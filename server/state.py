"""Shared application state: per-token CopilotClient cache."""

from __future__ import annotations

import asyncio
import logging

from copilot import CopilotClient, SubprocessConfig
from fastapi import Request

logger = logging.getLogger("copilot_proxy")

# Cache of token -> CopilotClient so we don't spawn a new subprocess per request.
_clients: dict[str | None, CopilotClient] = {}
_clients_lock = asyncio.Lock()


async def get_client(token: str | None) -> CopilotClient:
    """Return a running CopilotClient for *token*, creating one on first use."""
    async with _clients_lock:
        if token not in _clients:
            cfg = SubprocessConfig(github_token=token)
            client = CopilotClient(cfg)
            await client.start()
            _clients[token] = client
            logger.info("CopilotClient started for token %s", "****" if token else "<default>")
        return _clients[token]


def extract_token(request: Request) -> str | None:
    """Extract a Bearer token from the Authorization header, if present."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        value = auth[7:].strip()
        return value if value else None
    return None
