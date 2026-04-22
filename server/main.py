"""FastAPI server exposing OpenAI-compatible endpoints powered by the GitHub Copilot SDK."""

from __future__ import annotations

import argparse
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .auth import router as auth_router
from .handlers import (
    handle_chat_completion,
    handle_chat_completion_stream,
    handle_models,
)
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
                logger.info(
                    "CopilotClient stopped for token %s",
                    "****" if token else "<default>",
                )
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


_HOME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Copilot Proxy - Home</title>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
      min-height: 100vh;
      background:
        radial-gradient(circle at 10% -10%, rgba(56,139,253,0.25), transparent 40%),
        radial-gradient(circle at 90% 0%, rgba(63,185,80,0.16), transparent 35%),
        #0d1117;
      color: #e6edf3;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 24px;
    }
    .shell { width: 100%; max-width: 760px; }
    .header { margin-bottom: 18px; }
    .header h1 { font-size: 28px; font-weight: 700; margin-bottom: 8px; }
    .header p { color: #9da7b3; font-size: 14px; }
    .cards {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: 12px;
    }
    .card {
      background: rgba(22, 27, 34, 0.92);
      border: 1px solid #30363d;
      border-radius: 12px;
      padding: 18px;
    }
    .card h2 { font-size: 18px; margin-bottom: 8px; }
    .card p { color: #9da7b3; font-size: 13px; line-height: 1.5; min-height: 58px; }
    .btn {
      margin-top: 14px;
      display: inline-block;
      text-decoration: none;
      border: 1px solid #30363d;
      background: #21262d;
      color: #e6edf3;
      padding: 8px 12px;
      border-radius: 8px;
      font-weight: 600;
    }
    .btn:hover { border-color: #4f5865; }
    .btn.primary { background: #1f6feb; border-color: #1f6feb; color: #fff; }
  </style>
</head>
<body>
  <div class="shell">
    <div class="header">
      <h1>Copilot Proxy UI</h1>
      <p>Endpoint centralizzato per navigare tra autenticazione e dashboard token.</p>
    </div>

    <div class="cards">
      <div class="card">
        <h2>Authentication</h2>
        <p>Login OAuth device flow oppure verifica di un token esistente per Copilot.</p>
        <a class="btn primary" href="/auth">Apri /auth</a>
      </div>

      <div class="card">
        <h2>Dashboard</h2>
        <p>Quota requests, sessioni persistite per token e azioni di cleanup sessioni.</p>
        <a class="btn" href="/auth/dashboard">Apri /auth/dashboard</a>
      </div>
    </div>
  </div>
</body>
</html>"""


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def home_page():
    return HTMLResponse(_HOME_HTML)


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
    parser = argparse.ArgumentParser(
        description="Copilot OpenAI-compatible proxy server"
    )
    parser.add_argument(
        "-p", "--port", type=int, default=8081, help="Port to listen on"
    )
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--log-level", default="info", help="Log level")
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    logger.info("Starting Copilot OpenAI proxy on http://%s:%d", args.host, args.port)
    logger.info("Endpoints:")
    logger.info("  GET  /                  (home UI)")
    logger.info("  GET  /auth              (login UI)")
    logger.info("  GET  /auth/dashboard    (token dashboard UI)")
    logger.info("  POST /auth/device/start (start GitHub device flow)")
    logger.info("  POST /auth/device/poll  (poll device flow)")
    logger.info("  GET  /auth/status       (check auth status)")
    logger.info("  GET  /v1/models")
    logger.info("  POST /v1/chat/completions")
    logger.info("  GET  /health")

    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


if __name__ == "__main__":
    cli()
