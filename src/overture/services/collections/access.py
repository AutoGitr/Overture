"""What every collection workflow shares: the server, stored rows, policy and locks."""

lazy from collections.abc import AsyncGenerator, Iterable, Sequence
lazy from contextlib import asynccontextmanager
lazy from dataclasses import dataclass

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.models.catalog import CatalogCollection
lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.media_collection import CollectionLibrary, MediaCollection
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...domain import (
    UNMANAGED_REFUSAL,
    MediaType,
    ServerType,
    TermKind,
    library_server,
)
lazy from ...media_servers.registry import CollectionProvider, ProviderRegistry
lazy from ...repositories.catalog import CatalogRepository
lazy from ...repositories.collection_items import (
    CollectionItem,
    CollectionItemRepository,
    TermSelection,
)
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.libraries import LibraryRepository
lazy from ...schemas.collections import (
    CollectionLibraryCriteria,
    FilterGroup,
)
lazy from ...utils.collection_fields import PLEX_COLLECTION_KEY
lazy from ...utils.collection_formats import is_within_active_window
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.locks import KeyedLock
lazy from ...utils.time import local_now
lazy from ..needs import AssetNeeds
lazy from ..schedule_store import catalog_enabled
lazy from . import COLLECTIONS_LOCK
lazy from .copies import ServerCopy, held_copies, lead_part, server_copies
lazy from .criteria import criteria_terms
lazy from .policy import CollectionPolicy, RuleOrPolicy, resolve_policy


@dataclass(slots=True, frozen=True)
class LibraryScope:
    """One library of a collection: what it selects, and from which items."""

    library_id: str
    media_type: MediaType
    criteria: FilterGroup
    items: list[CollectionItem]
    #: The collection the criteria select for, which never counts as another
    #: collection holding an item; none for one not saved yet.
    collection_id: int | None = None


async def catalog_collections(
    session: AsyncSession, tmdb_ids: set[int]
) -> dict[int, CatalogCollection]:
    """Return the catalog's entries for these TMDB collections, if it is enabled."""
    if not tmdb_ids or not await catalog_enabled(session):
        return {}
    return await CatalogRepository(session).collections_by_tmdb_id(tmdb_ids)


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
        needs: AssetNeeds,
    ) -> None:
        self.database = database
        #: Keeps assets' needs in step with the policies that decide them.
        self.needs = needs
        self.app_config = app_config
        self.asset_locks = asset_locks
        #: The configured servers' providers.
        self.provider_registry = provider_registry
        self._publisher = publisher

    @property
    def supported(self) -> bool:
        """Whether any configured server has collections at all."""
        return self.provider_registry.collections_supported

    def require_collections(self) -> None:
        """Refuse to serve collections where no server has any.

        Raises:
            PublicServiceError: When no configured server has collections.
        """
        if not self.supported:
            raise PublicServiceError(
                400, "No configured media server supports collections."
            )

    def provider(self, server_id: int) -> CollectionProvider:
        """Return a configured server's provider when it supports collections.

        Raises:
            PublicServiceError: When that server is not configured or has no
                collections.
        """
        provider = self.provider_registry.get(server_id)
        if provider.collections is None:
            raise PublicServiceError(
                400, f"{provider.server.title} does not support collections."
            )
        return provider

    def library_provider(self, library_id: str) -> CollectionProvider:
        """Return the provider of the server holding a library.

        Raises:
            PublicServiceError: When its server is not configured or has no
                collections.
        """
        return self.provider(self._server_of(library_id))

    def server_type(self, library_id: str) -> ServerType:
        """Return the kind of server holding a library."""
        return self.provider_registry.type_of(self._server_of(library_id))

    def plex(self, library_id: str) -> bool:
        """Whether a library is on a Plex server."""
        return self.server_type(library_id) is ServerType.PLEX

    def server_types(self, library_ids: Iterable[str]) -> set[ServerType]:
        """The kinds of server holding these libraries."""
        return {self.server_type(library_id) for library_id in library_ids}

    def configured_types(self) -> set[ServerType]:
        """The kinds of every configured server."""
        return {server.type for server in self.provider_registry.servers}

    def server_order(self) -> list[int]:
        """The configured servers' database numbers, the lead first."""
        return self.provider_registry.server_ids()

    def spans_libraries(self, server_type: ServerType) -> bool:
        """Whether a kind of server keeps one collection for several libraries."""
        return self.provider_registry.spans_libraries(server_type)

    def configured(self, server_id: int) -> bool:
        """Whether the database's server *server_id* is configured."""
        return self.provider_registry.configured_server_id(server_id)

    def lead(self, row: MediaCollection) -> CollectionLibrary | None:
        """The part whose copy, on the earliest configured server, stands for it."""
        return lead_part(row, self.server_order())

    def held_copies(self, row: MediaCollection) -> list[CollectionLibrary]:
        """A part for each copy on the configured servers, the lead first."""
        return held_copies(row, self.server_order())

    def copies(self, row: MediaCollection) -> list[ServerCopy]:
        """The server collections this collection needs on the configured servers.

        A part on a server no longer configured waits for its return, or for
        a sync to move it to the server that holds its titles now.
        """
        return [
            copy
            for copy in server_copies(
                row,
                spans_libraries=lambda server_id: (
                    self.configured(server_id)
                    and self.provider(server_id).collections_span_libraries
                ),
            )
            if self.configured(copy.server_id)
        ]

    @staticmethod
    def _server_of(library_id: str) -> int:
        try:
            return library_server(library_id)
        except ValueError as exc:
            raise PublicServiceError(422, str(exc)) from exc

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
        self.require_collections()
        row = await CollectionRepository(session).get_listed(collection_id)
        if row is None:
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
        if row.rule is None:
            raise PublicServiceError(409, UNMANAGED_REFUSAL)
        return row

    async def group(
        self, session: AsyncSession, name: str | None
    ) -> CollectionGroup | None:
        """Return the group named *name*, if there is one."""
        return await CollectionRepository(session).group(name)

    async def policy(
        self,
        session: AsyncSession,
        group: CollectionGroup | None,
        rule: RuleOrPolicy = None,
    ) -> CollectionPolicy:
        return resolve_policy(await get_app_settings(session), group, rule)

    async def library_types(self, library_ids: Iterable[str]) -> dict[str, MediaType]:
        """What each of the servers' libraries holds.

        Raises:
            PublicServiceError: 422 when no configured server lists such a library.
        """
        requested = list(library_ids)
        wanted = set(requested)
        async with self.database.read_session() as session:
            types = {
                library.id: library.media_type
                for library in await LibraryRepository(session).listed(wanted)
            }
        if wanted - types.keys():
            raise PublicServiceError(422, "Select one of the servers' libraries")
        return {library_id: types[library_id] for library_id in requested}

    async def _require_type(self, library_id: str, media_type: MediaType) -> None:
        if (await self.library_types([library_id]))[library_id] is not media_type:
            raise PublicServiceError(
                422, "Select a library of the collection's media type"
            )

    async def library_items(
        self,
        library_id: str,
        media_type: MediaType,
        terms: TermSelection | None = None,
    ) -> list[CollectionItem]:
        """The stored items of one of the server's libraries of this media type."""
        await self._require_type(library_id, media_type)
        async with self.database.read_session() as session:
            return await CollectionItemRepository(session).library_items(
                media_type, library_id, terms
            )

    async def part_items(
        self, part: CollectionLibrary, terms: TermSelection | None = None
    ) -> list[CollectionItem]:
        """The stored items of a library a collection spans, listed or not."""
        async with self.database.read_session() as session:
            return await CollectionItemRepository(session).library_items(
                part.media_type, part.library_id, terms
            )

    async def term_counts(
        self, library_id: str, media_type: MediaType, kind: TermKind
    ) -> dict[str, int]:
        """How many of the items of one of the server's libraries hold each value."""
        await self._require_type(library_id, media_type)
        async with self.database.read_session() as session:
            return await CollectionItemRepository(session).term_counts(
                media_type, library_id, kind
            )

    async def scope(
        self,
        repo: CollectionItemRepository,
        library_id: str,
        media_type: MediaType,
        criteria: FilterGroup,
        *,
        collection_id: int | None,
        smart: bool,
    ) -> LibraryScope:
        """A library's criteria, with its items holding the values they test.

        Syncing a smart collection compares every label on Plex too.
        """
        labels = (TermKind.LABEL,) if smart and self.plex(library_id) else ()
        return LibraryScope(
            library_id=library_id,
            media_type=media_type,
            criteria=criteria,
            items=await repo.library_items(
                media_type, library_id, criteria_terms([criteria], labels)
            ),
            collection_id=collection_id,
        )

    async def scopes(
        self,
        libraries: Sequence[CollectionLibraryCriteria],
        collection_id: int | None = None,
        *,
        smart: bool = False,
    ) -> list[LibraryScope]:
        """Each library's criteria with the items it selects from."""
        types = await self.library_types(entry.library_id for entry in libraries)
        async with self.database.read_session() as session:
            repo = CollectionItemRepository(session)
            return [
                await self.scope(
                    repo,
                    entry.library_id,
                    types[entry.library_id],
                    entry.criteria,
                    collection_id=collection_id,
                    smart=smart,
                )
                for entry in libraries
            ]

    async def memberships(
        self, library_id: str, excluding: int | None
    ) -> dict[int, list[str]]:
        """The IDs of the collections each item of a library belongs to."""
        async with self.database.read_session() as session:
            return await CollectionItemRepository(session).memberships_by_item(
                library_id, excluding
            )

    async def collection_titles(self, collection_ids: Iterable[int]) -> dict[int, str]:
        """The titles of the collections *collection_ids* names that exist."""
        async with self.database.read_session() as session:
            return await CollectionRepository(session).titles_of(collection_ids)

    async def filter_choices(
        self, library_id: str, media_type: MediaType, key: str
    ) -> list[tuple[str, str]]:
        """List the keys a library's server gives a field's values, with the values.

        Criteria name a collection by its ID, so Plex's collections, which it
        lists by their rating key, are given as the collections Overture
        knows them by; one Overture does not know is left out.
        """
        provider = self.library_provider(library_id)
        choices = await provider.filter_choices(library_id, media_type, key)
        if key != PLEX_COLLECTION_KEY:
            return choices
        async with self.database.read_session() as session:
            copies = await CollectionRepository(session).server_copies(
                provider.server_id
            )
        return [
            (choice, str(copies[rating_key]))
            for choice, rating_key in choices
            if rating_key in copies
        ]

    async def region(self) -> str:
        """The region TMDB charts and streaming services are read for."""
        async with self.database.read_session() as session:
            return (await get_app_settings(session)).tmdb_region

    def active(self, start: str | None, end: str | None) -> bool:
        today = local_now(self.app_config.tzinfo).date()
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
