import asyncio
import logging
import shutil

from fastapi import HTTPException, Request

from copilot import CopilotClient
from copilot.client import SubprocessConfig

logger = logging.getLogger(__name__)

_clients: dict[str, CopilotClient] = {}
_client_lock = asyncio.Lock()
_base_subprocess_kwargs: dict[str, str] = {}


async def startup() -> None:
    global _base_subprocess_kwargs

    # If no bundled CLI is available, allow using the system `copilot` binary
    # found in PATH (e.g. when `copilot` is installed system-wide).
    _base_subprocess_kwargs = {}
    system_cli = shutil.which("copilot")
    if system_cli:
        _base_subprocess_kwargs["cli_path"] = system_cli

    logger.info("Copilot client manager ready")


async def shutdown() -> None:
    global _clients

    for token, client in list(_clients.items()):
        await client.stop()
        logger.info("CopilotClient stopped for token %s", _token_label(token))

    _clients = {}


def get_bearer_token(request: Request) -> str:
    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")

    if scheme.lower() != "bearer" or not token.strip():
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "message": "Missing bearer token. Use the OpenAI api_key as the GitHub token.",
                    "type": "invalid_request_error",
                    "param": None,
                    "code": "missing_api_key",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    return token.strip()


async def get_client(github_token: str) -> CopilotClient:
    client = _clients.get(github_token)
    if client is not None:
        return client

    async with _client_lock:
        client = _clients.get(github_token)
        if client is not None:
            return client

        kwargs = dict(_base_subprocess_kwargs)
        kwargs["github_token"] = github_token
        config = SubprocessConfig(**kwargs)
        client = CopilotClient(config)
        await client.start()
        _clients[github_token] = client
        logger.info("CopilotClient started for token %s", _token_label(github_token))
        return client


def _token_label(token: str) -> str:
    if len(token) <= 8:
        return "***"
    return f"{token[:4]}...{token[-4:]}"
