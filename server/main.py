"""FastAPI server exposing OpenAI-compatible endpoints powered by the GitHub Copilot SDK."""

from __future__ import annotations

import argparse
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import router as auth_router
from .handlers import handle_chat_completion, handle_chat_completion_stream, handle_models
from .models import ChatCompletionRequest, ErrorResponse, ErrorDetail
from .state import _clients, _clients_lock, extract_token, get_client

logger = logging.getLogger("copilot_proxy")


# ── Lifespan ─────────────────────────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    async with _clients_lock:
        for token, client in _clients.items():
            try:
                await client.stop()
                logger.info("CopilotClient stopped for token %s", "****" if token else "<default>")
            except Exception:
                logger.exception("Error stopping CopilotClient")


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(title="Copilot OpenAI Proxy", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


# ── Routes ───────────────────────────────────────────────────────────────────


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/v1/models")
async def models_endpoint(request: Request):
    try:
        token = extract_token(request)
        client = await get_client(token)
        result = await handle_models(client)
        return result.model_dump()
    except Exception:
        logger.exception("Error listing models")
        return _error_response(500, "Failed to list models")


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    try:
        body = await request.json()
        req = ChatCompletionRequest(**body)
    except Exception as exc:
        return _error_response(400, f"Invalid request body: {exc}")

    if not req.model:
        return _error_response(400, "Model is required")
    if not req.messages:
        return _error_response(400, "Messages are required")

    try:
        token = extract_token(request)
        client = await get_client(token)

        if req.stream:
            return StreamingResponse(
                handle_chat_completion_stream(client, req),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "X-Accel-Buffering": "no",
                },
            )

        result = await handle_chat_completion(client, req)
        return result.model_dump(exclude_none=True)
    except Exception:
        logger.exception("Error handling chat completion")
        return _error_response(500, "Internal server error")


# ── Helpers ──────────────────────────────────────────────────────────────────


def _error_response(status: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorResponse(
            error=ErrorDetail(message=message, type="api_error")
        ).model_dump(),
    )


# ── CLI entry-point ──────────────────────────────────────────────────────────


def cli():
    parser = argparse.ArgumentParser(description="Copilot OpenAI-compatible proxy server")
    parser.add_argument("-p", "--port", type=int, default=8081, help="Port to listen on")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--log-level", default="info", help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("Starting Copilot OpenAI proxy on http://%s:%d", args.host, args.port)
    logger.info("Endpoints:")
    logger.info("  GET  /auth              (login UI)")
    logger.info("  POST /auth/device/start (start GitHub device flow)")
    logger.info("  POST /auth/device/poll  (poll device flow)")
    logger.info("  GET  /auth/status       (check auth status)")
    logger.info("  GET  /v1/models")
    logger.info("  POST /v1/chat/completions")
    logger.info("  GET  /health")

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    cli()
