"""The runtime's media-server providers, one for each configured server."""

lazy import logging
lazy from collections.abc import Callable, Mapping
lazy from typing import Any

lazy from ..config import MediaServerConfig, Settings
lazy from ..domain import ArtType, ServerType, library_parts
lazy from ..utils.errors import PublicServiceError
lazy from .adapters import ServerSection, ServerWebLinks
lazy from .base import BaseMediaServerProvider
lazy from .emby import EmbyProvider
lazy from .errors import MediaServerError
lazy from .health import MediaServerHealth, MediaServerHealthTracker
lazy from .jellyfin import JellyfinProvider
lazy from .plex import PlexProvider

logger = logging.getLogger(__name__)

#: Why server-bound work is refused under MEDIA_SERVERS=none.
NO_MEDIA_SERVER = "No media server is configured"

#: A provider whose server has collections Overture can manage.
type CollectionProvider = BaseMediaServerProvider[Any]
#: Any configured server's provider.
type Provider = BaseMediaServerProvider[Any]

#: The provider class that adapts each media server.
_PROVIDERS: frozendict[
    ServerType, type[PlexProvider] | type[JellyfinProvider] | type[EmbyProvider]
] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        ServerType.PLEX: PlexProvider,
        ServerType.JELLYFIN: JellyfinProvider,
        ServerType.EMBY: EmbyProvider,
    }
)


class ProviderRegistry:
    """Own a provider for every configured media server, in MEDIA_SERVERS order.

    The database identifies each server by a number the server roster assigns
    when Overture starts (:meth:`attach`); library IDs carry it, so work on a
    library finds its server's provider. A provider is built the first time its
    server needs one and kept until the runtime closes it.
    """

    def __init__(self, *, app_config: Settings) -> None:
        self._app_config = app_config
        self._ids: dict[str, int] = {}
        self._providers: dict[int, Provider] = {}
        #: Whether each server answered its last request, by server key.
        self._health = {
            server.key: MediaServerHealthTracker() for server in self.servers
        }

    @property
    def servers(self) -> tuple[MediaServerConfig, ...]:
        """The configured servers, the lead first."""
        return self._app_config.MEDIA_SERVERS

    @property
    def configured(self) -> bool:
        """Whether any media server is configured; MEDIA_SERVERS=none has none."""
        return bool(self.servers)

    def attach(self, ids: Mapping[str, int]) -> None:
        """Note the database's number for each configured server, by its key."""
        self._ids = {server.key: ids[server.key] for server in self.servers}

    def server_ids(self) -> list[int]:
        """The configured servers' database numbers, the lead first."""
        return [self._id(server) for server in self.servers]

    def providers(self) -> list[Provider]:
        """Every configured server's provider, the lead first."""
        return [self.get(server_id) for server_id in self.server_ids()]

    def get(self, server_id: int) -> Provider:
        """Return the provider of the server the database numbers *server_id*.

        Raises:
            PublicServiceError: 409 when that server is not configured.
        """
        if (provider := self._providers.get(server_id)) is not None:
            return provider
        if not self.configured:
            raise PublicServiceError(409, NO_MEDIA_SERVER)
        server = next(
            (server for server in self.servers if self._id(server) == server_id), None
        )
        if server is None:
            raise PublicServiceError(
                409, "That media server is no longer configured in MEDIA_SERVERS"
            )
        provider = _PROVIDERS[server.type](
            server=server,
            server_id=server_id,
            app_config=self._app_config,
            health=self._health[server.key],
        )
        self._providers[server_id] = provider
        return provider

    def for_library(self, library_id: str) -> Provider:
        """Return the provider of the server holding a library.

        Raises:
            PublicServiceError: 409 when that server is not configured.
        """
        parts = library_parts(library_id)
        if parts is None:
            raise PublicServiceError(409, f"Library {library_id} names no server")
        return self.get(parts[0])

    def configured_server_id(self, server_id: int) -> bool:
        """Return whether the database's server *server_id* is configured."""
        return server_id in self._ids.values()

    def type_of(self, server_id: int) -> ServerType:
        """Return the kind of a configured server, without building its provider."""
        return self._server(server_id).type

    def title_of(self, server_id: int) -> str:
        """Return how a configured server is named to users."""
        return self._server(server_id).title

    @staticmethod
    def spans_libraries(server_type: ServerType) -> bool:
        """Whether a kind of server keeps one collection for several libraries."""
        return _PROVIDERS[server_type].collections_span_libraries

    def collection_providers(self) -> list[CollectionProvider]:
        """The providers of servers with collections Overture can manage."""
        return [
            provider
            for provider in self.providers()
            if provider.collections is not None
        ]

    @property
    def collections_supported(self) -> bool:
        """Whether any configured server has collections Overture can manage."""
        return any(
            _PROVIDERS[server.type].collections is not None for server in self.servers
        )

    def health(self, server_key: str) -> MediaServerHealth:
        """Return what a configured server's last request found."""
        return self._health[server_key].current

    def listen(
        self, listener: Callable[[MediaServerConfig, MediaServerHealth], None]
    ) -> None:
        """Call *listener* with a server and its new health when that changes."""
        for server in self.servers:
            self._health[server.key].listen(
                lambda health, server=server: listener(server, health)
            )

    async def require_reachable(self, server_id: int) -> None:
        """Probe a server last seen down, so a run fails once instead of per item.

        Raises:
            MediaServerError: When the server still does not answer.
        """
        provider = self.get(server_id)
        if provider.health.current.down and not await provider.test_connection():
            raise MediaServerError(
                provider.health.current.message
                or f"{provider.server.title} is unreachable"
            )

    async def reachable(self) -> list[Provider]:
        """The configured servers that answer, the lead first.

        Raises:
            MediaServerError: When none of them does.
        """
        reachable: list[Provider] = []
        failure: MediaServerError | None = None
        for provider in self.providers():
            try:
                await self.require_reachable(provider.server_id)
            except MediaServerError as exc:
                logger.warning("%s left out: %s", provider.server.title, exc.message)
                failure = exc
                continue
            reachable.append(provider)
        if not reachable and failure is not None:
            raise failure
        return reachable

    async def libraries(self) -> list[tuple[Provider, ServerSection]]:
        """Every reachable server's movie and show libraries, the lead's first.

        A server that does not answer is left out, unless none does.

        Raises:
            MediaServerError: When no server answers.
        """
        found: list[tuple[Provider, ServerSection]] = []
        answered = False
        failure: MediaServerError | None = None
        for provider in await self.reachable():
            try:
                sections = await provider.get_sections()
            except MediaServerError as exc:
                logger.warning("%s libraries left out: %s", provider.server.title, exc)
                failure = exc
                continue
            answered = True
            found += [(provider, section) for section in sections]
        if not answered and failure is not None:
            raise failure
        return found

    async def web_links(self) -> list[tuple[Provider, ServerWebLinks]]:
        """Where each reachable server's web app opens items and collections.

        Raises:
            MediaServerError: When no server answers.
        """
        links: list[tuple[Provider, ServerWebLinks]] = []
        failure: MediaServerError | None = None
        for provider in await self.reachable():
            try:
                links.append((provider, await provider.web_links()))
            except MediaServerError as exc:
                logger.warning("%s web links left out: %s", provider.server.title, exc)
                failure = exc
        if not links and failure is not None:
            raise failure
        return links

    async def fetch_server_active_art_url(
        self, server_id: int, server_item_id: str, art_type: ArtType
    ) -> str | None:
        """Return the image URL currently selected on one of the media servers."""
        if not self.configured_server_id(server_id):
            return None
        provider = self.get(server_id)
        try:
            return await provider.get_active_art_url(server_item_id, art_type)
        except MediaServerError as exc:
            logger.debug(
                "Could not read the active %s of %s item %s: %s",
                art_type,
                provider.server.title,
                server_item_id,
                exc,
            )
            return None

    def for_url(self, url: str) -> Provider | None:
        """Return the provider of the server *url* is on, if it is on one."""
        return next(
            (
                provider
                for provider in self.providers()
                if provider.server.is_trusted_url(url)
            ),
            None,
        )

    def download_headers(self, url: str) -> dict[str, str]:
        """Return the credentials of the server *url* is on, if it is on one."""
        provider = self.for_url(url)
        return {} if provider is None else provider.get_download_headers(url)

    async def close(self) -> None:
        """Close provider-owned HTTP clients."""
        for provider in self._providers.values():
            await provider.close()

    def _id(self, server: MediaServerConfig) -> int:
        try:
            return self._ids[server.key]
        except KeyError:
            raise RuntimeError(
                "The server roster has not attached the media servers yet"
            ) from None

    def _server(self, server_id: int) -> MediaServerConfig:
        for server in self.servers:
            if self._id(server) == server_id:
                return server
        raise PublicServiceError(
            409, "That media server is no longer configured in MEDIA_SERVERS"
        )
