"""Core request handlers: models listing and chat completions."""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, AsyncIterator

from copilot import CopilotClient, PermissionHandler
from copilot.generated.session_events import SessionEvent, SessionEventType

from .converters import (
    build_prompt,
    determine_available_tools,
    extract_attachments,
    extract_system_message,
    openai_tools_to_copilot,
)
from .models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    Choice,
    ChoiceMessage,
    ErrorResponse,
    ErrorDetail,
    ModelData,
    ModelsResponse,
    ToolCall,
    ToolCallFunction,
    Usage,
)

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 300.0  # 5 minutes


# ── /v1/models ───────────────────────────────────────────────────────────────


async def handle_models(client: CopilotClient) -> ModelsResponse:
    """List available models from the Copilot SDK."""
    models = await client.list_models()
    now = int(time.time())
    return ModelsResponse(
        data=[
            ModelData(id=m.id, created=now, owned_by="github-copilot")
            for m in models
        ]
    )


# ── /v1/chat/completions (non-streaming) ─────────────────────────────────────


async def handle_chat_completion(
    client: CopilotClient,
    req: ChatCompletionRequest,
) -> ChatCompletionResponse:
    """Handle a non-streaming chat completion request."""

    prompt = build_prompt(req.messages)
    system_msg = extract_system_message(req.messages)
    attachments = await extract_attachments(req.messages)

    captured_calls: list[dict[str, Any]] = []
    copilot_tools = None
    available_tools = None
    if req.tools:
        copilot_tools = openai_tools_to_copilot(req.tools, captured_calls)
        available_tools = determine_available_tools(req.tools, req.tool_choice)

    session_kwargs: dict[str, Any] = {
        "on_permission_request": PermissionHandler.approve_all,
        "model": req.model,
        "streaming": False,
    }
    if copilot_tools:
        session_kwargs["tools"] = copilot_tools
    if available_tools is not None:
        session_kwargs["available_tools"] = available_tools
    if system_msg:
        session_kwargs["system_message"] = {"mode": "replace", "content": system_msg}
    if req.reasoning_effort:
        effort = _normalize_reasoning_effort(req.reasoning_effort)
        if effort:
            session_kwargs["reasoning_effort"] = effort

    session = await client.create_session(**session_kwargs)
    try:
        content_parts: list[str] = []
        tool_calls_out: list[ToolCall] = []
        done = asyncio.Event()
        error_msg: str | None = None

        def on_event(event: SessionEvent) -> None:
            nonlocal error_msg
            try:
                if event.type == SessionEventType.ASSISTANT_MESSAGE:
                    if event.data.content:
                        content_parts.append(event.data.content)
                    if event.data.tool_requests:
                        for tr in event.data.tool_requests:
                            args_str = json.dumps(tr.arguments) if tr.arguments else "{}"
                            tool_calls_out.append(
                                ToolCall(
                                    id=tr.tool_call_id,
                                    type="function",
                                    function=ToolCallFunction(
                                        name=tr.name,
                                        arguments=args_str,
                                    ),
                                )
                            )
                elif event.type == SessionEventType.SESSION_IDLE:
                    done.set()
                elif event.type == SessionEventType.SESSION_ERROR:
                    error_msg = getattr(event.data, "message", None) or str(event.data)
                    done.set()
            except Exception:
                logger.exception("Error in event handler")

        unsubscribe = session.on(on_event)

        send_kwargs: dict[str, Any] = {}
        if attachments:
            send_kwargs["attachments"] = attachments

        await session.send(prompt, **send_kwargs)

        try:
            await asyncio.wait_for(done.wait(), timeout=REQUEST_TIMEOUT)
        except TimeoutError:
            logger.warning("Request timed out after %ss", REQUEST_TIMEOUT)

        unsubscribe()

        if error_msg:
            logger.error("Session error: %s", error_msg)

        # If we captured tool calls via intercepting handlers but didn't get
        # them from tool_requests, build from captured_calls instead.
        if captured_calls and not tool_calls_out:
            for cc in captured_calls:
                args_str = json.dumps(cc["arguments"]) if cc["arguments"] else "{}"
                tool_calls_out.append(
                    ToolCall(
                        id=cc["tool_call_id"],
                        type="function",
                        function=ToolCallFunction(
                            name=cc["tool_name"],
                            arguments=args_str,
                        ),
                    )
                )

        finish_reason = "tool_calls" if tool_calls_out else "stop"
        content = "".join(content_parts) or None
        # When the model made tool calls, the content is often just the
        # deferred placeholder — drop it.
        if tool_calls_out:
            content = None

        return ChatCompletionResponse(
            id=f"chatcmpl-{uuid.uuid4().hex[:12]}",
            created=int(time.time()),
            model=req.model,
            choices=[
                Choice(
                    index=0,
                    message=ChoiceMessage(
                        role="assistant",
                        content=content,
                        tool_calls=tool_calls_out or None,
                    ),
                    finish_reason=finish_reason,
                )
            ],
            usage=Usage(),
        )
    finally:
        await session.disconnect()


# ── /v1/chat/completions (streaming) ─────────────────────────────────────────


async def handle_chat_completion_stream(
    client: CopilotClient,
    req: ChatCompletionRequest,
) -> AsyncIterator[str]:
    """Handle a streaming chat completion request, yielding SSE lines."""

    prompt = build_prompt(req.messages)
    system_msg = extract_system_message(req.messages)
    attachments = await extract_attachments(req.messages)

    captured_calls: list[dict[str, Any]] = []
    copilot_tools = None
    available_tools = None
    if req.tools:
        copilot_tools = openai_tools_to_copilot(req.tools, captured_calls)
        available_tools = determine_available_tools(req.tools, req.tool_choice)

    session_kwargs: dict[str, Any] = {
        "on_permission_request": PermissionHandler.approve_all,
        "model": req.model,
        "streaming": True,
    }
    if copilot_tools:
        session_kwargs["tools"] = copilot_tools
    if available_tools is not None:
        session_kwargs["available_tools"] = available_tools
    if system_msg:
        session_kwargs["system_message"] = {"mode": "replace", "content": system_msg}
    if req.reasoning_effort:
        effort = _normalize_reasoning_effort(req.reasoning_effort)
        if effort:
            session_kwargs["reasoning_effort"] = effort

    completion_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())

    has_tools = bool(req.tools)

    session = await client.create_session(**session_kwargs)
    try:
        done_event = asyncio.Event()
        buffered_deltas: list[str] = []
        tool_calls_collected: list[ToolCall] = []
        # When tools are NOT in the request we can use a queue for true
        # real-time streaming.  When tools ARE present we buffer everything
        # and replay after the session finishes so we can decide whether to
        # emit content or tool_calls (but never the noise the model produces
        # after our intercepting handler returns the dummy result).
        queue: asyncio.Queue[dict | None] = asyncio.Queue()
        tool_call_seen = False

        def on_event(event: SessionEvent) -> None:
            nonlocal tool_call_seen
            try:
                if event.type == SessionEventType.ASSISTANT_MESSAGE_DELTA:
                    delta = getattr(event.data, "delta_content", None)
                    if not delta:
                        return
                    if has_tools:
                        # Buffer: only keep deltas that arrived BEFORE the
                        # first tool call (the rest is noise).
                        if not tool_call_seen:
                            buffered_deltas.append(delta)
                    else:
                        queue.put_nowait({"type": "delta", "content": delta})

                elif event.type == SessionEventType.ASSISTANT_MESSAGE:
                    if event.data.tool_requests:
                        tool_call_seen = True
                        for i, tr in enumerate(event.data.tool_requests):
                            args_str = (
                                json.dumps(tr.arguments)
                                if tr.arguments
                                else "{}"
                            )
                            tool_calls_collected.append(
                                ToolCall(
                                    index=i,
                                    id=tr.tool_call_id,
                                    type="function",
                                    function=ToolCallFunction(
                                        name=tr.name,
                                        arguments=args_str,
                                    ),
                                )
                            )

                elif event.type == SessionEventType.SESSION_IDLE:
                    if has_tools:
                        done_event.set()
                    else:
                        queue.put_nowait(None)  # sentinel

                elif event.type == SessionEventType.SESSION_ERROR:
                    msg = getattr(event.data, "message", None) or str(event.data)
                    logger.error("Session error: %s", msg)
                    if has_tools:
                        done_event.set()
                    else:
                        queue.put_nowait(None)
            except Exception:
                logger.exception("Error in streaming event handler")

        unsubscribe = session.on(on_event)

        send_kwargs: dict[str, Any] = {}
        if attachments:
            send_kwargs["attachments"] = attachments

        await session.send(prompt, **send_kwargs)

        # Initial chunk with role
        yield _sse_line(
            ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=req.model,
                choices=[Choice(index=0, delta=ChoiceMessage(role="assistant"))],
            )
        )

        if has_tools:
            # ── Buffered path (tools present) ────────────────────────────
            try:
                await asyncio.wait_for(done_event.wait(), timeout=REQUEST_TIMEOUT)
            except TimeoutError:
                logger.warning("Streaming timed out")

            unsubscribe()

            # Fallback: use captured_calls if tool_requests was empty
            if captured_calls and not tool_calls_collected:
                for i, cc in enumerate(captured_calls):
                    args_str = (
                        json.dumps(cc["arguments"]) if cc["arguments"] else "{}"
                    )
                    tool_calls_collected.append(
                        ToolCall(
                            index=i,
                            id=cc["tool_call_id"],
                            type="function",
                            function=ToolCallFunction(
                                name=cc["tool_name"],
                                arguments=args_str,
                            ),
                        )
                    )

            if tool_calls_collected:
                # Emit tool call chunks (drop buffered content)
                for tc in tool_calls_collected:
                    yield _sse_line(
                        ChatCompletionChunk(
                            id=completion_id,
                            created=created,
                            model=req.model,
                            choices=[
                                Choice(
                                    index=0,
                                    delta=ChoiceMessage(
                                        tool_calls=[
                                            ToolCall(
                                                index=tc.index,
                                                id=tc.id,
                                                type="function",
                                                function=ToolCallFunction(
                                                    name=tc.function.name,
                                                    arguments="",
                                                ),
                                            )
                                        ]
                                    ),
                                )
                            ],
                        )
                    )
                    yield _sse_line(
                        ChatCompletionChunk(
                            id=completion_id,
                            created=created,
                            model=req.model,
                            choices=[
                                Choice(
                                    index=0,
                                    delta=ChoiceMessage(
                                        tool_calls=[
                                            ToolCall(
                                                index=tc.index,
                                                function=ToolCallFunction(
                                                    name="",
                                                    arguments=tc.function.arguments,
                                                ),
                                            )
                                        ]
                                    ),
                                )
                            ],
                        )
                    )
                finish_reason = "tool_calls"
            else:
                # No tool calls — replay buffered content as chunks
                for delta in buffered_deltas:
                    yield _sse_line(
                        ChatCompletionChunk(
                            id=completion_id,
                            created=created,
                            model=req.model,
                            choices=[
                                Choice(
                                    index=0,
                                    delta=ChoiceMessage(content=delta),
                                )
                            ],
                        )
                    )
                finish_reason = "stop"

        else:
            # ── Real-time streaming path (no tools) ──────────────────────
            while True:
                try:
                    item = await asyncio.wait_for(
                        queue.get(), timeout=REQUEST_TIMEOUT
                    )
                except TimeoutError:
                    logger.warning("Streaming timed out")
                    break

                if item is None:
                    break

                if item["type"] == "delta":
                    yield _sse_line(
                        ChatCompletionChunk(
                            id=completion_id,
                            created=created,
                            model=req.model,
                            choices=[
                                Choice(
                                    index=0,
                                    delta=ChoiceMessage(content=item["content"]),
                                )
                            ],
                        )
                    )

            unsubscribe()
            finish_reason = "stop"

        # Final chunk with finish_reason
        yield _sse_line(
            ChatCompletionChunk(
                id=completion_id,
                created=created,
                model=req.model,
                choices=[
                    Choice(
                        index=0,
                        delta=ChoiceMessage(),
                        finish_reason=finish_reason,
                    )
                ],
            )
        )

        yield "data: [DONE]\n\n"
    finally:
        await session.disconnect()


# ── Helpers ──────────────────────────────────────────────────────────────────


def _sse_line(chunk: ChatCompletionChunk) -> str:
    return f"data: {chunk.model_dump_json(exclude_none=True)}\n\n"


def _normalize_reasoning_effort(value: str | None) -> str | None:
    if not value:
        return None
    v = value.strip().lower()
    if v in ("low", "medium", "high", "xhigh"):
        return v
    return None
