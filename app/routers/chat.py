"""
POST /v1/chat/completions — OpenAI-compatible chat completions backed by the
GitHub Copilot SDK.  Supports streaming (SSE), vision (image_url), multi-turn
conversations, tool/function calling, and reasoning_effort.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time
import urllib.request
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, create_model

from copilot import define_tool
from copilot.session import PermissionHandler

from app.copilot_manager import get_client
from app.schemas import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    DeltaMessage,
    FunctionCall,
    FunctionCallDelta,
    ResponseMessage,
    StreamChoice,
    ToolCall,
    ToolCallDelta,
    Usage,
)

logger = logging.getLogger(__name__)
router = APIRouter()

# ---------------------------------------------------------------------------
# Message helpers
# ---------------------------------------------------------------------------


def _text_of(msg) -> str:
    """Return the plain-text content of a ChatMessage."""
    if isinstance(msg.content, str):
        return msg.content
    if isinstance(msg.content, list):
        return "\n".join(p.text for p in msg.content if p.type == "text" and p.text)
    return ""


def _extract_system(messages) -> str | None:
    """Collect all system / developer messages into one string."""
    parts = [_text_of(m) for m in messages if m.role in ("system", "developer")]
    return "\n\n".join(parts) if parts else None


def _build_context(messages) -> tuple[str | None, str, list[dict]]:
    """Return (conversation_history | None, prompt, attachments).

    * ``conversation_history`` — formatted prior turns (everything before the
      last user message).
    * ``prompt`` — the text of the last user message (or a continuation
      sentinel when the last message is not from the user).
    * ``attachments`` — image blobs extracted from the last user message.
    """
    non_system = [m for m in messages if m.role not in ("system", "developer")]

    if not non_system:
        return None, "", []

    last = non_system[-1]

    if last.role == "user":
        history_msgs = non_system[:-1]
        prompt = _text_of(last)
        attachments = _extract_attachments(last)
    else:
        # Last message is assistant or tool result — include everything as
        # history and ask the model to continue.
        history_msgs = non_system
        prompt = "Continue the conversation based on the context above."
        attachments = []

    history = _format_history(history_msgs) if history_msgs else None
    return history, prompt, attachments


def _format_history(msgs) -> str:
    parts: list[str] = []
    for m in msgs:
        if m.role == "user":
            parts.append(f"User: {_text_of(m)}")
        elif m.role == "assistant":
            if m.tool_calls:
                for tc in m.tool_calls:
                    parts.append(
                        f"Assistant: [Tool call: {tc.function.name}"
                        f"({tc.function.arguments})]"
                    )
            else:
                parts.append(f"Assistant: {_text_of(m)}")
        elif m.role == "tool":
            name = m.name or "tool"
            parts.append(f"Tool result ({name}): {m.content}")
    return "\n\n".join(parts)


def _extract_attachments(msg) -> list[dict]:
    """Convert image_url content parts into Copilot SDK blob attachments."""
    if not isinstance(msg.content, list):
        return []

    attachments: list[dict] = []
    for part in msg.content:
        if part.type != "image_url" or part.image_url is None:
            continue

        url = part.image_url.url

        if url.startswith("data:"):
            # data:image/png;base64,iVBOR…
            header, data = url.split(",", 1)
            mime = header.split(":")[1].split(";")[0]
            attachments.append({"type": "blob", "data": data, "mimeType": mime})
        elif url.startswith(("http://", "https://")):
            try:
                b64, mime = _download_image(url)
                attachments.append({"type": "blob", "data": b64, "mimeType": mime})
            except Exception:
                logger.warning("Failed to download image: %s", url, exc_info=True)
    return attachments


def _download_image(url: str) -> tuple[str, str]:
    req = urllib.request.Request(url, headers={"User-Agent": "copilot-proxy/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        data = resp.read()
        mime = resp.headers.get("Content-Type", "image/png")
        return base64.b64encode(data).decode(), mime


# ---------------------------------------------------------------------------
# Dynamic tool creation
# ---------------------------------------------------------------------------

_JSON_TYPE_MAP: dict[str, type] = {
    "string": str,
    "number": float,
    "integer": int,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _schema_to_model(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """Build a Pydantic model from a JSON-Schema ``properties`` dict."""
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    fields: dict[str, Any] = {}

    for pname, pschema in props.items():
        py_type = _JSON_TYPE_MAP.get(pschema.get("type", "string"), str)
        desc = pschema.get("description")
        if pname in required:
            fields[pname] = (py_type, Field(description=desc))
        else:
            fields[pname] = (py_type | None, Field(default=None, description=desc))

    if not fields:
        # Fallback: accept anything
        class _Generic(BaseModel):
            model_config = {"extra": "allow"}

        _Generic.__name__ = _Generic.__qualname__ = f"{name}_params"
        return _Generic

    return create_model(f"{name}_params", **fields)


def _build_tools(
    openai_tools: list | None,
    tracker: list[dict],
) -> list:
    """Convert OpenAI tool definitions → Copilot ``define_tool`` objects."""
    if not openai_tools:
        return []

    tools = []
    for td in openai_tools:
        if td.type != "function":
            continue
        fn = td.function

        params_model = (
            _schema_to_model(fn.name, fn.parameters) if fn.parameters else None
        )

        # -- closure over *fn_name* ------------------------------------------
        def _make_handler(fn_name: str):
            async def _handler(params=None, **_kw):
                if params is not None and hasattr(params, "model_dump_json"):
                    args = params.model_dump_json()
                elif params is not None:
                    args = json.dumps(params) if isinstance(params, dict) else str(params)
                else:
                    args = "{}"
                tracker.append(
                    {
                        "id": f"call_{uuid.uuid4().hex[:24]}",
                        "name": fn_name,
                        "arguments": args,
                    }
                )
                # Return empty string so the SDK feeds *something* back to the
                # model.  We will discard the model's follow-up text and return
                # tool_calls to the OpenAI client instead.
                return ""

            # The SDK inspects __name__ and __annotations__
            _handler.__name__ = fn_name
            if params_model is not None:
                _handler.__annotations__["params"] = params_model
            return _handler

        handler = _make_handler(fn.name)

        tool = define_tool(fn.name, description=fn.description or "")(handler)
        tools.append(tool)

    return tools


# ---------------------------------------------------------------------------
# Non-streaming response
# ---------------------------------------------------------------------------


async def _non_stream(session, prompt: str, attachments, tracker, model: str):
    send_kw: dict[str, Any] = {}
    if attachments:
        send_kw["attachments"] = attachments

    response = await session.send_and_wait(prompt, **send_kw)

    # If tools were called, return tool_calls (ignore model text).
    if tracker:
        return ChatCompletionResponse(
            model=model,
            choices=[
                Choice(
                    message=ResponseMessage(
                        tool_calls=[
                            ToolCall(
                                id=tc["id"],
                                function=FunctionCall(
                                    name=tc["name"], arguments=tc["arguments"]
                                ),
                            )
                            for tc in tracker
                        ],
                    ),
                    finish_reason="tool_calls",
                )
            ],
        )

    content = ""
    if response is not None and hasattr(response, "data") and response.data is not None:
        content = getattr(response.data, "content", "") or ""

    return ChatCompletionResponse(
        model=model,
        choices=[
            Choice(
                message=ResponseMessage(content=content),
                finish_reason="stop",
            )
        ],
    )


# ---------------------------------------------------------------------------
# Streaming response
# ---------------------------------------------------------------------------


async def _stream(
    session,
    prompt: str,
    attachments,
    tracker: list[dict],
    model: str,
) -> AsyncGenerator[str, None]:
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    queue: asyncio.Queue = asyncio.Queue()

    def _on_event(event):
        # put_nowait is fine — callback runs in the same event loop
        queue.put_nowait(event)

    unsubscribe = session.on(_on_event)

    send_kw: dict[str, Any] = {}
    if attachments:
        send_kw["attachments"] = attachments

    await session.send(prompt, **send_kw)

    # First chunk: role announcement
    yield _sse(
        ChatCompletionChunk(
            id=chunk_id,
            created=created,
            model=model,
            choices=[StreamChoice(delta=DeltaMessage(role="assistant"))],
        )
    )

    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=300)
            except asyncio.TimeoutError:
                break

            etype = event.type.value if hasattr(event.type, "value") else str(event.type)

            if etype == "assistant.message_delta":
                # If tools have already been tracked, suppress post-tool text.
                if tracker:
                    continue
                delta = getattr(event.data, "delta_content", None) or ""
                if delta:
                    yield _sse(
                        ChatCompletionChunk(
                            id=chunk_id,
                            created=created,
                            model=model,
                            choices=[StreamChoice(delta=DeltaMessage(content=delta))],
                        )
                    )

            elif etype in ("session.idle", "session.error"):
                # Finished — emit tool_calls or stop
                if tracker:
                    for i, tc in enumerate(tracker):
                        yield _sse(
                            ChatCompletionChunk(
                                id=chunk_id,
                                created=created,
                                model=model,
                                choices=[
                                    StreamChoice(
                                        delta=DeltaMessage(
                                            tool_calls=[
                                                ToolCallDelta(
                                                    index=i,
                                                    id=tc["id"],
                                                    type="function",
                                                    function=FunctionCallDelta(
                                                        name=tc["name"],
                                                        arguments=tc["arguments"],
                                                    ),
                                                )
                                            ]
                                        )
                                    )
                                ],
                            )
                        )
                    yield _sse(
                        ChatCompletionChunk(
                            id=chunk_id,
                            created=created,
                            model=model,
                            choices=[
                                StreamChoice(
                                    delta=DeltaMessage(),
                                    finish_reason="tool_calls",
                                )
                            ],
                        )
                    )
                else:
                    yield _sse(
                        ChatCompletionChunk(
                            id=chunk_id,
                            created=created,
                            model=model,
                            choices=[
                                StreamChoice(
                                    delta=DeltaMessage(),
                                    finish_reason="stop",
                                )
                            ],
                        )
                    )
                yield "data: [DONE]\n\n"
                break
    finally:
        unsubscribe()
        await session.disconnect()


def _sse(chunk: ChatCompletionChunk) -> str:
    return f"data: {chunk.model_dump_json()}\n\n"


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/v1/chat/completions")
async def chat_completions(request: ChatCompletionRequest):
    client = get_client()

    # 1. System message
    system_content = _extract_system(request.messages)

    # 2. Conversation history + last prompt + attachments
    history, prompt, attachments = _build_context(request.messages)

    # 3. Assemble full system prompt
    sys_parts: list[str] = []
    if system_content:
        sys_parts.append(system_content)
    if history:
        sys_parts.append(
            "Below is the conversation so far. "
            "Continue naturally from the last turn.\n\n"
            f"<conversation_history>\n{history}\n</conversation_history>"
        )
    full_system = "\n\n".join(sys_parts) if sys_parts else None

    # 4. Tools
    tool_tracker: list[dict] = []
    copilot_tools = _build_tools(request.tools, tool_tracker)

    # 5. Build session kwargs
    session_kw: dict[str, Any] = {
        "model": request.model,
        "on_permission_request": PermissionHandler.approve_all,
    }
    if full_system:
        session_kw["system_message"] = {"mode": "replace", "content": full_system}
    if copilot_tools:
        session_kw["tools"] = copilot_tools
    if request.reasoning_effort:
        session_kw["reasoning_effort"] = request.reasoning_effort

    session = await client.create_session(**session_kw)

    try:
        if request.stream:
            return StreamingResponse(
                _stream(session, prompt, attachments, tool_tracker, request.model),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        response = await _non_stream(
            session, prompt, attachments, tool_tracker, request.model
        )
        await session.disconnect()
        return response
    except Exception:
        await session.disconnect()
        raise
