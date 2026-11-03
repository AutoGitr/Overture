"""What every collection workflow shares: the server, stored rows, policy and locks."""

lazy from collections.abc import AsyncGenerator
lazy from contextlib import asynccontextmanager
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
lazy from ...utils.collection_formats import is_within_active_window
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.locks import KeyedLock
lazy from . import COLLECTIONS_LOCK
lazy from .policy import CollectionPolicy, RuleOrPolicy, resolve_policy


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

    @asynccontextmanager
    async def locked(self, collection_id: int) -> AsyncGenerator[None]:
        """Hold the listing lock and the collection's own asset lock."""
        async with (
            self.asset_locks.acquire(COLLECTIONS_LOCK),
            self.asset_locks.acquire(f"collection:{collection_id}"),
        ):
            yield

    async def require(
        self, session: AsyncSession, collection_id: int, media_type: MediaType
    ) -> MediaCollection:
        """Return a listed collection of the requested media type.

        Raises:
            PublicServiceError: When the last sync listed no such collection.
        """
        provider = self.provider()
        row = await CollectionRepository(session).get_listed(collection_id, media_type)
        if row is None or row.server_type is not provider.server_type:
            raise PublicServiceError(
                404, "Collection not found for the selected media type"
            )
        return row

    async def require_managed(
        self, session: AsyncSession, collection_id: int, media_type: MediaType
    ) -> MediaCollection:
        """Return a listed collection Overture manages; only adoption changes others.

        Raises:
            PublicServiceError: 409 when the collection has not been adopted.
        """
        row = await self.require(session, collection_id, media_type)
        if await CollectionRepository(session).rule(collection_id) is None:
            raise PublicServiceError(409, UNMANAGED_REFUSAL)
        return row

    async def policy(
        self,
        session: AsyncSession,
        media_type: MediaType,
        group: str | None,
        rule: RuleOrPolicy = None,
    ) -> CollectionPolicy:
        return resolve_policy(
            await get_app_settings(session),
            await CollectionRepository(session).group_policy(
                self.server_type, media_type, group
            ),
            rule,
        )

    async def library_items(
        self, library_id: str, media_type: MediaType
    ) -> list[MediaItem]:
        """The stored items of one of the server's libraries of this media type."""
        sections = await self.provider().get_sections()
        if not any(
            section.key == library_id and section.media_type is media_type
            for section in sections
        ):
            raise PublicServiceError(
                422, "Select a library of the collection's media type"
            )
        async with self.database.read_session() as session:
            return await CollectionRepository(session).library_items(
                media_type, library_id
            )

    async def collection_titles(
        self, media_type: MediaType, library_id: str
    ) -> dict[int, list[str]]:
        async with self.database.read_session() as session:
            return await CollectionRepository(session).titles_by_item(
                media_type, library_id
            )

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
