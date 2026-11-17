"""System health and status services."""

lazy import asyncio
lazy import logging

lazy from .. import protocols
lazy from ..media_servers.errors import MediaServerError
lazy from ..media_servers.registry import Provider, ProviderRegistry
lazy from ..schemas.settings import ConnectivityStatusResponse

logger = logging.getLogger(__name__)


async def check_media_server_connection(provider_registry: ProviderRegistry) -> bool:
    """Check that every configured media server is reachable.

    Each server's answer is recorded in its health, which tells clients.
    """
    if not provider_registry.configured:
        return False
    answers = await asyncio.gather(
        *(_answers(provider) for provider in provider_registry.providers())
    )
    return all(answers)


async def _answers(provider: Provider) -> bool:
    try:
        return await provider.test_connection()
    except MediaServerError as e:
        logger.warning("%s check failed: %s", provider.server.title, e)
        return False


async def get_service_status(
    provider_registry: ProviderRegistry,
    tmdb_client: protocols.ConnectivityProbe,
) -> ConnectivityStatusResponse:
    """Probe all external services and report which are reachable."""
    statuses = await asyncio.gather(
        check_media_server_connection(provider_registry),
        tmdb_client.test_connection(),
        return_exceptions=True,
    )
    for name, outcome in zip(("media server", "TMDB"), statuses, strict=True):
        if isinstance(outcome, asyncio.CancelledError):
            raise outcome
        if isinstance(outcome, Exception):
            logger.error("The %s connectivity check failed", name, exc_info=outcome)
    return ConnectivityStatusResponse(
        media_server=statuses[0] is True, tmdb=statuses[1] is True
    )
