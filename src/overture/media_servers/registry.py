"""The runtime's media-server provider."""

lazy import logging
lazy from collections.abc import Callable
lazy from typing import Any

lazy from ..config import Settings
lazy from ..domain import ArtType, ServerType
lazy from ..utils.errors import PublicServiceError
lazy from .base import BaseMediaServerProvider
lazy from .emby import EmbyProvider
lazy from .errors import MediaServerError
lazy from .health import MediaServerHealthTracker
lazy from .jellyfin import JellyfinProvider
lazy from .plex import PlexProvider

logger = logging.getLogger(__name__)

#: Why server-bound work is refused under MEDIA_SERVER=none.
NO_MEDIA_SERVER = "No media server is configured"

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
    def configured(self) -> bool:
        """Whether a media server is configured; MEDIA_SERVER=none has none."""
        return self._app_config.MEDIA_SERVER is not None

    @property
    def provider(self) -> BaseMediaServerProvider[Any]:
        """Return the configured media server's provider.

        Raises:
            PublicServiceError: 409 when no media server is configured.
        """
        server_type = self._app_config.MEDIA_SERVER
        if server_type is None:
            raise PublicServiceError(409, NO_MEDIA_SERVER)
        if server_type not in self._providers:
            self._providers[server_type] = _PROVIDERS[server_type](
                app_config=self._app_config, health=self.health
            )
        return self._providers[server_type]

    @property
    def collections(self) -> CollectionProvider | None:
        """Return the provider when its server supports collections."""
        if not self.configured:
            return None
        provider = self.provider
        if provider.collections is not None:
            return provider
        return None

    async def require_reachable(self) -> None:
        """Probe a server last seen down, so a run fails once instead of per item.

        Raises:
            MediaServerError: When the server still does not answer.
        """
        if (
            self.configured
            and self.health.current.down
            and not await self.provider.test_connection()
        ):
            raise MediaServerError(
                self.health.current.message or "The media server is unreachable"
            )

    async def fetch_server_active_art_url(
        self, server_id: str, art_type: ArtType
    ) -> str | None:
        """Return the image URL currently selected on the media server."""
        if not self.configured:
            return None
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
