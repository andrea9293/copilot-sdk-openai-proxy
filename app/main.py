import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.copilot_manager import shutdown, startup
from app.routers import chat, embeddings, models

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await startup()
    yield
    await shutdown()


app = FastAPI(
    title="Copilot SDK Proxy",
    description="OpenAI-compatible API backed by the GitHub Copilot SDK",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat.router)
app.include_router(models.router)
app.include_router(embeddings.router)


@app.exception_handler(FastAPIHTTPException)
async def http_exception_handler(request: Request, exc: FastAPIHTTPException):
    detail = exc.detail
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=exc.status_code, content=detail, headers=exc.headers)

    logger.warning("HTTP error on %s %s: %s", request.method, request.url.path, detail)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "message": str(detail),
                "type": "invalid_request_error",
                "param": None,
                "code": None,
            }
        },
        headers=exc.headers,
    )


@app.exception_handler(Exception)
async def openai_error_handler(request: Request, exc: Exception):
    """Return all unhandled errors in the OpenAI error envelope format."""
    if isinstance(exc, RequestValidationError):
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "message": str(exc),
                    "type": "invalid_request_error",
                    "param": None,
                    "code": None,
                }
            },
        )

    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    status = getattr(exc, "status_code", 500)
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict) and "error" in detail:
        return JSONResponse(status_code=status, content=detail)
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "message": str(exc),
                "type": "server_error",
                "param": None,
                "code": None,
            }
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc):
    return JSONResponse(
        status_code=422,
        content={
            "error": {
                "message": str(exc),
                "type": "invalid_request_error",
                "param": None,
                "code": None,
            }
        },
    )


@app.get("/health")
async def health():
    return {"status": "ok"}


def run():
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level,
    )


if __name__ == "__main__":
    run()
