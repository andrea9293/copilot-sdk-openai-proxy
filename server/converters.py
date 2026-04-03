"""Convert between OpenAI API types and Copilot SDK types."""

from __future__ import annotations

import base64
import json
import logging
from typing import Any

import httpx

from copilot.tools import Tool, ToolInvocation, ToolResult

from .models import ContentPartImageURL, ContentPartText, Message, Tool as OAITool

logger = logging.getLogger(__name__)


# ── Prompt building ──────────────────────────────────────────────────────────


def build_prompt(messages: list[Message]) -> str:
    """Flatten an OpenAI messages array into a single prompt string.

    System / developer messages are skipped here (handled separately).
    """
    parts: list[str] = []

    for msg in messages:
        if msg.role in ("system", "developer"):
            continue

        text = _message_text(msg)

        if msg.role == "user":
            parts.append(f"[User]: {text}")

        elif msg.role == "assistant":
            if text:
                parts.append(f"[Assistant]: {text}")
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    parts.append(
                        f"[Assistant called tool {tc.function.name} "
                        f"with args: {tc.function.arguments}]"
                    )

        elif msg.role == "tool":
            tool_call_id = msg.tool_call_id or "unknown"
            parts.append(f"[Tool result for {tool_call_id}]: {text}")

    return "\n\n".join(parts)


def extract_system_message(messages: list[Message]) -> str | None:
    """Combine all system / developer messages into a single string."""
    parts: list[str] = []
    for msg in messages:
        if msg.role in ("system", "developer"):
            text = _message_text(msg)
            if text:
                parts.append(text)
    return "\n\n".join(parts) if parts else None


# ── Image / attachment extraction ────────────────────────────────────────────


async def extract_attachments(messages: list[Message]) -> list[dict[str, Any]]:
    """Return a list of Copilot ``BlobAttachment`` dicts from image_url content parts."""
    blobs: list[dict[str, Any]] = []
    for msg in messages:
        if not isinstance(msg.content, list):
            continue
        for part in msg.content:
            if isinstance(part, ContentPartImageURL):
                blob = await _image_url_to_blob(part.image_url.url)
                if blob:
                    blobs.append(blob)
    return blobs


async def _image_url_to_blob(url: str) -> dict[str, Any] | None:
    """Convert an image URL (data-URI or remote) to a BlobAttachment dict."""
    if url.startswith("data:"):
        return _parse_data_uri(url)
    return await _fetch_remote_image(url)


def _parse_data_uri(uri: str) -> dict[str, Any] | None:
    """Parse ``data:<mime>;base64,<data>`` into a BlobAttachment dict."""
    try:
        header, data = uri.split(",", 1)
        mime = header.split(":")[1].split(";")[0]
        return {"type": "blob", "data": data, "mimeType": mime}
    except Exception:
        logger.warning("Failed to parse data URI")
        return None


async def _fetch_remote_image(url: str) -> dict[str, Any] | None:
    """Download a remote image and return a BlobAttachment dict."""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            mime = resp.headers.get("content-type", "image/png").split(";")[0]
            data = base64.b64encode(resp.content).decode()
            return {"type": "blob", "data": data, "mimeType": mime}
    except Exception:
        logger.warning("Failed to fetch remote image: %s", url)
        return None


# ── Tool conversion ──────────────────────────────────────────────────────────


def openai_tools_to_copilot(
    tools: list[OAITool],
    captured_calls: list[dict[str, Any]],
) -> list[Tool]:
    """Convert OpenAI tool definitions to Copilot ``Tool`` objects.

    Each tool gets an *intercepting handler* that captures the call details
    (name, id, arguments) into ``captured_calls`` and returns a dummy result
    so that the SDK can respond to the CLI.  The actual execution is expected
    to happen on the client side (standard OpenAI flow).
    """
    copilot_tools: list[Tool] = []
    for t in tools:
        if t.type != "function":
            continue
        fn = t.function
        name = fn.name

        def _make_handler(tool_name: str):
            def handler(inv: ToolInvocation) -> ToolResult:
                captured_calls.append(
                    {
                        "tool_call_id": inv.tool_call_id,
                        "tool_name": tool_name,
                        "arguments": inv.arguments,
                    }
                )
                return ToolResult(
                    text_result_for_llm="[Tool call deferred to client]",
                    result_type="success",
                )

            return handler

        copilot_tools.append(
            Tool(
                name=name,
                description=fn.description or "",
                handler=_make_handler(name),
                parameters=fn.parameters,
            )
        )
    return copilot_tools


def determine_available_tools(
    tools: list[OAITool] | None,
    tool_choice: Any,
) -> list[str] | None:
    """Derive the ``available_tools`` list for the Copilot session.

    Restricts the model to only the user-supplied tools (same logic as the Go
    implementation).  Returns ``None`` if no tools are provided.
    """
    if not tools:
        return None

    names = [t.function.name for t in tools if t.type == "function" and t.function.name]
    if not names:
        return None

    if tool_choice is None:
        return names

    if isinstance(tool_choice, str):
        if tool_choice == "none":
            return []
        # "auto", "required", ""
        return names

    if isinstance(tool_choice, dict):
        # {"type": "function", "function": {"name": "..."}}
        if tool_choice.get("type") == "function":
            fn = tool_choice.get("function", {})
            chosen = fn.get("name", "")
            if chosen:
                return [chosen]
        return names

    return names


# ── Helpers ──────────────────────────────────────────────────────────────────


def _message_text(msg: Message) -> str:
    """Extract plain text from a Message regardless of content type."""
    if msg.content is None:
        return ""
    if isinstance(msg.content, str):
        return msg.content
    # list[ContentPart]
    parts: list[str] = []
    for p in msg.content:
        if isinstance(p, ContentPartText):
            parts.append(p.text)
        elif isinstance(p, ContentPartImageURL):
            parts.append("[image]")
    return "\n".join(parts)
