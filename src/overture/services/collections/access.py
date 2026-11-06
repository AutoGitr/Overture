"""What every collection workflow shares: the server, stored rows, policy and locks."""

lazy from collections.abc import AsyncGenerator, Iterable, Sequence
lazy from contextlib import asynccontextmanager
lazy from dataclasses import dataclass
lazy from datetime import datetime

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import UNMANAGED_REFUSAL, MediaType, ServerType
lazy from ...media_servers.registry import CollectionProvider, ProviderRegistry
lazy from ...repositories.collections import CollectionRepository
lazy from ...schemas.collections import CollectionLibraryCriteria, FilterGroup
lazy from ...utils.collection_formats import is_within_active_window
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.locks import KeyedLock
lazy from . import COLLECTIONS_LOCK
lazy from .copies import ServerCopy, server_copies
lazy from .policy import CollectionPolicy, RuleOrPolicy, resolve_policy


@dataclass(slots=True, frozen=True)
class LibraryScope:
    """One library of a collection: what it selects, and from which items."""

    library_id: str
    media_type: MediaType
    criteria: FilterGroup
    items: list[MediaItem]


class CollectionAccess:
    """Reach the server's collections and the rows, policy and locks behind them."""

    def __init__(
        self,
        *,
        database: Database,
        provider_registry: ProviderRegistry,
        publisher: protocols.EventPublisher,
        asset_locks: KeyedLock[int | str],
        app_config: Settings,
    ) -> None:
        self.database = database
        self.app_config = app_config
        self.asset_locks = asset_locks
        self._provider_registry = provider_registry
        self._publisher = publisher

    @property
    def supported(self) -> bool:
        """Whether the media server has collections at all."""
        return self._provider_registry.collections is not None

    def provider(self) -> CollectionProvider:
        """Return the media server's provider when it supports collections.

        Raises:
            PublicServiceError: When the media server has no collections.
        """
        provider = self._provider_registry.collections
        if provider is None:
            raise PublicServiceError(
                400, "The media server does not support collections."
            )
        return provider

    @property
    def server_type(self) -> ServerType:
        return self.provider().server_type

    @property
    def plex(self) -> bool:
        return self.server_type is ServerType.PLEX

    @property
    def spans_libraries(self) -> bool:
        return self.provider().collections_span_libraries

    def copies(self, row: MediaCollection) -> list[ServerCopy]:
        """The server collections this collection needs on this server."""
        return server_copies(row, spans_libraries=self.spans_libraries)

    @asynccontextmanager
    async def locked(self, collection_id: int) -> AsyncGenerator[None]:
        """Hold the listing lock and the collection's own asset lock."""
        async with (
            self.asset_locks.acquire(COLLECTIONS_LOCK),
            self.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            yield

    async def require(
        self, session: AsyncSession, collection_id: int
    ) -> MediaCollection:
        """Return a listed collection.

        Raises:
            PublicServiceError: When the last sync listed no such collection.
        """
        provider = self.provider()
        row = await CollectionRepository(session).get_listed(collection_id)
        if row is None or row.server_type is not provider.server_type:
            raise PublicServiceError(404, "Collection not found")
        return row

    async def require_managed(
        self, session: AsyncSession, collection_id: int
    ) -> MediaCollection:
        """Return a listed collection Overture manages; only adoption changes others.

        Raises:
            PublicServiceError: 409 when the collection has not been adopted.
        """
        row = await self.require(session, collection_id)
        if await CollectionRepository(session).rule(collection_id) is None:
            raise PublicServiceError(409, UNMANAGED_REFUSAL)
        return row

    async def policy(
        self,
        session: AsyncSession,
        group: str | None,
        rule: RuleOrPolicy = None,
    ) -> CollectionPolicy:
        return resolve_policy(
            await get_app_settings(session),
            await CollectionRepository(session).group_policy(self.server_type, group),
            rule,
        )

    async def library_types(self, library_ids: Iterable[str]) -> dict[str, MediaType]:
        """What each of the server's libraries holds.

        Raises:
            PublicServiceError: 422 when the server has no such library.
        """
        sections = {
            section.key: section.media_type
            for section in await self.provider().get_sections()
        }
        try:
            return {library_id: sections[library_id] for library_id in library_ids}
        except KeyError as exc:
            raise PublicServiceError(
                422, "Select one of the server's libraries"
            ) from exc

    async def library_items(
        self, library_id: str, media_type: MediaType
    ) -> list[MediaItem]:
        """The stored items of one of the server's libraries of this media type."""
        if (await self.library_types([library_id]))[library_id] is not media_type:
            raise PublicServiceError(
                422, "Select a library of the collection's media type"
            )
        async with self.database.read_session() as session:
            return await CollectionRepository(session).library_items(
                media_type, library_id
            )

    async def scopes(
        self, libraries: Sequence[CollectionLibraryCriteria]
    ) -> list[LibraryScope]:
        """Each library's criteria with the items it selects from."""
        types = await self.library_types(entry.library_id for entry in libraries)
        async with self.database.read_session() as session:
            repo = CollectionRepository(session)
            return [
                LibraryScope(
                    library_id=entry.library_id,
                    media_type=types[entry.library_id],
                    criteria=entry.criteria,
                    items=await repo.library_items(
                        types[entry.library_id], entry.library_id
                    ),
                )
                for entry in libraries
            ]

    async def collection_titles(self, library_id: str) -> dict[int, list[str]]:
        async with self.database.read_session() as session:
            return await CollectionRepository(session).titles_by_item(library_id)

    async def region(self) -> str:
        """The region TMDB charts and streaming services are read for."""
        async with self.database.read_session() as session:
            return (await get_app_settings(session)).tmdb_region

    def active(self, start: str | None, end: str | None) -> bool:
        today = datetime.now(self.app_config.tzinfo).date()
        return is_within_active_window(start, end, today)

    async def updated(self, collection_id: int | None) -> None:
        """Tell clients one collection changed."""
        await self._publisher.broadcast(
            "collection.updated", {"collection_id": collection_id}
        )

    async def changed(self) -> None:
        """Tell clients the list of collections changed."""
        await self._publisher.broadcast("collections.changed")

    async def broadcast(self, event: str, payload: object) -> None:
        await self._publisher.broadcast(event, payload)
