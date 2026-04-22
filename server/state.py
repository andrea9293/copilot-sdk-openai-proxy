"""Shared application state: per-token CopilotClient cache."""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from copilot import CopilotClient, SubprocessConfig
from fastapi import Request

logger = logging.getLogger("copilot_proxy")

SESSION_KEEP_COUNT = max(0, int(os.getenv("COPILOT_SESSION_KEEP_COUNT", "10")))
SESSION_PRUNE_INTERVAL_SECONDS = max(
    0.0,
    float(os.getenv("COPILOT_SESSION_PRUNE_INTERVAL_SECONDS", "120")),
)

# Cache of token -> CopilotClient so we don't spawn a new subprocess per request.
_clients: dict[str | None, CopilotClient] = {}
_clients_lock = asyncio.Lock()
_last_prune_at: dict[str | None, float] = {}


def _parse_iso8601(value: str) -> datetime:
    """Parse an ISO-8601 timestamp, supporting trailing 'Z'."""
    try:
        normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


async def _prune_old_sessions(client: CopilotClient) -> None:
    """Delete old sessions, keeping only the most recently modified ones."""
    if SESSION_KEEP_COUNT < 1:
        logger.warning("Session pruning disabled because keep count is < 1")
        return

    sessions = await client.list_sessions()
    total = len(sessions)
    if total <= SESSION_KEEP_COUNT:
        return

    ordered = sorted(
        sessions,
        key=lambda s: _parse_iso8601(s.modifiedTime),
        reverse=True,
    )
    stale_sessions = ordered[SESSION_KEEP_COUNT:]

    deleted = 0
    for session in stale_sessions:
        try:
            await client.delete_session(session.sessionId)
            deleted += 1
        except Exception:
            logger.exception(
                "Failed deleting stale Copilot session %s", session.sessionId
            )

    logger.info(
        "Pruned %d Copilot sessions (total=%d, kept=%d)",
        deleted,
        total,
        SESSION_KEEP_COUNT,
    )


async def _maybe_prune_sessions(token: str | None, client: CopilotClient) -> None:
    """Run session pruning at most once per interval per token."""
    now = asyncio.get_running_loop().time()
    last = _last_prune_at.get(token)
    if last is not None and (now - last) < SESSION_PRUNE_INTERVAL_SECONDS:
        return

    _last_prune_at[token] = now
    try:
        await _prune_old_sessions(client)
    except Exception:
        logger.exception("Session pruning failed")


async def get_client(token: str | None) -> CopilotClient:
    """Return a running CopilotClient for *token*, creating one on first use."""
    async with _clients_lock:
        if token not in _clients:
            cfg = SubprocessConfig(github_token=token)
            client = CopilotClient(cfg)
            await client.start()
            _clients[token] = client
            logger.info(
                "CopilotClient started for token %s", "****" if token else "<default>"
            )
        client = _clients[token]

    await _maybe_prune_sessions(token, client)
    return client


def extract_token(request: Request) -> str | None:
    """Extract a Bearer token from the Authorization header, if present."""
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        value = auth[7:].strip()
        return value if value else None
    return None
