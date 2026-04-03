"""Pydantic models for the OpenAI-compatible API surface."""

from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field


# ── Content parts (multimodal messages) ──────────────────────────────────────


class ImageURL(BaseModel):
    url: str
    detail: str | None = None


class ContentPartText(BaseModel):
    type: Literal["text"]
    text: str


class ContentPartImageURL(BaseModel):
    type: Literal["image_url"]
    image_url: ImageURL


ContentPart = Union[ContentPartText, ContentPartImageURL]


# ── Messages ─────────────────────────────────────────────────────────────────


class ToolCallFunction(BaseModel):
    name: str
    arguments: str


class ToolCall(BaseModel):
    index: int | None = None
    id: str | None = None
    type: str | None = "function"
    function: ToolCallFunction


class Message(BaseModel):
    """A single chat message.

    ``content`` may be a plain string **or** a structured content-parts array
    (e.g. text + image_url).  The validator keeps whichever form the caller
    sends; helpers in *converters.py* know how to inspect both.
    """

    role: str
    content: str | list[ContentPart] | None = None
    name: str | None = None
    tool_calls: list[ToolCall] | None = None
    tool_call_id: str | None = None


# ── Tool definitions ─────────────────────────────────────────────────────────


class ToolFunction(BaseModel):
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class Tool(BaseModel):
    type: Literal["function"] = "function"
    function: ToolFunction


# ── Request ──────────────────────────────────────────────────────────────────


class StreamOptions(BaseModel):
    include_usage: bool = False


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float | None = None
    top_p: float | None = None
    n: int | None = None
    stream: bool = False
    stream_options: StreamOptions | None = None
    stop: str | list[str] | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    presence_penalty: float | None = None
    frequency_penalty: float | None = None
    reasoning_effort: str | None = None
    tools: list[Tool] | None = None
    tool_choice: Any = None
    user: str | None = None


# ── Response (non-streaming) ─────────────────────────────────────────────────


class ChoiceMessage(BaseModel):
    role: str = "assistant"
    content: str | None = None
    tool_calls: list[ToolCall] | None = None


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage | None = None
    delta: ChoiceMessage | None = None
    finish_reason: str | None = None


class Usage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: list[Choice]
    usage: Usage | None = None
    system_fingerprint: str | None = None


# ── Response (streaming chunks) ──────────────────────────────────────────────


class ChatCompletionChunk(BaseModel):
    id: str
    object: str = "chat.completion.chunk"
    created: int
    model: str
    choices: list[Choice]
    system_fingerprint: str | None = None


# ── Models endpoint ──────────────────────────────────────────────────────────


class ModelData(BaseModel):
    id: str
    object: str = "model"
    created: int
    owned_by: str = "github-copilot"


class ModelsResponse(BaseModel):
    object: str = "list"
    data: list[ModelData]


# ── Errors ───────────────────────────────────────────────────────────────────


class ErrorDetail(BaseModel):
    message: str
    type: str
    param: str | None = None
    code: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
