import logging

from copilot import CopilotClient
from copilot.client import SubprocessConfig

from app.config import settings

logger = logging.getLogger(__name__)

_client: CopilotClient | None = None


async def startup() -> None:
    global _client

    kwargs: dict = {}
    if settings.github_token:
        kwargs["github_token"] = settings.github_token

    config = SubprocessConfig(**kwargs) if kwargs else None
    _client = CopilotClient(config)
    await _client.start()
    logger.info("CopilotClient started")


async def shutdown() -> None:
    global _client
    if _client is not None:
        await _client.stop()
        logger.info("CopilotClient stopped")
        _client = None


def get_client() -> CopilotClient:
    if _client is None:
        raise RuntimeError("CopilotClient not initialised – call startup() first")
    return _client
