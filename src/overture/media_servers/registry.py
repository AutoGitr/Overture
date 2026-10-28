"""The runtime's media-server provider."""

lazy import logging
lazy from collections.abc import Callable
lazy from typing import Any

lazy from ..config import Settings
lazy from ..domain import ArtType, ServerType
lazy from .base import BaseMediaServerProvider
lazy from .emby import EmbyProvider
lazy from .errors import MediaServerError
lazy from .health import MediaServerHealthTracker
lazy from .jellyfin import JellyfinProvider
lazy from .plex import PlexProvider

logger = logging.getLogger(__name__)

#: A provider whose server has collections Overture can manage.
type CollectionProvider = BaseMediaServerProvider[Any]

#: The provider class that adapts each media server.
_PROVIDERS: frozendict[ServerType, Callable[..., BaseMediaServerProvider[Any]]] = (
    frozendict(
        {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
            ServerType.PLEX: PlexProvider,
            ServerType.JELLYFIN: JellyfinProvider,
            ServerType.EMBY: EmbyProvider,
        }
    )
)


class ProviderRegistry:
    """Own the provider of the configured media server.

    A provider is built the first time the configured server needs one and
    kept until the runtime closes it.
    """

    def __init__(self, *, app_config: Settings) -> None:
        self._app_config = app_config
        self._providers: dict[ServerType, BaseMediaServerProvider[Any]] = {}
        #: Whether the media server answered its last request.
        self.health = MediaServerHealthTracker()

    @property
    def provider(self) -> BaseMediaServerProvider[Any]:
        """Return the configured media server's provider."""
        server_type = self._app_config.MEDIA_SERVER
        if server_type not in self._providers:
            self._providers[server_type] = _PROVIDERS[server_type](
                app_config=self._app_config, health=self.health
            )
        return self._providers[server_type]

    @property
    def collections(self) -> CollectionProvider | None:
        """Return the provider when its server supports collections."""
        provider = self.provider
        if provider.collections is not None:
            return provider
        return None

    async def fetch_server_active_art_url(
        self, server_id: str, art_type: ArtType
    ) -> str | None:
        """Return the image URL currently selected on the media server."""
        try:
            return await self.provider.get_active_art_url(server_id, art_type)
        except MediaServerError as exc:
            logger.debug(
                "Could not read the active %s of server item %s: %s",
                art_type,
                server_id,
                exc,
            )
            return None

    async def close(self) -> None:
        """Close provider-owned HTTP clients."""
        for provider in self._providers.values():
            await provider.close()
