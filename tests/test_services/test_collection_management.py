"""Collection lifecycle and rule runs against the real database."""

lazy from collections import Counter
lazy from collections.abc import Mapping, Sequence
lazy from dataclasses import dataclass, field
lazy from typing import Any, ClassVar, override
lazy from unittest.mock import AsyncMock

lazy import pytest
lazy from pydantic import SecretStr, ValidationError
lazy from sqlmodel import select

lazy from overture.config import Settings
lazy from overture.db.ledger import (
    clear_selection,
    read_asset,
    select_art,
)
lazy from overture.db.models.catalog import CatalogCollection
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.saved_schedule import SavedSchedule
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtStyle,
    ArtType,
    AssetStatus,
    AutoArtSource,
    CollectionFiltering,
    CollectionKind,
    CollectionMode,
    CollectionOrder,
    CollectionPosterStyle,
    FilterField,
    FilterOperator,
    MediaType,
    ScheduleKind,
    ServerAsset,
    ServerType,
    SetDimension,
    SourceType,
    SyncMode,
    TermKind,
    TmdbChart,
    TmdbPersonRole,
)
lazy from overture.integrations.arr import (
    ArrClient,
    ArrOptions,
    ArrRequest,
    ArrTag,
    ArrTagMatches,
    ArrTitle,
)
lazy from overture.integrations.mdblist import MDBListClient, MdblistList
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import (
    TMDBClient,
    TmdbCollection,
    TmdbDetails,
    TmdbPerson,
    TmdbTitle,
)
lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.media_servers.adapters import (
    CollectionDetails,
    MemberWrite,
    ServerCollection,
    ServerSection,
)
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.plex.provider import PlexProvider
lazy from overture.media_servers.registry import ProviderRegistry
lazy from overture.repositories.collection_items import (
    CollectionItem,
    CollectionItemRepository,
    TermSelection,
)
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.repositories.libraries import LibraryRepository
lazy from overture.repositories.saved_schedules import SavedScheduleRepository
lazy from overture.schemas.art import (
    ArtCandidate,
    ArtSourcesResponse,
    SaveCollectionArtRequest,
)
lazy from overture.schemas.collections import (
    GROUP_CONDITIONS_MAX,
    BulkCollectionOperation,
    CollectionAdoption,
    CollectionCreate,
    CollectionDetail,
    CollectionGenerator,
    CollectionGroupDelete,
    CollectionGroupPolicy,
    CollectionGroupRename,
    CollectionKindRequest,
    CollectionLibraryCriteria,
    CollectionMembersUpdate,
    CollectionOptions,
    CollectionPreviewRequest,
    CollectionRequest,
    CollectionRequestTitle,
    CollectionRuleWrite,
    CollectionSetPreview,
    CollectionSource,
    CustomSetValue,
    FieldCondition,
    FilterGroup,
    MdblistListRead,
    MdblistSource,
    RadarrTagSource,
    SetValueAlias,
    SonarrTagSource,
    SourceCondition,
    TmdbChartSource,
    TmdbCollectionSource,
    TmdbItemSource,
    TmdbListSource,
    TmdbPersonSource,
)
lazy from overture.schemas.common import Status, StatusResponse
lazy from overture.schemas.library_filters import (
    LibraryFilterMatchRequest,
    SavedFilterWrite,
)
lazy from overture.schemas.removal import AssetRemoval
lazy from overture.services.art.collection_art import CollectionArtService
lazy from overture.services.collections.criteria import CriteriaContext, evaluate
lazy from overture.services.collections.recommend import recommend_kind
lazy from overture.services.collections.rules import member_criteria
lazy from overture.services.collections.service import CollectionsService
lazy from overture.services.collections.sources import condition_label, source_label
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.media_server_roster import MediaServerRoster
lazy from overture.services.needs import AssetNeeds
lazy from overture.services.sync.reconciler import LibraryReconciler
lazy from overture.utils.art_urls import PublicArtUrl
lazy from overture.utils.collection_fields import FIELDS
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_catalog
lazy from tests.collection_helpers import copy_id, library_rule, stored_collection
lazy from tests.factories import seed_asset, seed_theme
lazy from tests.media_servers import TEST_SERVER_ID, configure, served_item, server_of
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    make_local_assets,
    make_remover,
    unused,
)
lazy from tests.sync_helpers import RecordedReport
lazy from tests.term_helpers import assign, holding
lazy from tests.test_services.test_collections_service import (
    FakeDownloads,
    FakePublisher,
)


class Provider(PlexProvider):
    def __init__(self, app_config: Settings) -> None:
        super().__init__(
            server=server_of(app_config, self.server_type),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        )
        self.created: list[str] = []
        self.deleted: list[str] = []
        #: Collections someone made on the server, by title, as Overture finds them.
        self.titled: dict[str, ServerCollection] = {}
        self.members: dict[str, list[str]] = {}
        self.options: dict[str, tuple[str, CollectionMode, CollectionOrder, bool]] = {}
        self.sort_titles: dict[str, str | None] = {}
        self.empty: dict[str, bool] = {}
        self.summaries: dict[str, str | None] = {}
        self.smart_filters: dict[str, str] = {}
        self.synced_labels: list[tuple[str, list[str], list[str]]] = []
        self.choices: dict[str, list[tuple[str, str]]] = {}
        #: The values each item holds per filter field, which a section's list
        #: of the field's values can leave out.
        self.item_choices: dict[tuple[str, str], list[tuple[str, str]]] = {}
        self.fail = False
        #: Libraries the server refuses to make a collection in.
        self.refused_libraries: set[str] = set()
        #: Collections someone deleted on the server behind Overture's back.
        self.gone: set[str] = set()
        self.rejected_updates: set[str] = set()
        self.queries: list[str] = []
        self.hub_orders: list[list[str]] = []

    @override
    async def _list_sections(self) -> list[ServerSection]:
        return [
            ServerSection("movies", "Movies", MediaType.MOVIE, library_id="1:movies"),
            ServerSection(
                "extra", "Extra movies", MediaType.MOVIE, library_id="1:extra"
            ),
            ServerSection("shows", "Shows", MediaType.SHOW, library_id="1:shows"),
        ]

    @override
    async def create_collection(
        self, library_id: str, title: str, media_type: MediaType, member_ids: list[str]
    ) -> ServerCollection:
        if self.fail or library_id in self.refused_libraries:
            raise MediaServerError("Create failed")
        self.created.append(title)
        identity = str(len(self.created))
        self.members[identity] = member_ids
        return ServerCollection(
            identity,
            title,
            tuple(member_ids),
            media_type=media_type,
            library_id=library_id,
        )

    @override
    async def find_collection(
        self, library_id: str, title: str, media_type: MediaType
    ) -> ServerCollection | None:
        return self.titled.get(title.casefold())

    @override
    async def create_smart_collection(
        self, library_id: str, title: str, media_type: MediaType, filter_query: str
    ) -> ServerCollection:
        if self.fail:
            raise MediaServerError("Smart create failed")
        self.created.append(title)
        identity = str(len(self.created))
        self.members[identity] = []
        self.smart_filters[identity] = filter_query
        return ServerCollection(
            identity,
            title,
            (),
            media_type=media_type,
            library_id=library_id,
            smart=True,
        )

    @override
    async def update_smart_collection_filter(
        self,
        server_collection_id: str,
        library_id: str,
        media_type: MediaType,
        filter_query: str,
    ) -> None:
        self.smart_filters[server_collection_id] = filter_query

    @override
    async def filter_choices(
        self, library_id: str, media_type: MediaType, field: str
    ) -> list[tuple[str, str]]:
        return self.choices.get(field, [])

    @override
    async def has_collection(self, server_collection_id: str) -> bool:
        return server_collection_id not in self.gone

    @override
    async def item_filter_choices(
        self, server_item_id: str, field: str
    ) -> list[tuple[str, str]]:
        return self.item_choices.get((server_item_id, field), [])

    @override
    async def find_matching(
        self, library_id: str, media_type: MediaType, filter_query: str, size: int
    ) -> tuple[int, list[str]]:
        self.queries.append(filter_query)
        return (3 if "eng" in filter_query else 1), ["m0", "m1"][:size]

    @override
    async def order_collection_hubs(
        self, library_id: str, server_collection_ids: Sequence[str]
    ) -> None:
        self.hub_orders.append(list(server_collection_ids))

    @override
    async def sync_item_labels(
        self,
        library_id: str,
        media_type: MediaType,
        label: str,
        *,
        add: Mapping[str, Sequence[str]],
        remove_ids: list[str],
    ) -> None:
        self.synced_labels.append((label, sorted(add), remove_ids))

    @override
    async def update_collection_details(
        self,
        server_collection_id: str,
        library_id: str,
        details: CollectionDetails,
    ) -> None:
        if server_collection_id in self.rejected_updates:
            raise ValueError("Server refused this update")
        self.options[server_collection_id] = (
            details.title,
            details.mode,
            details.order,
            details.visible_home,
        )
        self.sort_titles[server_collection_id] = details.sort_title
        self.summaries[server_collection_id] = details.summary
        self.empty[server_collection_id] = details.empty

    @override
    async def get_collection_member_ids(self, server_collection_id: str) -> list[str]:
        return self.members[server_collection_id].copy()

    @override
    async def set_collection_members(
        self,
        server_collection_id: str,
        server_item_ids: list[str],
        *,
        order: CollectionOrder,
        append: bool = False,
    ) -> MemberWrite:
        if self.fail:
            raise MediaServerError("Write failed")
        if append:
            wanted = set(server_item_ids)
            server_item_ids = [
                *server_item_ids,
                *(
                    identity
                    for identity in self.members[server_collection_id]
                    if identity not in wanted
                ),
            ]
        before = set(self.members.get(server_collection_id, []))
        self.members[server_collection_id] = server_item_ids
        after = set(server_item_ids)
        return MemberWrite(server_item_ids, len(after - before), len(before - after))

    @override
    async def delete_collection(self, server_collection_id: str) -> None:
        self.deleted.append(server_collection_id)


class JellyfinProvider(Provider):
    server_type: ClassVar[ServerType] = ServerType.JELLYFIN
    collections_span_libraries: ClassVar[bool] = True


class Lists(MDBListClient):
    def __init__(self) -> None:
        self.ids = [12, 11, 900]
        self.failure = False
        self.closed = False

    @override
    async def tmdb_ids(self, identifier: str, media_type: MediaType) -> list[int]:
        if self.failure:
            raise PublicServiceError(502, "Source unavailable")
        return self.ids

    @override
    async def search_lists(self, query: str) -> list[MdblistList]:
        return [MdblistList(id=5, name=f"{query} picks", user_name="gary", items=9)]

    @override
    async def close(self) -> None:
        self.closed = True


class Tmdb(TMDBClient):
    def __init__(self) -> None:
        self.found = True
        self.error: Exception | None = None
        self.chart_requests: list[tuple[TmdbChart, int, str]] = []
        self.keyword_queries: list[str] = []

    @override
    async def search_keywords(self, query: str) -> tuple[str, ...]:
        self.keyword_queries.append(query)
        return ("christmas", "Christmas Eve")

    @override
    async def get_collection(self, collection_id: int) -> TmdbCollection | None:
        if self.error is not None:
            raise self.error
        if not self.found:
            return None
        return TmdbCollection(
            collection_id,
            "Saga",
            None,
            (
                TmdbTitle(12, "Second", 2005, "2005-01-01", None),
                TmdbTitle(11, "First", 1995, "1995-01-01", None),
            ),
            overview="Collection overview",
        )

    @override
    async def get_list_ids(
        self, list_id: int, media_type: MediaType
    ) -> tuple[int, ...]:
        if self.error is not None:
            raise self.error
        return (13, 11) if list_id == 1 else (11, 12)

    @override
    async def get_list_description(self, list_id: int) -> str | None:
        return f"List {list_id}"

    @override
    async def get_chart_ids(
        self, media_type: MediaType, chart: TmdbChart, limit: int, region: str
    ) -> tuple[int, ...]:
        self.chart_requests.append((chart, limit, region))
        return (13, 12, 99)[:limit]

    @override
    async def get_details(
        self, media_type: MediaType, tmdb_id: int
    ) -> TmdbDetails | None:
        return TmdbDetails(
            media_type,
            tmdb_id,
            f"Missing {tmdb_id}",
            2020,
            7000 + tmdb_id,
            None,
            None,
            None,
            (),
        )

    @override
    async def get_person(self, person_id: int) -> TmdbPerson | None:
        if not self.found:
            return None
        return TmdbPerson(
            person_id, "Director Name", "Directing", None, "Person biography"
        )

    @override
    async def get_person_credits(
        self,
        person_id: int,
        media_type: MediaType,
        roles: frozenset[TmdbPersonRole] | set[TmdbPersonRole],
    ) -> tuple[int, ...]:
        if not self.found:
            return ()
        return (11, 13)


class Art(CollectionArtService):
    def __init__(self) -> None:
        self.offered: dict[str, list[ArtCandidate]] = {
            "plex": [ArtCandidate(url="https://plex.test/art.jpg")],
            "tmdb": [ArtCandidate(url="https://example.test/poster.jpg")],
        }
        self.urls: list[str | None] = []
        self.selections: list[ArtType] = []
        self.generated: list[ArtType] = []
        #: Whether each generated poster showed its title alone.
        self.title_only: list[bool] = []
        self.removed: list[tuple[int, ArtType | None, AssetRemoval]] = []
        self.fail = False

    @override
    async def remove(
        self, collection_id: int, art_type: ArtType | None, removal: AssetRemoval
    ) -> StatusResponse:
        self.removed.append((collection_id, art_type, removal))
        return StatusResponse(status=Status.OK)

    @override
    async def found(self, collection_id: int, art_type: ArtType) -> ArtSourcesResponse:
        if self.fail:
            raise PublicServiceError(502, "Artwork source unavailable")
        return ArtSourcesResponse(sources=self.offered)

    @override
    async def apply(
        self,
        collection_id: int,
        art_type: ArtType,
        body: SaveCollectionArtRequest,
    ) -> StatusResponse:
        self.selections.append(art_type)
        self.urls.append(body.url)
        if body.generated is not None:
            self.generated.append(art_type)
            self.title_only.append(body.title_only)
        return StatusResponse(status=Status.OK)

    @override
    async def reupload(self, collection_id: int, art_type: ArtType) -> None:
        self.selections.append(art_type)


class FakeArrClient(ArrClient):
    def __init__(self, tag_id: int, label: str) -> None:
        self._tag = ArrTag(id=tag_id, label=label)
        self._configured = True
        self.closed = False
        self.held = [ArrTitle(id=1, tmdb_id=11, tvdb_id=None, tags=frozenset({77}))]
        self.added: list[tuple[int, ArrRequest]] = []
        self.tag_edits: list[tuple[int, list[int], bool]] = []
        self.tag_labels: list[str] = []

    @override
    async def titles(self) -> list[ArrTitle]:
        return self.held

    @override
    async def add(self, external_id: int, request: ArrRequest) -> None:
        self.added.append((external_id, request))

    @override
    async def tag_id(self, label: str) -> int:
        self.tag_labels.append(label)
        return 77

    @override
    async def edit_tag(
        self, tag_id: int, title_ids: Sequence[int], *, add: bool
    ) -> None:
        self.tag_edits.append((tag_id, list(title_ids), add))

    @override
    async def options(self) -> ArrOptions:
        return ArrOptions(("/movies",), (ArrTag(id=4, label="HD"),))

    @override
    async def list_tags(self) -> list[ArrTag]:
        return [self._tag]

    @override
    async def external_ids_for_tags(self, tag_names: Sequence[str]) -> ArrTagMatches:
        return ArrTagMatches(
            tmdb_ids=(11, 12),
            tvdb_ids=(201,),
            imdb_ids=("tt9999999",),
        )

    @override
    async def close(self) -> None:
        self.closed = True


@dataclass(slots=True)
class Manager:
    service: CollectionsService
    provider: Provider
    lists: Lists
    tmdb: Tmdb
    publisher: FakePublisher
    art: Art
    downloads: FakeDownloads
    radarr: FakeArrClient
    database: Database
    ids: list[int] = field(default_factory=list[int])


def sources(*selected: CollectionSource) -> FilterGroup:
    """Criteria matching what any of the sources holds."""
    return FilterGroup(
        mode="any", conditions=[SourceCondition(source=source) for source in selected]
    )


def where(
    field: FilterField, operator: FilterOperator, value: str | float | bool
) -> FilterGroup:
    return FilterGroup(
        conditions=[FieldCondition(field=field, operator=operator, value=value)]
    )


#: The collection policy these tests are written against.
_POLICY = {
    "collection_minimum_items": 1,
    "collection_delete_below_minimum": False,
    "collection_delete_when_inactive": False,
    "collection_sync_enabled": True,
}


def settings_row(**values: object) -> AppSettings:
    """The settings row, with groups optional unless a test asks for them."""
    return AppSettings.model_validate({"id": 1, **_POLICY, **values})


#: Criteria no title matches, for a collection that starts empty.
NOTHING_MATCHES = library_rule(
    criteria=where(FilterField.TITLE, FilterOperator.IS, "No title has this name"),
    sync_mode=SyncMode.APPEND,
)


def chosen(manager: Manager, ids: list[int] | None = None) -> CollectionRuleWrite:
    """Criteria naming exactly these fixture movies, by their TMDB IDs, in Append."""
    picked = manager.ids if ids is None else ids
    return library_rule(
        criteria=sources(
            TmdbItemSource(tmdb_ids=[11 + manager.ids.index(item) for item in picked])
        ),
        sync_mode=SyncMode.APPEND,
    )


@pytest.fixture
def app_config(app_config: Settings) -> Settings:
    """TMDB and MDBList sources need their keys."""
    return app_config.model_copy(
        update={
            "TMDB_READ_ACCESS_TOKEN": SecretStr("tmdb"),
            "MDBLIST_API_KEY": SecretStr("mdblist"),
        }
    )


@pytest.fixture
async def manager(database: Database, app_config: Settings) -> Manager:
    provider = Provider(app_config)
    lists = Lists()
    tmdb = Tmdb()
    publisher = FakePublisher()
    art = Art()
    downloads = FakeDownloads()
    radarr = FakeArrClient(1, "4k")
    async with database.write_session() as session:
        # A sync records the server's libraries before anything else.
        await LibraryRepository(session).record(
            TEST_SERVER_ID, await provider.get_sections(), utc_now()
        )
        # Groups are optional here; the tests about requiring one turn it on.
        await session.merge(settings_row())
        items = [
            served_item(
                media_type=MediaType.MOVIE,
                title=title,
                year=year,
                release_date=f"{year}-06-01",
                tmdb_id=11 + index,
                server_item_id=f"m{index}",
                library_id="1:movies",
                studio="Studio",
                tmdb_collection_id=10,
            )
            for index, (title, year) in enumerate(
                (("First", 1995), ("Second", 2005), ("Manual", 2006))
            )
        ]
        show = served_item(
            media_type=MediaType.SHOW,
            title="Anime Series",
            year=2020,
            tmdb_id=11,
            server_item_id="s1",
            library_id="1:shows",
            studio="Studio",
        )
        session.add_all([*items, show])
        for item in items:
            await assign(session, item, genre=["Action"])
        await assign(session, show, genre=["Animation"])
        await session.flush()
        ids = [item.id or 0 for item in items]
    registry = NoopProviderRegistry(provider)
    service = CollectionsService(
        needs=AssetNeeds(database=database, provider_registry=registry),
        database=database,
        provider_registry=registry,
        publisher=publisher,
        downloads=downloads,
        proxy_clients=unused(ProxyClientManager),
        app_config=app_config,
        tmdb=tmdb,
        mdblist=lists,
        remover=make_remover(provider, app_config=app_config, database=database),
        art=art,
        radarr=radarr,
        sonarr=FakeArrClient(2, "anime"),
    )
    return Manager(
        service, provider, lists, tmdb, publisher, art, downloads, radarr, database, ids
    )


async def members(manager: Manager, detail: CollectionDetail) -> list[MediaItem]:
    """The items a collection holds, in its display order."""
    async with manager.database.read_session() as session:
        return [
            item
            for identity in detail.member_ids
            if (item := await session.get(MediaItem, identity)) is not None
        ]


async def created(
    service: CollectionsService, body: CollectionCreate
) -> CollectionDetail:
    """Save a collection, then sync it, as a sync from Operations sends it."""
    detail = await service.editor.create(body)
    return await synced(service, detail.id)


async def group_sync(manager: Manager, name: str) -> tuple[RecordedReport, list[int]]:
    """Sync a group as a run does; return its log and the group's collections."""
    report = RecordedReport()
    await manager.service.groups.sync(name, report)
    return report, [
        row.id
        for row in sorted(await manager.service.reader.listed(), key=lambda r: r.id)
        if row.collection_group == name
    ]


def errors(report: RecordedReport) -> list[str]:
    """The lines of a run's log that report a failure."""
    return [line for line in report.lines if " Error " in f" {line} "]


async def synced(service: CollectionsService, collection_id: int) -> CollectionDetail:
    """Sync a saved collection and read it back."""
    await service.rules.sync(collection_id)
    return await service.reader.get(collection_id)


async def create_unmanaged(manager: Manager, database: Database) -> int:
    """A collection as a server sync imports one: listed, with no rule."""
    identity = await create(manager)
    async with database.write_session() as session:
        rule = await CollectionRepository(session).rule(identity)
        await session.delete(rule)
    return identity


async def create(manager: Manager, ids: list[int] | None = None) -> int:
    result = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Saga",
            rule=chosen(manager, ids),
        ),
    )
    return result.id


async def test_a_collection_deleted_on_the_server_is_made_again_by_its_own_sync(
    manager: Manager,
) -> None:
    identity = await create(manager)
    first = (await manager.service.reader.get(identity)).copies[0].server_item_id
    manager.provider.gone.add(first)

    detail = await synced(manager.service, identity)

    # The sync makes a new copy rather than writing to the one that is gone.
    assert manager.provider.created == ["Saga", "Saga"]
    assert [copy.server_item_id for copy in detail.copies] != [first]
    assert manager.provider.members[detail.copies[0].server_item_id]


@pytest.mark.parametrize("status", [404, 403, 500])
async def test_delete_handles_only_an_already_absent_server_collection(
    manager: Manager, database: Database, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    identity = await create(manager)
    request = AsyncMock(
        side_effect=MediaServerError("Unavailable", upstream_status_code=status)
    )
    monkeypatch.setattr(manager.provider, "delete_collection", request)
    if status == 404:
        await manager.service.editor.delete(identity)
    else:
        with pytest.raises(MediaServerError):
            await manager.service.editor.delete(identity)
    async with database.read_session() as session:
        assert (await CollectionRepository(session).get(identity) is None) is (
            status == 404
        )
        assert (
            len(
                await CollectionItemRepository(session).library_items(
                    MediaType.MOVIE, "1:movies"
                )
            )
            == 3
        )


async def test_delete_from_server_preserves_configuration(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    await manager.service.editor.delete(identity, target="server")
    assert manager.provider.deleted == ["1"]
    async with database.read_session() as session:
        repo = CollectionRepository(session)
        row = await repo.get(identity)
        assert row is not None
        assert copy_id(row) is None
        assert row.child_count == 0
        assert await repo.rule(identity) is not None
        assert (
            len(
                await CollectionItemRepository(session).library_items(
                    MediaType.MOVIE, "1:movies"
                )
            )
            == 3
        )
    await manager.service.rules.sync(identity)
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(identity)
        assert row is not None
        assert copy_id(row) is not None


@pytest.mark.parametrize("target", ["move", "orphan", "both"])
async def test_group_deletion_targets(
    manager: Manager, database: Database, target: str
) -> None:
    identity = await create(manager)
    await manager.service.editor.update(
        identity,
        CollectionOptions(title="Saga", collection_group="Weekend"),
    )
    await manager.service.groups.save_policy(
        "Weekend", CollectionGroupPolicy(minimum_items=1)
    )
    result = await manager.service.groups.delete(
        "Weekend",
        CollectionGroupDelete.model_validate(
            {"collections": target, "group": "Evenings" if target == "move" else None}
        ),
    )
    assert not result.errors
    assert manager.provider.deleted == (["1"] if target == "both" else [])
    # The collection was made in Films, which stays, empty.
    assert await manager.service.groups.names() == (
        ["Evenings", "Films"] if target == "move" else ["Films"]
    )
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(identity)
        rule = await CollectionRepository(session).rule(identity)
    if target == "both":
        assert row is None
    elif target == "orphan":
        assert row is not None
        assert row.group_name is None
        assert rule is None
    else:
        assert row is not None
        assert row.group_name == "Evenings"


async def test_a_group_holding_collections_is_deleted_only_with_a_choice_for_them(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    await manager.service.editor.update(
        identity,
        CollectionOptions(title="Saga", collection_group="Weekend"),
    )
    with pytest.raises(PublicServiceError, match="Choose what happens"):
        await manager.service.groups.delete("Weekend", CollectionGroupDelete())
    with pytest.raises(PublicServiceError, match="another group"):
        await manager.service.groups.delete(
            "Weekend",
            CollectionGroupDelete(collections="move", group="weekend"),
        )
    with pytest.raises(ValidationError, match="Name the group"):
        CollectionGroupDelete(collections="move")
    # A group without collections goes without a choice, as any group can.
    await manager.service.groups.delete("Films", CollectionGroupDelete())
    assert await manager.service.groups.names() == ["Weekend"]
    # No collection Overture manages is left without a group.
    with pytest.raises(PublicServiceError, match="Choose a group"):
        await manager.service.editor.update(identity, CollectionOptions(title="Saga"))
    assert (await manager.service.reader.get(identity)).collection_group == "Weekend"


async def test_group_delete_failure_preserves_group_for_retry(
    manager: Manager, monkeypatch: pytest.MonkeyPatch
) -> None:
    identity = await create(manager)
    await manager.service.editor.update(
        identity,
        CollectionOptions(title="Saga", collection_group="Weekend"),
    )
    monkeypatch.setattr(
        manager.provider,
        "delete_collection",
        AsyncMock(side_effect=MediaServerError("Offline")),
    )
    result = await manager.service.groups.delete(
        "Weekend", CollectionGroupDelete(collections="both")
    )
    assert identity in result.errors
    assert await manager.service.groups.names() == ["Films", "Weekend"]


async def test_group_rename_preserves_defaults_and_rejects_collisions(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.editor.update(
        identity,
        CollectionOptions(title="Saga", collection_group="Weekend"),
    )
    await manager.service.groups.save_policy(
        "Weekend",
        CollectionGroupPolicy(sort_title_format="01_{title}"),
    )
    await manager.service.groups.rename("Weekend", "Evenings")
    assert (await manager.service.reader.get(identity)).collection_group == "Evenings"
    assert (
        await manager.service.groups.policy("Evenings")
    ).sort_title_format == "01_{title}"
    await manager.service.groups.save_policy("Other", CollectionGroupPolicy())
    with pytest.raises(PublicServiceError, match="already exists"):
        await manager.service.groups.rename("Evenings", "Other")
    with pytest.raises(PublicServiceError, match="not found"):
        await manager.service.groups.rename("Nothing", "Shows")


async def test_group_art_orders_read_back_as_their_enums(manager: Manager) -> None:
    await manager.service.groups.save_policy(
        "Weekend",
        CollectionGroupPolicy(
            auto_art=[AutoArtSource.GENERATE],
            overturedb_posters=[CollectionPosterStyle.INDIVIDUAL],
        ),
    )
    # Warnings are errors, so a stored string read back as the enum's value
    # fails here when the policy is serialised.
    saved = await manager.service.groups.policy("Weekend")
    assert saved.model_dump(mode="json")["auto_art"] == ["generate"]
    assert saved.auto_art == [AutoArtSource.GENERATE]


async def test_schedules_keep_running_a_renamed_group(
    manager: Manager, database: Database
) -> None:
    await manager.service.groups.save_policy("Weekend", CollectionGroupPolicy())
    async with database.write_session() as session:
        for kind, groups in (
            (ScheduleKind.SYNC, ["Weekend", "Other"]),
            (ScheduleKind.ASSETS, ["Weekend"]),
        ):
            session.add(
                SavedSchedule(
                    kind=kind,
                    name="Nightly",
                    cron_expression="0 3 * * *",
                    payload={"collection_groups": groups},
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            )

    await manager.service.groups.rename("Weekend", "Evenings")

    async with database.read_session() as session:
        repository = SavedScheduleRepository(session)
        assert [
            record.payload["collection_groups"]
            for kind in (ScheduleKind.SYNC, ScheduleKind.ASSETS)
            for record in await repository.of_kind(kind)
        ] == [["Evenings", "Other"], ["Evenings"]]


async def test_a_new_set_never_replaces_another_and_names_taken_titles(
    manager: Manager,
) -> None:
    decades = CollectionGenerator(
        dimension=SetDimension.DECADE, library_ids=["1:movies"], title_format="{value}s"
    )
    taken = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films", title="1990s", rule=chosen(manager, None)
        ),
    )

    preview = await manager.service.sets.preview(
        CollectionSetPreview(generator=decades, group="Decades")
    )
    assert [(entry.title, entry.title_taken_by) for entry in preview] == [
        ("1990s", taken.id),
        ("2000s", None),
    ]

    await manager.service.groups.save_policy(
        "Decades", CollectionGroupPolicy(generator=decades), new_set=True
    )
    assert [
        (found.name, found.set and (found.set.dimension, found.set.library_ids))
        for found in await manager.service.groups.list()
    ] == [
        ("Decades", (SetDimension.DECADE, ["1:movies"])),
        ("Films", None),
    ]
    with pytest.raises(PublicServiceError, match="already splits by Decades"):
        await manager.service.groups.save_policy(
            "Decades", CollectionGroupPolicy(generator=decades), new_set=True
        )
    await manager.service.groups.save_policy(
        "Decades",
        CollectionGroupPolicy(
            generator=decades.model_copy(update={"title_format": "{value}"})
        ),
    )


async def test_set_collections_leave_only_with_their_set(manager: Manager) -> None:
    decades = CollectionGenerator(
        dimension=SetDimension.DECADE, library_ids=["1:movies"], title_format="{value}s"
    )
    await manager.service.groups.save_policy(
        "Decades", CollectionGroupPolicy(minimum_items=1, generator=decades)
    )
    first, _ = (await group_sync(manager, "Decades"))[1]
    for remove in (
        manager.service.editor.delete(first),
        manager.service.adoption.orphan(first),
    ):
        with pytest.raises(PublicServiceError, match="set made it"):
            await remove

    result = await manager.service.groups.delete(
        "Decades", CollectionGroupDelete(collections="orphan")
    )

    assert not result.errors
    detail = await manager.service.reader.get(first)
    assert (detail.managed, detail.collection_group, detail.generated_value) == (
        False,
        None,
        None,
    )


async def test_sets_create_update_and_withhold_their_collections(
    manager: Manager,
) -> None:
    decades = CollectionGenerator(
        dimension=SetDimension.DECADE, library_ids=["1:movies"], title_format="{value}s"
    )
    preview = await manager.service.sets.preview(
        CollectionSetPreview(generator=decades, group="Decades")
    )
    assert [
        (entry.title, entry.member_count, entry.collection_id) for entry in preview
    ] == [
        ("1990s", 1, None),
        ("2000s", 2, None),
    ]
    await manager.service.groups.save_policy(
        "Decades",
        CollectionGroupPolicy(
            minimum_items=1,
            delete_below_minimum=True,
            sort_title_format="01_{title}",
            generator=decades,
        ),
    )
    report, (first, second) = await group_sync(manager, "Decades")
    assert not errors(report)
    detail = await manager.service.reader.get(first)
    assert (detail.title, detail.sort_title, detail.generated_value) == (
        "1990s",
        "01_1990s",
        "1990",
    )
    assert detail.rule is not None
    assert detail.rule.libraries[0].criteria == where(
        FilterField.DECADE, FilterOperator.IS, 1990
    )
    assert [member.title for member in await members(manager, detail)] == ["First"]

    repeated, ids = await group_sync(manager, "Decades")
    assert ids == [first, second]
    assert repeated[JobOutcome.UNCHANGED] == 2

    await manager.service.groups.save_policy(
        "Decades",
        CollectionGroupPolicy(
            minimum_items=1,
            delete_below_minimum=True,
            generator=decades.model_copy(
                update={
                    "title_format": "The {value}s",
                    "exclude": ["the 1990s"],
                }
            ),
        ),
    )
    edited, _ = await group_sync(manager, "Decades")
    assert [line for line in edited.lines if "Removed" in line] == [
        (
            "[Plex] Removed 1990s - deleted from Movies: "
            "its group's set no longer selects it"
        )
    ]
    assert (await manager.service.reader.get(second)).title == "The 2000s"
    # Overture keeps the deselected collection, and its own sync leaves it
    # off the server until the set selects its value again.
    assert (await manager.service.reader.get(first)).withheld
    assert (await manager.service.rules.sync(first)).withheld
    assert (await manager.service.reader.get(first)).withheld
    with pytest.raises(PublicServiceError, match="edit the set"):
        await manager.service.editor.save_rule(
            second,
            library_rule(criteria=where(FilterField.YEAR, FilterOperator.IS, 1)),
        )
    with pytest.raises(PublicServiceError, match="edit the set"):
        await manager.service.editor.update(
            second, CollectionOptions(collection_group="Films", title="Renamed")
        )
    kept = await manager.service.sets.preview(
        CollectionSetPreview(generator=decades, group="Decades")
    )
    assert [entry.collection_id for entry in kept] == [first, second]
    genres = await manager.service.sets.preview(
        CollectionSetPreview(
            generator=CollectionGenerator(
                dimension=SetDimension.GENRE, library_ids=["1:shows"]
            ),
            minimum_items=2,
        )
    )
    assert [(entry.title, entry.below_minimum) for entry in genres] == [
        ("Animation", True)
    ]


async def test_sets_skip_titles_other_collections_hold(manager: Manager) -> None:
    await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Action",
            rule=chosen(manager),
        ),
    )
    await manager.service.groups.save_policy(
        "Genres",
        CollectionGroupPolicy(
            generator=CollectionGenerator(
                dimension=SetDimension.GENRE, library_ids=["1:movies"]
            )
        ),
    )
    result, ids = await group_sync(manager, "Genres")
    assert ids == []
    assert errors(result) == [
        (
            "Error Action - its group's set could not save it: "
            "One of its libraries already has a collection titled Action"
        )
    ]


async def test_inherited_placeholders_resolve_group_before_global(
    manager: Manager,
) -> None:
    await manager.service.groups.save_policy(
        "Weekend",
        CollectionGroupPolicy(sort_title_format="", minimum_items=4),
    )
    defaults = await manager.service.reader.inherited_policy("Weekend")
    assert defaults.sort_title_format == ""
    assert defaults.minimum_items == 4
    # A group's automatic art inherits the global choice, which its form names.
    global_defaults = await manager.service.reader.inherited_policy()
    assert (
        global_defaults.auto_art,
        global_defaults.generated_style,
        global_defaults.backgrounds,
    ) == ([], ArtStyle.DARK, True)


def make_jellyfin_service(
    manager: Manager,
    app_config: Settings,
    database: Database,
    provider: JellyfinProvider | None = None,
) -> CollectionsService:
    provider = provider or JellyfinProvider(app_config)
    registry = NoopProviderRegistry(provider)
    return CollectionsService(
        needs=AssetNeeds(database=database, provider_registry=registry),
        database=database,
        provider_registry=registry,
        publisher=manager.publisher,
        downloads=manager.downloads,
        proxy_clients=unused(ProxyClientManager),
        app_config=app_config,
        tmdb=manager.tmdb,
        mdblist=manager.lists,
        remover=make_remover(provider, app_config=app_config, database=database),
        art=manager.art,
        radarr=FakeArrClient(1, "4k"),
        sonarr=FakeArrClient(2, "anime"),
    )


async def test_create_edit_order_and_delete_preserve_media(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    detail = await manager.service.editor.update(
        identity,
        CollectionOptions(
            collection_group="Films",
            title="Renamed",
            sort_title="!Saga",
            summary="Summary",
            collection_mode=CollectionMode.HIDE_ITEMS,
            visible_home=True,
        ),
    )
    assert (detail.title, detail.sort_title, detail.summary) == (
        "Renamed",
        "!Saga",
        "Summary",
    )
    detail = await manager.service.editor.set_members(
        identity,
        CollectionMembersUpdate(
            member_ids=list(reversed(manager.ids)), order_type=CollectionOrder.CUSTOM
        ),
    )
    assert detail.member_ids == list(reversed(manager.ids))
    assert (detail.unsynced, manager.provider.members["1"]) == (
        True,
        ["m0", "m1", "m2"],
    )
    await manager.service.editor.save_rule(
        identity,
        library_rule(criteria=sources(TmdbCollectionSource(collection_id=10))),
    )
    async with database.write_session() as session:
        row = await session.get(MediaCollection, identity)
        assert row is not None
        select_art(
            row,
            ServerAsset.POSTER,
            PublicArtUrl("https://example.test/poster.jpg"),
            poster_style=CollectionPosterStyle.INDIVIDUAL,
        )
        session.add(row)
    await manager.service.editor.delete(identity)
    assert manager.provider.deleted == ["1"]
    async with database.read_session() as session:
        assert await session.get(MediaCollection, identity) is None
        assert await CollectionRepository(session).rule(identity) is None
        assert (
            len(
                await CollectionItemRepository(session).library_items(
                    MediaType.MOVIE, "1:movies"
                )
            )
            == 3
        )
    assert manager.publisher.broadcasts[-1][0] == "collections.changed"


async def test_edits_say_whether_the_titles_a_collection_links_changed(
    manager: Manager,
) -> None:
    identity = await create(manager)

    def titles() -> bool:
        event, payload = manager.publisher.broadcasts[-1]
        assert event == "collection.updated"
        return payload["titles"]

    await manager.service.editor.update(
        identity, CollectionOptions(collection_group="Films", title="Renamed")
    )
    assert not titles()
    await manager.service.editor.set_members(
        identity,
        CollectionMembersUpdate(
            member_ids=list(reversed(manager.ids)), order_type=CollectionOrder.CUSTOM
        ),
    )
    assert titles()
    franchise = library_rule(criteria=sources(TmdbCollectionSource(collection_id=10)))
    await manager.service.editor.save_rule(identity, franchise)
    assert titles()
    await manager.service.editor.save_rule(identity, franchise)
    assert not titles()


@pytest.mark.parametrize("ids", [[999], [1, 1]])
async def test_invalid_members_never_reach_the_server(
    manager: Manager, ids: list[int]
) -> None:
    identity = await create(manager)
    before = list(manager.provider.members["1"])
    with pytest.raises(PublicServiceError, match="distinct active"):
        await manager.service.editor.set_members(
            identity,
            CollectionMembersUpdate(member_ids=ids, order_type=CollectionOrder.CUSTOM),
        )
    assert manager.provider.members["1"] == before


async def test_create_validates_library_and_duplicate_titles(manager: Manager) -> None:
    with pytest.raises(PublicServiceError, match="servers' libraries"):
        await created(
            manager.service,
            CollectionCreate(
                collection_group="Films",
                title="Saga",
                rule=library_rule(
                    criteria=sources(TmdbItemSource(tmdb_ids=[11])),
                    library_id="1:other",
                ),
            ),
        )
    await create(manager)
    with pytest.raises(PublicServiceError, match="already has a collection titled"):
        await create(manager)
    assert manager.provider.created == ["Saga"]


async def test_a_failed_sync_keeps_the_saved_members(manager: Manager) -> None:
    identity = await create(manager)
    await manager.service.editor.set_members(
        identity,
        CollectionMembersUpdate(
            member_ids=[manager.ids[0]], order_type=CollectionOrder.RELEASE_ASC
        ),
    )
    manager.provider.fail = True
    outcome = await manager.service.rules.sync(identity)
    assert outcome.errors == "Write failed"
    detail = await manager.service.reader.get(identity)
    assert (detail.member_ids, detail.unsynced) == ([manager.ids[0]], True)
    assert detail.rule is not None
    assert detail.rule.last_error == "Write failed"


@pytest.mark.parametrize(
    ("global_mode", "override", "expected"),
    [
        (SyncMode.SYNC, None, 2),
        (SyncMode.APPEND, None, 3),
        (SyncMode.APPEND, SyncMode.SYNC, 2),
        (SyncMode.SYNC, SyncMode.APPEND, 3),
    ],
)
async def test_rule_sync_uses_global_defaults_and_nullable_overrides(
    manager: Manager,
    database: Database,
    global_mode: SyncMode,
    override: SyncMode | None,
    expected: int,
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        await session.merge(settings_row(collection_sync_mode=global_mode))
    await manager.service.editor.save_rule(
        identity,
        library_rule(
            criteria=sources(MdblistSource(identifiers=["person/list"])),
            order_type=CollectionOrder.CUSTOM,
            sync_mode=override,
        ),
    )
    result = await manager.service.rules.sync(identity)
    detail = await manager.service.reader.get(identity)
    assert len(detail.member_ids) == expected
    assert sum(change.removed for change in result.changes) == 3 - expected
    assert detail.rule is not None
    assert detail.rule.last_synced_at is not None
    assert manager.provider.members["1"] == (
        ["m1", "m0"] if expected == 2 else ["m1", "m0", "m2"]
    )


@pytest.mark.parametrize("delete", [False, True])
async def test_below_minimum_keeps_or_withholds_collection(
    manager: Manager, database: Database, *, delete: bool
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        await session.merge(
            settings_row(
                collection_minimum_items=3, collection_delete_below_minimum=delete
            )
        )
    await manager.service.editor.save_rule(
        identity,
        library_rule(criteria=sources(MdblistSource(identifiers=["42"]))),
    )
    result = await manager.service.rules.sync(identity)
    assert result.withheld is delete
    assert result.skipped is not delete
    # Overture keeps the collection either way; only its server copy goes.
    detail = await manager.service.reader.get(identity)
    assert detail.withheld is delete
    if not delete:
        assert len((await manager.service.reader.get(identity)).member_ids) == 3


async def test_failed_source_preserves_members_and_records_safe_error(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.editor.save_rule(
        identity,
        library_rule(criteria=sources(MdblistSource(identifiers=["42"]))),
    )
    manager.lists.failure = True
    with pytest.raises(PublicServiceError, match="Source unavailable"):
        await manager.service.rules.sync(identity)
    detail = await manager.service.reader.get(identity)
    assert len(detail.member_ids) == 3
    assert detail.rule
    assert detail.rule.last_error == "Source unavailable"


async def test_tmdb_and_intersected_filters_resolve_only_library_members(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.editor.save_rule(
        identity,
        library_rule(criteria=sources(TmdbCollectionSource(collection_id=10))),
    )
    await manager.service.rules.sync(identity)
    assert manager.provider.members["1"] == ["m0", "m1"]
    manager.tmdb.found = False
    with pytest.raises(PublicServiceError, match="membership was kept"):
        await manager.service.rules.sync(identity)
    await manager.service.editor.save_rule(
        identity,
        library_rule(
            criteria=FilterGroup(
                conditions=[
                    FieldCondition(
                        field=FilterField.DECADE, operator=FilterOperator.IS, value=2000
                    ),
                    FieldCondition(
                        field=FilterField.STUDIO,
                        operator=FilterOperator.IS,
                        value="studio",
                    ),
                    FieldCondition(
                        field=FilterField.GENRE,
                        operator=FilterOperator.IS,
                        value="action",
                    ),
                ],
            )
        ),
    )
    await manager.service.rules.sync(identity)
    assert manager.provider.members["1"] == ["m1", "m2"]


async def test_closing_the_service_closes_its_source_clients(
    manager: Manager,
) -> None:
    await manager.service.close()
    assert manager.lists.closed


async def test_rule_sync_uses_shared_automatic_art_and_theme_pipelines(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        await session.merge(
            settings_row(
                collection_auto_art=[AutoArtSource.OVERTUREDB, AutoArtSource.TMDB],
                collection_auto_match_theme=True,
            )
        )
        session.add(
            CatalogCollection(tmdb_id=10, title="Saga", youtube_id_overturedb="a" * 11)
        )
    async with database.write_session() as session:
        await enable_catalog(session)
    await manager.service.editor.save_rule(
        identity,
        library_rule(criteria=sources(TmdbCollectionSource(collection_id=10))),
    )
    await manager.service.rules.sync(identity)
    assert manager.art.selections == [ArtType.POSTER, ArtType.BACKGROUND]
    assert manager.downloads.targets[0].collection_id == identity


async def test_auto_asset_failure_keeps_synced_members_and_records_the_failure(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        await session.merge(
            settings_row(
                collection_auto_art=[AutoArtSource.OVERTUREDB, AutoArtSource.TMDB]
            )
        )
    await manager.service.editor.save_rule(
        identity,
        library_rule(criteria=sources(TmdbCollectionSource(collection_id=10))),
    )
    manager.art.fail = True
    with pytest.raises(
        PublicServiceError, match="Members synced; Automatic assets failed"
    ):
        await manager.service.rules.sync(identity)
    detail = await manager.service.reader.get(identity)
    assert len(detail.member_ids) == 2
    assert detail.rule is not None
    assert detail.rule.last_error is not None
    assert "Artwork source unavailable" in detail.rule.last_error


async def test_append_keeps_new_server_members_and_counts_them_for_minimum(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager, manager.ids[:2])
    manager.provider.members["1"].extend(["m2", "unimported"])
    async with database.write_session() as session:
        await session.merge(
            settings_row(
                collection_minimum_items=4, collection_delete_below_minimum=True
            )
        )
    await manager.service.editor.save_rule(
        identity,
        library_rule(
            criteria=sources(MdblistSource(identifiers=["42"])),
            order_type=CollectionOrder.CUSTOM,
            sync_mode=SyncMode.APPEND,
        ),
    )
    result = await manager.service.rules.sync(identity)
    assert not result.skipped
    assert not result.withheld
    assert manager.provider.members["1"] == ["m1", "m0", "m2", "unimported"]
    detail = await manager.service.reader.get(identity)
    assert detail.child_count == 4
    assert len(detail.member_ids) == 3


async def test_append_does_not_restore_a_manual_member_removed_on_the_server(
    manager: Manager,
) -> None:
    identity = await create(manager)
    manager.provider.members["1"] = ["m0", "m1"]
    await manager.service.editor.save_rule(
        identity,
        library_rule(
            criteria=sources(MdblistSource(identifiers=["42"])),
            order_type=CollectionOrder.CUSTOM,
            sync_mode=SyncMode.APPEND,
        ),
    )
    await manager.service.rules.sync(identity)
    assert manager.provider.members["1"] == ["m1", "m0"]
    assert (await manager.service.reader.get(identity)).child_count == 2


async def test_custom_group_round_trips_and_joins_group_choices(
    manager: Manager,
) -> None:
    identity = await create(manager)
    detail = await manager.service.editor.update(
        identity,
        CollectionOptions(title="Saga", collection_group="  Weekend  "),
    )
    assert detail.collection_group == "Weekend"
    groups = await manager.service.groups.names()
    assert groups == ["Films", "Weekend"]
    listed = await manager.service.reader.listed()
    assert listed[0].collection_group == "Weekend"
    # A blank group is no group, which a collection Overture manages must name.
    with pytest.raises(PublicServiceError, match="Choose a group"):
        await manager.service.editor.update(
            identity, CollectionOptions(title="Saga", collection_group=" ")
        )


async def test_explicit_identity_survives_membership_changes(manager: Manager) -> None:
    identity = await create(manager)
    detail = await manager.service.reader.get(identity)
    assert detail.tmdb_collection_id is None
    await manager.service.editor.update(
        identity,
        CollectionOptions(
            collection_group="Films", title="Saga", tmdb_collection_id=99
        ),
    )
    detail = await manager.service.editor.set_members(
        identity,
        CollectionMembersUpdate(
            member_ids=manager.ids, order_type=CollectionOrder.RELEASE_ASC
        ),
    )
    assert detail.tmdb_collection_id == 99
    detail = await manager.service.editor.update(
        identity, CollectionOptions(collection_group="Films", title="Renamed")
    )
    assert detail.tmdb_collection_id == 99
    detail = await manager.service.editor.update(
        identity,
        CollectionOptions(
            collection_group="Films", title="Renamed", tmdb_collection_id=None
        ),
    )
    assert detail.tmdb_collection_id is None


async def test_creation_resolves_a_dynamic_rule_and_saves_it_with_identity(
    manager: Manager,
) -> None:
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Dynamic",
            rule=library_rule(criteria=sources(TmdbCollectionSource(collection_id=10))),
        ),
    )
    assert detail.tmdb_collection_id == 10
    assert [member.tmdb_id for member in await members(manager, detail)] == [11, 12]
    assert detail.rule is not None
    assert detail.rule.libraries[0].criteria == sources(
        TmdbCollectionSource(collection_id=10)
    )


async def test_group_defaults_and_explicit_rule_choices_resolve_in_order(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        await session.merge(
            settings_row(
                collection_minimum_items=3,
                collection_delete_below_minimum=True,
                collection_auto_art=[AutoArtSource.OVERTUREDB, AutoArtSource.TMDB],
            )
        )
    policy = CollectionGroupPolicy(
        sync_mode=SyncMode.SYNC,
        minimum_items=2,
        delete_below_minimum=False,
        auto_art=[],
        collection_mode=CollectionMode.HIDE,
        sort_title_format="+{group} - {title}",
    )
    await manager.service.groups.save_policy("Weekend", policy)
    assert await manager.service.groups.policy("Weekend") == policy
    await manager.service.editor.update(
        identity,
        CollectionOptions(title="Saga", collection_group="Weekend"),
    )
    await synced(manager.service, identity)
    assert manager.provider.options["1"][1] is CollectionMode.HIDE
    assert manager.provider.sort_titles["1"] == "+Weekend - Saga"
    await manager.service.editor.save_rule(
        identity,
        library_rule(criteria=sources(MdblistSource(identifiers=["42"]))),
    )
    await manager.service.rules.sync(identity)
    detail = await manager.service.reader.get(identity)
    assert len(detail.member_ids) == 2
    assert not detail.below_minimum
    assert manager.art.selections == []
    await manager.service.editor.save_rule(
        identity,
        library_rule(
            criteria=sources(MdblistSource(identifiers=["42"])),
            minimum_items=3,
            delete_below_minimum=False,
        ),
    )
    result = await manager.service.rules.sync(identity)
    assert result.skipped
    assert not result.withheld
    listed = await manager.service.reader.listed()
    assert listed[0].below_minimum
    await manager.service.editor.save_rule(
        identity,
        library_rule(
            criteria=sources(MdblistSource(identifiers=["42"])),
            minimum_items=1,
            sync_mode=SyncMode.APPEND,
        ),
    )
    assert (
        await manager.service.reader.get(identity)
    ).effective_sync_mode is SyncMode.APPEND


async def test_bulk_operations_commit_successes_and_report_invalid_targets(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    result = await manager.service.bulk.run(
        BulkCollectionOperation(
            collection_ids=[999, identity],
            operation="set_group",
            collection_group=" Weekend ",
        )
    )
    assert result.collection_ids == [identity]
    assert set(result.errors) == {999}
    detail = await manager.service.reader.get(identity)
    assert detail.collection_group == "Weekend"
    result = await manager.service.bulk.run(
        BulkCollectionOperation(
            collection_ids=[identity],
            operation="apply_sort_title_format",
            sort_title_format="+{group}: {title}",
        )
    )
    assert result.collection_ids == [identity]
    assert (await manager.service.reader.get(identity)).unsynced
    await synced(manager.service, identity)
    assert manager.provider.sort_titles["1"] == "+Weekend: Saga"
    result = await manager.service.bulk.run(
        BulkCollectionOperation(
            collection_ids=[identity],
            operation="set_monitored",
            monitored=False,
        )
    )
    assert result.collection_ids == [identity]
    assert not (await manager.service.reader.get(identity)).monitored
    result = await manager.service.bulk.run(
        BulkCollectionOperation(collection_ids=[identity], operation="delete")
    )
    assert result.collection_ids == [identity]
    assert manager.provider.deleted == ["1"]
    async with database.read_session() as session:
        assert await session.get(MediaItem, manager.ids[0]) is not None


@pytest.mark.parametrize(
    "template",
    ["{title.__class__}", "{0}", "{index}", "{title!r}", "{title:>1000}", "{"],
)
async def test_sort_title_templates_reject_attribute_access_and_unbounded_formats(
    template: str,
) -> None:
    with pytest.raises(ValueError, match="sort_title_format"):
        CollectionGroupPolicy(sort_title_format=template)


async def test_composable_builders_and_person_biography_summary(
    manager: Manager,
) -> None:
    await manager.service.groups.save_policy(
        "Directors",
        CollectionGroupPolicy(summary_format="Famous director. {source_summary}"),
    )
    detail = await created(
        manager.service,
        CollectionCreate(
            title="Director Spotlight",
            collection_group="Directors",
            order_type=CollectionOrder.CUSTOM,
            rule=library_rule(
                criteria=sources(
                    TmdbPersonSource(
                        person_id=500,
                        roles=[TmdbPersonRole.DIRECTOR],
                    ),
                    TmdbItemSource(tmdb_ids=[12]),
                )
            ),
        ),
    )
    assert [m.tmdb_id for m in await members(manager, detail)] == [11, 13, 12]
    assert detail.summary == "Famous director. Person biography"
    assert manager.provider.summaries["1"] == "Famous director. Person biography"


async def test_smart_collections_label_sources_and_filter_by_plex_keys(
    manager: Manager, database: Database
) -> None:
    requested = SourceCondition(source=MdblistSource(identifiers=["user/requests"]))
    label = source_label(requested)
    manager.provider.choices = {"label": [("5", label)]}
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Requests",
            collection_filtering=CollectionFiltering.USER,
            rule=library_rule(
                smart=True,
                order_type=CollectionOrder.ADDED_DESC,
                criteria=FilterGroup(
                    conditions=[
                        FieldCondition(
                            field=FilterField.YEAR,
                            operator=FilterOperator.GTE,
                            value=2000,
                        ),
                        requested,
                        FieldCondition(
                            field=FilterField.UNPLAYED,
                            operator=FilterOperator.IS,
                            value=True,
                        ),
                    ],
                ),
            ),
        ),
    )
    assert detail.kind is CollectionKind.SMART
    assert manager.provider.synced_labels == [(label, ["m0", "m1"], [])]
    assert manager.provider.smart_filters["1"] == (
        "sort=addedAt%3Adesc&year%3E=2000&and=1&label=5&and=1&unwatched=1"
    )
    async with database.read_session() as session:
        labelled = await CollectionItemRepository(session).library_items(
            MediaType.MOVIE, "1:movies", TermSelection(frozenset({TermKind.LABEL}))
        )
    assert [label in item.values(TermKind.LABEL) for item in labelled] == [
        True,
        True,
        False,
    ]

    manager.lists.ids = [13]
    result = await manager.service.rules.sync(detail.id)
    assert [change.added for change in result.changes] == [0]
    assert manager.provider.synced_labels[-1] == (label, ["m2"], ["m0", "m1"])

    # Without a smart collection filtering on it, Overture removes the label.
    await manager.service.editor.delete(detail.id)
    assert manager.provider.synced_labels[-1] == (label, [], ["m2"])


async def test_a_franchise_set_gives_each_collection_its_tmdb_summary(
    manager: Manager,
) -> None:
    """Without a summary template, a collection takes its list's description."""
    await manager.service.groups.save_policy(
        "Franchises",
        CollectionGroupPolicy(
            generator=CollectionGenerator(
                dimension=SetDimension.FRANCHISE, library_ids=["1:movies"]
            )
        ),
    )

    _, [created] = await group_sync(manager, "Franchises")
    detail = await manager.service.reader.get(created)
    assert detail.summary == "Collection overview"
    assert list(manager.provider.summaries.values()) == ["Collection overview"]


async def test_smart_collections_test_fields_plex_lacks_through_labels(
    manager: Manager, database: Database
) -> None:
    async with database.write_session() as session:
        first = await session.get(MediaItem, manager.ids[0])
        assert first is not None
        first.original_language = "ja"
        session.add(first)
    japanese = FieldCondition(field=FilterField.ORIGINAL_LANGUAGE, value="ja")
    label = condition_label(japanese)
    manager.provider.choices = {"label": [("7", label)]}

    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Japanese",
            rule=library_rule(
                smart=True,
                order_type=CollectionOrder.TITLE_ASC,
                criteria=FilterGroup(conditions=[japanese]),
            ),
        ),
    )

    assert detail.kind is CollectionKind.SMART
    assert manager.provider.synced_labels == [(label, ["m0"], [])]
    assert manager.provider.smart_filters["1"] == "sort=titleSort&label=7"
    # Its Plex filter reads Overture's label, so it cannot be left unmanaged.
    with pytest.raises(PublicServiceError, match="labels only Overture keeps"):
        await manager.service.adoption.orphan(detail.id)


async def test_regular_and_smart_kinds_replace_the_server_collection(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.editor.save_rule(
        identity,
        library_rule(
            smart=True,
            order_type=CollectionOrder.TITLE_ASC,
            criteria=where(FilterField.GENRE, FilterOperator.IS, "Action"),
        ),
    )
    await manager.service.rules.sync(identity)
    assert manager.provider.deleted == ["1"]
    assert manager.provider.smart_filters["2"] == "sort=titleSort&genre=-1"
    smart = await manager.service.reader.get(identity)
    assert smart.kind is CollectionKind.SMART
    with pytest.raises(PublicServiceError, match="controlled by their criteria"):
        await manager.service.editor.set_members(
            identity,
            CollectionMembersUpdate(
                member_ids=manager.ids, order_type=CollectionOrder.CUSTOM
            ),
        )
    await manager.service.editor.save_rule(
        identity,
        library_rule(criteria=where(FilterField.GENRE, FilterOperator.IS, "Action")),
    )
    await manager.service.rules.sync(identity)
    assert manager.provider.deleted == ["1", "2"]
    regular = await manager.service.reader.get(identity)
    assert regular.kind is CollectionKind.REGULAR
    assert len(regular.member_ids) == 3


async def test_seasonal_inactive_withholds_and_deletes_server_collection(
    manager: Manager,
) -> None:
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Holiday",
            active_start_mmdd="01-01",
            active_end_mmdd="01-02",
            rule=library_rule(
                criteria=sources(TmdbItemSource(tmdb_ids=[11, 12])),
                delete_when_inactive=True,
            ),
        ),
    )
    assert detail.withheld
    assert manager.provider.created == []

    # Active collection transitions to inactive and deletes server copy
    active = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Active Seasonal",
            active_start_mmdd="01-01",
            active_end_mmdd="12-31",
            rule=library_rule(
                criteria=sources(TmdbItemSource(tmdb_ids=[11, 12])),
                delete_when_inactive=True,
            ),
        ),
    )
    assert not active.withheld
    assert active.title in manager.provider.created

    await manager.service.editor.update(
        active.id,
        CollectionOptions(
            collection_group="Films",
            title="Active Seasonal",
            active_start_mmdd="01-01",
            active_end_mmdd="01-02",
        ),
    )
    await manager.service.rules.sync(active.id)
    refreshed = await manager.service.reader.get(active.id)
    assert refreshed.withheld is True
    assert refreshed.child_count == 0


async def test_franchise_sets_name_collections_after_tmdb(manager: Manager) -> None:
    await manager.service.groups.save_policy(
        "Franchises",
        CollectionGroupPolicy(
            minimum_items=2,
            sort_title_format="+1_{title}",
            generator=CollectionGenerator(
                dimension=SetDimension.FRANCHISE,
                library_ids=["1:movies"],
                strip_suffix=" Collection",
            ),
        ),
    )
    await manager.service.groups.sync("Franchises", RecordedReport())
    listed = await manager.service.reader.listed()
    assert [
        (row.title, row.collection_group, row.sort_title, row.generated_value)
        for row in listed
    ] == [("Saga", "Franchises", "+1_Saga", "10")]
    assert listed[0].tmdb_collection_id == 10


async def test_non_plex_option_validation(
    manager: Manager, app_config: Settings, database: Database
) -> None:
    jellyfin_service = make_jellyfin_service(manager, app_config, database)
    identity = (
        await created(
            jellyfin_service,
            CollectionCreate(
                collection_group="Films",
                title="Box set",
                rule=chosen(manager),
            ),
        )
    ).id

    with pytest.raises(PublicServiceError, match="can order collections"):
        await jellyfin_service.editor.set_members(
            identity,
            CollectionMembersUpdate(member_ids=[1], order_type=CollectionOrder.CUSTOM),
        )

    with pytest.raises(PublicServiceError, match="can order collections"):
        await jellyfin_service.editor.update(
            identity,
            CollectionOptions(
                collection_group="Films",
                title="Rated",
                order_type=CollectionOrder.PLAYS_DESC,
            ),
        )

    with pytest.raises(PublicServiceError, match="Visibility and home promotion"):
        await jellyfin_service.editor.update(
            identity,
            CollectionOptions(
                collection_group="Films", title="Home", visible_home=True
            ),
        )

    with pytest.raises(PublicServiceError, match="Visibility and home promotion"):
        await jellyfin_service.editor.update(
            identity,
            CollectionOptions(
                collection_group="Films", title="Shared", visible_shared=True
            ),
        )

    with pytest.raises(PublicServiceError, match="Visibility and home promotion"):
        await jellyfin_service.editor.update(
            identity,
            CollectionOptions(
                collection_group="Films", title="Lib", visible_library=True
            ),
        )

    with pytest.raises(PublicServiceError, match="Visibility and home promotion"):
        await jellyfin_service.editor.update(
            identity,
            CollectionOptions(
                collection_group="Films",
                title="Mode",
                collection_mode=CollectionMode.HIDE,
            ),
        )

    with pytest.raises(PublicServiceError, match="Visibility and home promotion"):
        await jellyfin_service.editor.update(
            identity,
            CollectionOptions(
                collection_group="Films",
                title="Filter",
                collection_filtering=CollectionFiltering.ADMIN,
            ),
        )


async def test_rules_accept_only_what_the_server_and_library_offer(
    manager: Manager, app_config: Settings, database: Database
) -> None:
    movies = await create(manager)
    shows = (
        await created(
            manager.service,
            CollectionCreate(
                collection_group="Films",
                title="Anime",
                rule=library_rule(
                    criteria=sources(TmdbItemSource(tmdb_ids=[11])),
                    library_id="1:shows",
                ),
            ),
        )
    ).id
    for collection, library_id, source, message in (
        (shows, "1:shows", RadarrTagSource(tags=["4k"]), "movies only"),
        (shows, "1:shows", TmdbCollectionSource(collection_id=10), "movies only"),
        (movies, "1:movies", SonarrTagSource(tags=["anime"]), "shows only"),
    ):
        with pytest.raises(PublicServiceError, match=message):
            await manager.service.editor.save_rule(
                collection,
                library_rule(criteria=sources(source), library_id=library_id),
            )
    with pytest.raises(PublicServiceError, match="only available in Plex smart"):
        await manager.service.editor.save_rule(
            movies,
            library_rule(criteria=where(FilterField.HDR, FilterOperator.IS, True)),
        )
    with pytest.raises(PublicServiceError, match="is not available for shows on Plex"):
        await manager.service.editor.save_rule(
            shows,
            library_rule(
                criteria=where(FilterField.DIRECTOR, FilterOperator.IS, "Someone"),
                library_id="1:shows",
            ),
        )

    jellyfin = make_jellyfin_service(manager, app_config, database)
    box_set = (
        await created(
            jellyfin,
            CollectionCreate(
                collection_group="Films",
                title="Box set",
                rule=chosen(manager),
            ),
        )
    ).id
    genre = where(FilterField.GENRE, FilterOperator.IS, "Action")
    with pytest.raises(PublicServiceError, match="need a library on a Plex server"):
        await jellyfin.editor.save_rule(
            box_set,
            library_rule(
                criteria=genre, smart=True, order_type=CollectionOrder.TITLE_ASC
            ),
        )
    with pytest.raises(
        PublicServiceError, match="Unplayed is not available for movies on Jelly"
    ):
        await jellyfin.editor.save_rule(
            box_set,
            library_rule(criteria=where(FilterField.UNPLAYED, FilterOperator.IS, True)),
        )


async def test_capabilities_follow_the_server(
    manager: Manager, app_config: Settings, database: Database
) -> None:
    plex = manager.service.discovery.capabilities(MediaType.MOVIE)
    assert plex.smart
    assert CollectionOrder.CUSTOM in plex.orders
    assert CollectionOrder.CUSTOM not in plex.smart_orders
    fields = {field.field: field for field in plex.fields}
    assert (fields[FilterField.HDR].local, fields[FilterField.HDR].smart) == (
        False,
        True,
    )
    assert FilterField.NETWORK not in fields
    sources = {source.type: source.unavailable for source in plex.sources}
    # Only sources that can hold movies are offered for movie collections.
    assert SourceType.SONARR_TAG not in sources
    assert SourceType.RADARR_TAG in sources
    assert sources[SourceType.MDBLIST] is None
    shows = {
        source.type
        for source in manager.service.discovery.capabilities(MediaType.SHOW).sources
    }
    assert SourceType.SONARR_TAG in shows
    assert not shows & {SourceType.RADARR_TAG, SourceType.TMDB_COLLECTION}
    assert SetDimension.FRANCHISE in {entry.dimension for entry in plex.dimensions}

    jellyfin = make_jellyfin_service(manager, app_config, database)
    capabilities = jellyfin.discovery.capabilities(MediaType.MOVIE)
    assert not capabilities.smart
    assert capabilities.smart_orders == []
    labels = {field.field: field.label for field in capabilities.fields}
    assert labels[FilterField.LABEL] == "Tag"
    assert FilterField.UNPLAYED not in labels


async def test_mdblist_lists_name_their_owner_and_size(manager: Manager) -> None:
    assert await manager.service.discovery.mdblist_lists("Top") == [
        MdblistListRead(id=5, name="Top picks", owner="gary", items=9)
    ]


async def test_field_values_count_library_metadata_or_ask_plex(
    manager: Manager,
) -> None:
    genres = await manager.service.discovery.field_values(
        MediaType.MOVIE, "1:movies", FilterField.GENRE
    )
    assert [(entry.value, entry.count) for entry in genres] == [("Action", 3)]
    manager.provider.choices = {"audioLanguage": [("eng", "English")]}
    languages = await manager.service.discovery.field_values(
        MediaType.MOVIE, "1:movies", FilterField.AUDIO_LANGUAGE
    )
    assert [entry.value for entry in languages] == ["English"]
    saga = await create(manager)
    collections = await manager.service.discovery.field_values(
        MediaType.MOVIE, "1:movies", FilterField.COLLECTION
    )
    # Criteria hold a collection's ID, which people choose by its title.
    assert [(entry.value, entry.label, entry.count) for entry in collections] == [
        (str(saga), "Saga", 3)
    ]


async def test_field_values_without_a_library_span_every_library_of_the_type(
    manager: Manager,
) -> None:
    saga = await create(manager)
    discovery = manager.service.discovery

    # A library filter tests every library, so it is offered their values.
    collections = await discovery.field_values(
        MediaType.MOVIE, None, FilterField.COLLECTION
    )
    genres = await discovery.field_values(MediaType.MOVIE, None, FilterField.GENRE)
    shows = await discovery.field_values(MediaType.SHOW, None, FilterField.GENRE)
    # What only Plex can test is no library filter's to offer.
    manager.provider.choices = {"audioLanguage": [("eng", "English")]}
    languages = await discovery.field_values(
        MediaType.MOVIE, None, FilterField.AUDIO_LANGUAGE
    )

    assert [(entry.value, entry.label, entry.count) for entry in collections] == [
        (str(saga), "Saga", 3)
    ]
    assert [(entry.value, entry.count) for entry in genres] == [("Action", 3)]
    assert [entry.value for entry in shows] == ["Animation"]
    assert languages == []


async def test_keyword_values_list_the_common_first_and_add_tmdb_matches(
    manager: Manager, database: Database
) -> None:
    async with database.write_session() as session:
        for index, item_id in enumerate(manager.ids):
            item = await session.get(MediaItem, item_id)
            assert item is not None
            await assign(
                session,
                item,
                tmdb_keyword=["christmas eve", *(["sequel"] if index else [])],
            )

    every = await manager.service.discovery.field_values(
        MediaType.MOVIE, "1:movies", FilterField.TMDB_KEYWORD
    )
    typed = await manager.service.discovery.field_values(
        MediaType.MOVIE, "1:movies", FilterField.TMDB_KEYWORD, " Christ "
    )

    assert [(entry.value, entry.count) for entry in every] == [
        ("christmas eve", 3),
        ("sequel", 2),
    ]
    # TMDB adds keywords no title has yet, after those titles have.
    assert [(entry.value, entry.count) for entry in typed] == [
        ("christmas eve", 3),
        ("christmas", 0),
    ]
    assert manager.tmdb.keyword_queries == ["christ"]


async def test_list_arr_tags(manager: Manager) -> None:
    radarr_tags = await manager.service.arr.radarr_tags()
    assert len(radarr_tags) == 1
    assert radarr_tags[0].id == 1
    assert radarr_tags[0].label == "4k"

    sonarr_tags = await manager.service.arr.sonarr_tags()
    assert len(sonarr_tags) == 1
    assert sonarr_tags[0].id == 2
    assert sonarr_tags[0].label == "anime"


async def test_formatted_options(manager: Manager) -> None:
    identity = await create(manager)

    # Valid sort_title_format
    updated = await manager.service.editor.update(
        identity,
        CollectionOptions(
            title="Star Wars",
            collection_group="Sci-Fi",
            sort_title_format="+1_{title}",
        ),
    )
    assert updated.sort_title == "+1_Star Wars"

    # Too long sort_title_format raises PublicServiceError(422)
    with pytest.raises(PublicServiceError):
        await manager.service.editor.update(
            identity,
            CollectionOptions(
                title="A" * 150,
                collection_group="B" * 60,
                sort_title_format="{title}_{group}",
            ),
        )

    # Valid summary_format
    updated_summary = await manager.service.editor.update(
        identity,
        CollectionOptions(
            collection_group="Films",
            title="Star Wars",
            summary_format="{title} complete saga",
        ),
    )
    assert updated_summary.summary == "Star Wars complete saga"

    # Too long summary_format raises PublicServiceError(422)
    with pytest.raises(PublicServiceError):
        await manager.service.editor.update(
            identity,
            CollectionOptions(
                collection_group="Films",
                title="A" * 200,
                summary_format="X" * 9900 + "{title}",
            ),
        )


async def test_radarr_and_sonarr_tag_builder_sync(manager: Manager) -> None:
    # RadarrTagSource sync
    radarr_col = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="4K Movies",
            rule=library_rule(
                criteria=sources(RadarrTagSource(tags=["4k"])),
            ),
        ),
    )
    assert radarr_col.child_count == 2
    res = await manager.service.rules.sync(radarr_col.id)
    assert [change.added for change in res.changes] == [0]

    # SonarrTagSource sync
    sonarr_col = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Anime Shows",
            rule=library_rule(
                criteria=sources(SonarrTagSource(tags=["anime"])),
                library_id="1:shows",
                minimum_items=1,
            ),
        ),
    )
    assert sonarr_col.child_count == 1
    show_res = await manager.service.rules.sync(sonarr_col.id)
    assert [change.added for change in show_res.changes] == [0]


async def test_create_collection_custom_order(manager: Manager) -> None:
    col = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Custom Order",
            order_type=CollectionOrder.CUSTOM,
            rule=chosen(manager),
        ),
    )
    assert col.order_type is CollectionOrder.CUSTOM


async def test_a_sync_that_fails_midway_keeps_its_copy_for_the_next(
    manager: Manager,
) -> None:
    saved = await manager.service.editor.create(
        CollectionCreate(
            collection_group="Films", title="Half made", rule=chosen(manager)
        )
    )
    manager.provider.rejected_updates.add("1")
    with pytest.raises(ValueError, match="refused"):
        await manager.service.rules.sync(saved.id)
    manager.provider.rejected_updates.clear()
    detail = await synced(manager.service, saved.id)
    assert (manager.provider.created, manager.provider.deleted) == (["Half made"], [])
    assert ([copy.server_item_id for copy in detail.copies], detail.unsynced) == (
        ["1"],
        False,
    )


def test_source_labels_name_stable_identifiers() -> None:
    def label(source: CollectionSource) -> str:
        return source_label(SourceCondition(source=source))

    assert (
        label(TmdbPersonSource(person_id=5292, roles=[TmdbPersonRole.DIRECTOR]))
        == "overture:tmdb_person:5292:director"
    )
    assert label(MdblistSource(identifiers=["user/list"])) == (
        "overture:mdblist:user/list"
    )
    many = label(TmdbItemSource(tmdb_ids=[1, 2]))
    assert many.startswith("overture:tmdb_item:")
    assert many == label(TmdbItemSource(tmdb_ids=[1, 2]))


async def test_seasonal_smart_collection_sync_creates_server_copy(
    manager: Manager,
) -> None:
    # Inactive smart collection starts withheld with no server_item_id
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Seasonal Smart",
            active_start_mmdd="01-01",
            active_end_mmdd="01-02",
            rule=library_rule(
                criteria=where(FilterField.GENRE, FilterOperator.IS, "Action"),
                delete_when_inactive=True,
                smart=True,
                order_type=CollectionOrder.RELEASE_DESC,
            ),
        ),
    )
    assert detail.withheld

    # Make it active and sync, which invokes create_smart_collection
    await manager.service.editor.update(
        detail.id,
        CollectionOptions(
            collection_group="Films",
            title="Seasonal Smart",
            active_start_mmdd="01-01",
            active_end_mmdd="12-31",
        ),
    )
    res = await manager.service.rules.sync(detail.id)
    assert res.skipped is False
    refreshed = await manager.service.reader.get(detail.id)
    assert not refreshed.withheld


async def test_inherited_format_overflow_raises_422(manager: Manager) -> None:
    await manager.service.groups.save_policy(
        "LongGroup",
        CollectionGroupPolicy(
            sort_title_format="Prefix_" + ("A" * 60) + "_{title}",
            summary_format="SummaryPrefix_" + ("B" * 50) + "_{summary}",
        ),
    )
    with pytest.raises(PublicServiceError, match="at most 200 characters"):
        await created(
            manager.service,
            CollectionCreate(
                title="T" * 150,
                collection_group="LongGroup",
                rule=chosen(manager),
            ),
        )
    with pytest.raises(PublicServiceError, match="at most 10000 characters"):
        await created(
            manager.service,
            CollectionCreate(
                title="Normal",
                summary="S" * 9960,
                collection_group="LongGroup",
                rule=chosen(manager),
            ),
        )


async def test_group_policy_validation_errors(
    manager: Manager, app_config: Settings, database: Database
) -> None:
    with pytest.raises(PublicServiceError, match="A group needs a name"):
        await manager.service.groups.save_policy("   ", CollectionGroupPolicy())
    with pytest.raises(PublicServiceError, match="TMDB franchises are not available"):
        await manager.service.groups.save_policy(
            "ShowFranchises",
            CollectionGroupPolicy(
                generator=CollectionGenerator(
                    dimension=SetDimension.FRANCHISE, library_ids=["1:shows"]
                )
            ),
        )
    with pytest.raises(PublicServiceError, match="ordered by Plex"):
        await manager.service.groups.save_policy(
            "SmartGenres",
            CollectionGroupPolicy(
                order_type=CollectionOrder.CUSTOM,
                generator=CollectionGenerator(
                    dimension=SetDimension.GENRE, library_ids=["1:movies"], smart=True
                ),
            ),
        )
    jellyfin_service = make_jellyfin_service(manager, app_config, database)
    with pytest.raises(PublicServiceError, match="Visibility and home promotion"):
        await jellyfin_service.groups.save_policy(
            "NonPlexGroup",
            CollectionGroupPolicy(visible_home=True),
        )
    with pytest.raises(PublicServiceError, match="need a library on a Plex server"):
        await jellyfin_service.groups.save_policy(
            "SmartJellyfin",
            CollectionGroupPolicy(
                generator=CollectionGenerator(
                    dimension=SetDimension.GENRE, library_ids=["1:movies"], smart=True
                )
            ),
        )


async def test_franchise_sets_skip_franchises_other_collections_hold(
    manager: Manager,
) -> None:
    await created(
        manager.service,
        CollectionCreate(
            title="External Franchise",
            collection_group="OtherGroup",
            rule=library_rule(
                criteria=sources(TmdbCollectionSource(collection_id=10)),
            ),
        ),
    )
    generator = CollectionGenerator(
        dimension=SetDimension.FRANCHISE, library_ids=["1:movies"]
    )
    await manager.service.groups.save_policy(
        "Franchises",
        CollectionGroupPolicy(minimum_items=1, generator=generator),
    )
    _, ids = await group_sync(manager, "Franchises")
    assert ids == []
    assert (
        await manager.service.sets.preview(
            CollectionSetPreview(generator=generator, group="OtherGroup")
        )
    )[0].title == "Saga"


async def test_a_universe_of_franchises_is_none_of_them_and_leaves_their_set_whole(
    manager: Manager,
) -> None:
    universe = await created(
        manager.service,
        CollectionCreate(
            title="Saga Universe",
            collection_group="Universes",
            rule=library_rule(
                criteria=sources(
                    TmdbCollectionSource(collection_id=10),
                    TmdbCollectionSource(collection_id=99),
                ),
            ),
        ),
    )
    assert universe.tmdb_collection_id is None
    await manager.service.groups.save_policy(
        "Franchises",
        CollectionGroupPolicy(
            minimum_items=1,
            generator=CollectionGenerator(
                dimension=SetDimension.FRANCHISE, library_ids=["1:movies"]
            ),
        ),
    )
    await group_sync(manager, "Franchises")
    assert [
        (row.title, row.tmdb_collection_id)
        for row in await manager.service.reader.listed()
        if row.collection_group == "Franchises"
    ] == [("Saga", 10)]


async def test_saving_a_set_makes_its_collections_in_overture_before_any_sync(
    manager: Manager,
) -> None:
    await manager.service.groups.save_policy(
        "Franchises",
        CollectionGroupPolicy(
            minimum_items=1,
            generator=CollectionGenerator(
                dimension=SetDimension.FRANCHISE, library_ids=["1:movies"]
            ),
        ),
        new_set=True,
    )
    [saga] = [
        row
        for row in await manager.service.reader.listed()
        if row.collection_group == "Franchises"
    ]
    # Saved as a collection is: in Overture, for the next sync to send.
    assert (saga.title, saga.withheld) == ("Saga", True)
    assert manager.provider.created == []


async def test_turning_a_separator_on_gives_its_group_the_sort_title_it_shows(
    manager: Manager,
) -> None:
    groups = manager.service.groups
    saved = await groups.save_policy("Sagas", CollectionGroupPolicy(separator=True))
    assert saved.sort_title_format == "{group} {title}"
    assert (await groups.policy("Sagas")).sort_title_format == "{group} {title}"
    # Cleared while the separator stays on, it stays cleared.
    await groups.save_policy(
        "Sagas", CollectionGroupPolicy(separator=True, sort_title_format=None)
    )
    assert (await groups.policy("Sagas")).sort_title_format is None
    # A sort title of the group's own is kept as it turns a separator on.
    await groups.save_policy(
        "Parts", CollectionGroupPolicy(separator=True, sort_title_format="~{title}")
    )
    assert (await groups.policy("Parts")).sort_title_format == "~{title}"


async def test_a_new_collection_has_no_theme(manager: Manager) -> None:
    col = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Theme Target",
            rule=chosen(manager),
        ),
    )
    theme = await manager.service.themes.status(col.id)
    assert (theme.youtube_id, theme.status) == (None, AssetStatus.MISSING)


async def test_sync_group_records_rule_errors(manager: Manager) -> None:
    await created(
        manager.service,
        CollectionCreate(
            title="Will Fail",
            collection_group="ErrorGroup",
            rule=library_rule(criteria=sources(MdblistSource(identifiers=["1234"]))),
        ),
    )
    manager.lists.failure = True
    res, _ = await group_sync(manager, "ErrorGroup")
    assert any("Will Fail" in line for line in errors(res))


async def test_a_collection_below_its_minimum_waits_in_overture_for_the_server(
    manager: Manager,
) -> None:
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Empty",
            rule=NOTHING_MATCHES,
        ),
    )
    assert detail.withheld
    assert manager.provider.created == []
    # Once it has enough members, its sync creates it on the server.
    await manager.service.editor.save_rule(
        detail.id,
        library_rule(criteria=sources(MdblistSource(identifiers=["42"]))),
    )
    result = await manager.service.rules.sync(detail.id)
    assert not result.skipped
    assert not result.withheld
    assert not (await manager.service.reader.get(detail.id)).withheld


async def test_inactive_rule_without_delete_skips_sync(manager: Manager) -> None:
    col = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Inactive Seasonal",
            active_start_mmdd="01-01",
            active_end_mmdd="01-02",
            rule=library_rule(
                criteria=sources(TmdbItemSource(tmdb_ids=[11])),
                delete_when_inactive=False,
            ),
        ),
    )
    res = await manager.service.rules.sync(col.id)
    assert res.skipped is True


async def test_bulk_operations_order_and_visibility(manager: Manager) -> None:
    col = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Bulk Config",
            rule=chosen(manager),
        ),
    )
    # set_order
    res_order = await manager.service.bulk.run(
        BulkCollectionOperation(
            operation="set_order",
            collection_ids=[col.id],
            order_type=CollectionOrder.RELEASE_ASC,
        )
    )
    assert res_order.collection_ids == [col.id]

    # set_visibility
    res_vis = await manager.service.bulk.run(
        BulkCollectionOperation(
            operation="set_visibility",
            collection_ids=[col.id],
            collection_mode=CollectionMode.HIDE,
            visible_home=True,
            visible_shared=True,
            visible_library=True,
        )
    )
    assert res_vis.collection_ids == [col.id]
    refreshed = await manager.service.reader.get(col.id)
    assert refreshed.order_type is CollectionOrder.RELEASE_ASC
    assert refreshed.collection_mode is CollectionMode.HIDE
    assert refreshed.visible_home is True
    assert refreshed.visible_shared is True
    assert refreshed.visible_library is True


async def test_bulk_set_order_without_an_order_inherits_the_groups(
    manager: Manager,
) -> None:
    await manager.service.groups.save_policy(
        "Sorted", CollectionGroupPolicy(order_type=CollectionOrder.TITLE_ASC)
    )
    col = await created(
        manager.service,
        CollectionCreate(
            title="Own order",
            collection_group="Sorted",
            order_type=CollectionOrder.RELEASE_ASC,
            rule=chosen(manager),
        ),
    )
    assert (await manager.service.reader.get(col.id)).order_type is (
        CollectionOrder.RELEASE_ASC
    )

    result = await manager.service.bulk.run(
        BulkCollectionOperation(
            operation="set_order", collection_ids=[col.id], order_type=None
        )
    )

    assert result.errors == {}
    assert result.collection_ids == [col.id]
    assert (await manager.service.reader.get(col.id)).order_type is (
        CollectionOrder.TITLE_ASC
    )


def test_bulk_set_order_requires_a_choice() -> None:
    with pytest.raises(ValidationError, match="Choose a sort"):
        BulkCollectionOperation(operation="set_order", collection_ids=[1])


async def test_tmdb_lists_merge_in_order_and_failures_keep_members(
    manager: Manager,
) -> None:
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Lists",
            order_type=CollectionOrder.CUSTOM,
            rule=library_rule(criteria=sources(TmdbListSource(list_ids=[1, 2]))),
        ),
    )
    assert [item.tmdb_id for item in await members(manager, detail)] == [13, 11, 12]
    manager.tmdb.error = ValueError("List temporarily unavailable")
    with pytest.raises(ValueError, match="temporarily unavailable"):
        await manager.service.rules.sync(detail.id)
    refreshed = await manager.service.reader.get(detail.id)
    assert [item.tmdb_id for item in await members(manager, refreshed)] == [13, 11, 12]


async def test_group_apply_updates_inherited_templates_and_preserves_overrides(
    manager: Manager,
) -> None:
    await manager.service.groups.save_policy(
        "Charts",
        CollectionGroupPolicy(
            sort_title_format="01_{title}",
            summary_format="About {title}",
            visible_home=True,
        ),
    )
    inherited = await created(
        manager.service,
        CollectionCreate(
            title="Inherited",
            collection_group="Charts",
            rule=library_rule(criteria=sources(TmdbItemSource(tmdb_ids=[11]))),
        ),
    )
    explicit = await created(
        manager.service,
        CollectionCreate(
            title="Override",
            collection_group="Charts",
            sort_title_format="Custom sort",
            summary_format="Custom summary",
            rule=library_rule(
                criteria=sources(TmdbItemSource(tmdb_ids=[12])), visible_home=False
            ),
        ),
    )
    await manager.service.groups.save_policy(
        "Charts",
        CollectionGroupPolicy(
            sort_title_format="02_{title}",
            summary_format="Updated {title}",
            visible_home=True,
        ),
    )
    # Saving writes only; the group's sync sends what its collections inherit.
    assert (await manager.service.reader.get(inherited.id)).sort_title != "02_Inherited"
    for _ in range(2):
        result, _ = await group_sync(manager, "Charts")
        assert not errors(result)
        assert result[JobOutcome.ADDED] + result[JobOutcome.UNCHANGED] == 2
        refreshed = await manager.service.reader.get(inherited.id)
        assert refreshed.sort_title == "02_Inherited"
        assert refreshed.summary == "Updated Inherited"
        assert refreshed.visible_home is True
        override = await manager.service.reader.get(explicit.id)
        assert override.sort_title == "Custom sort"
        assert override.summary == "Custom summary"
        assert override.visible_home is False
        assert refreshed.member_ids == [manager.ids[0]]


async def test_summary_source_is_not_replaced_by_its_rendered_template(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.editor.update(
        identity,
        CollectionOptions(
            collection_group="Films", title="Saga", summary="Original overview"
        ),
    )
    for _ in range(2):
        result = await manager.service.editor.update(
            identity,
            CollectionOptions(
                collection_group="Films",
                title="Saga",
                summary_format="{title}: {summary}",
            ),
        )
        assert result.summary == "Saga: Original overview"


async def test_rule_sync_resolves_changed_group_defaults_without_freezing_them(
    manager: Manager,
) -> None:
    detail = await created(
        manager.service,
        CollectionCreate(
            title="Inherited",
            collection_group="Shared",
            rule=library_rule(criteria=sources(TmdbItemSource(tmdb_ids=[11]))),
        ),
    )
    assert detail.visible_home is False
    await manager.service.groups.save_policy(
        "Shared",
        CollectionGroupPolicy(visible_home=True, order_type=CollectionOrder.TITLE_ASC),
    )
    await manager.service.rules.sync(detail.id)
    refreshed = await manager.service.reader.get(detail.id)
    assert refreshed.visible_home is True
    assert refreshed.order_type is CollectionOrder.TITLE_ASC
    assert refreshed.rule is not None
    assert refreshed.rule.visible_home is None
    await manager.service.groups.save_policy(
        "Shared", CollectionGroupPolicy(visible_home=False)
    )
    await manager.service.rules.sync(detail.id)
    refreshed = await manager.service.reader.get(detail.id)
    assert refreshed.visible_home is False


async def test_group_sync_commits_successful_collections_and_reports_failures(
    manager: Manager,
) -> None:
    collections = [
        await created(
            manager.service,
            CollectionCreate(
                title=title,
                collection_group="Shared",
                rule=library_rule(criteria=sources(TmdbItemSource(tmdb_ids=[11]))),
            ),
        )
        for title in ("First", "Second")
    ]
    manager.provider.rejected_updates.add("1")
    await manager.service.groups.save_policy(
        "Shared", CollectionGroupPolicy(sort_title_format="01_{title}")
    )
    result, _ = await group_sync(manager, "Shared")
    assert errors(result) == ["Error First - Server refused this update"]
    first = await manager.service.reader.get(collections[0].id)
    second = await manager.service.reader.get(collections[1].id)
    assert first.sort_title is None
    assert second.sort_title == "01_Second"


async def test_bulk_display_edits_keep_inheritance_and_store_reusable_templates(
    manager: Manager,
) -> None:
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="First",
            summary="Original",
            summary_format="{title}: {summary}",
            active_start_mmdd="01-01",
            active_end_mmdd="12-31",
            rule=library_rule(criteria=sources(TmdbItemSource(tmdb_ids=[11]))),
        ),
    )
    for operation in (
        BulkCollectionOperation(
            operation="set_visibility",
            collection_ids=[detail.id],
            visible_shared=True,
        ),
        BulkCollectionOperation(
            operation="apply_sort_title_format",
            collection_ids=[detail.id],
            sort_title_format="01_{title}",
        ),
    ):
        result = await manager.service.bulk.run(operation)
        assert not result.errors
    refreshed = await manager.service.reader.get(detail.id)
    assert refreshed.summary == "First: Original"
    assert refreshed.summary_format == "{title}: {summary}"
    assert refreshed.sort_title == "01_First"
    assert refreshed.sort_title_format == "01_{title}"
    assert refreshed.active_start_mmdd == "01-01"
    assert refreshed.rule is not None
    assert refreshed.rule.visible_home is None
    assert refreshed.rule.visible_shared is True
    assert refreshed.rule.order_type is None


async def test_a_saved_collection_stays_off_the_server_until_synced(
    manager: Manager,
) -> None:
    saved = await manager.service.editor.create(
        CollectionCreate(
            collection_group="Films",
            title="Draft",
            rule=library_rule(criteria=sources(TmdbItemSource(tmdb_ids=[11]))),
        )
    )
    assert (saved.withheld, saved.unsynced) == (True, True)
    assert manager.provider.created == []

    detail = await synced(manager.service, saved.id)
    assert manager.provider.created == ["Draft"]
    assert (detail.withheld, detail.unsynced) == (False, False)


async def test_saved_edits_wait_for_sync(manager: Manager) -> None:
    identity = await create(manager)
    await manager.service.editor.update(
        identity, CollectionOptions(collection_group="Films", title="Renamed")
    )
    detail = await manager.service.editor.set_members(
        identity,
        CollectionMembersUpdate(
            member_ids=list(reversed(manager.ids)), order_type=CollectionOrder.CUSTOM
        ),
    )
    assert (detail.title, detail.unsynced) == ("Renamed", True)
    assert detail.member_ids == list(reversed(manager.ids))
    assert manager.provider.members["1"] == ["m0", "m1", "m2"]
    assert manager.provider.options["1"][0] == "Saga"

    detail = await synced(manager.service, identity)
    assert sorted(manager.provider.members["1"]) == ["m0", "m1", "m2"]
    assert manager.provider.options["1"][0] == "Renamed"
    assert detail.unsynced is False


async def test_append_sync_sends_members_chosen_since_the_last_sync(
    manager: Manager,
) -> None:
    saved = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Append",
            rule=library_rule(
                criteria=sources(TmdbItemSource(tmdb_ids=[11])),
                sync_mode=SyncMode.APPEND,
            ),
        ),
    )
    picked = [*saved.member_ids, manager.ids[2]]
    await manager.service.editor.set_members(
        saved.id,
        CollectionMembersUpdate(member_ids=picked, order_type=CollectionOrder.CUSTOM),
    )
    detail = await synced(manager.service, saved.id)
    assert {member.id for member in await members(manager, detail)} == set(picked)
    assert detail.unsynced is False


def _chart(limit: int = 3) -> FilterGroup:
    return sources(TmdbChartSource(chart=TmdbChart.POPULAR, limit=limit))


async def _set_requests(database: Database, *, folder: str = "/movies") -> None:
    async with database.write_session() as session:
        await session.merge(
            settings_row(radarr_root_folder=folder, radarr_quality_profile_id=4)
        )


async def test_a_chart_keeps_its_order_for_its_region(manager: Manager) -> None:
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Popular",
            order_type=CollectionOrder.CUSTOM,
            rule=library_rule(criteria=_chart()),
        ),
    )
    assert [member.title for member in await members(manager, detail)] == [
        "Manual",
        "Second",
    ]
    assert manager.tmdb.chart_requests == [(TmdbChart.POPULAR, 3, "US")]


async def test_missing_titles_list_and_request_what_the_library_lacks(
    manager: Manager, database: Database
) -> None:
    collection = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Popular",
            rule=library_rule(criteria=_chart()),
        ),
    )
    assert (await manager.service.reader.get(collection.id)).lists_missing
    missing = await manager.service.arr.missing(collection.id)
    assert [
        (title.tmdb_id, title.title, title.requested) for title in missing.titles
    ] == [(99, "Missing 99", False)]
    assert missing.requestable
    with pytest.raises(PublicServiceError, match="root folder"):
        await manager.service.arr.request_missing(collection.id, CollectionRequest())
    await _set_requests(database)
    result = await manager.service.arr.request_missing(
        collection.id, CollectionRequest()
    )
    assert (result.requested, result.present) == (1, 0)
    radarr = manager.radarr
    assert [
        (tmdb_id, request.root_folder, request.tag_ids)
        for tmdb_id, request in radarr.added
    ] == [(99, "/movies", (77,))]
    assert radarr.tag_labels == ["overture"]
    already = await manager.service.arr.request_missing(
        collection.id,
        CollectionRequest(
            titles=[CollectionRequestTitle(tmdb_id=11, media_type=MediaType.MOVIE)]
        ),
    )
    assert (already.requested, already.present) == (0, 1)


async def test_a_sync_labels_tags_requests_and_orders_home(
    manager: Manager, database: Database
) -> None:
    await _set_requests(database)
    collection = await manager.service.editor.create(
        CollectionCreate(
            title="Popular",
            collection_group="Charts",
            visible_home=True,
            rule=library_rule(
                criteria=_chart(),
                member_label="{title} members",
                arr_tag="{group}",
                request_missing=True,
                home_order=1,
            ),
        ),
    )
    await manager.service.rules.sync(collection.id)
    assert any(
        label == "Popular members" for label, _, _ in manager.provider.synced_labels
    )
    radarr = manager.radarr
    assert [tmdb_id for tmdb_id, _ in radarr.added] == [99]
    # Members Radarr holds get the tag; the fake holds only First.
    assert radarr.tag_edits == [(77, [], True), (77, [1], False)]
    assert manager.provider.hub_orders[-1] == ["1"]


async def test_collections_sharing_an_arr_tag_keep_each_others_members(
    manager: Manager,
) -> None:
    """Radarr accepts a-z, 0-9 and -, so both templates render one tag."""
    holder = await manager.service.editor.create(
        CollectionCreate(
            collection_group="Films",
            title="Holder",
            rule=library_rule(
                criteria=sources(TmdbItemSource(tmdb_ids=[11])), arr_tag="Shared Tag"
            ),
        ),
    )
    other = await manager.service.editor.create(
        CollectionCreate(
            collection_group="Films",
            title="Other",
            rule=library_rule(
                criteria=sources(TmdbItemSource(tmdb_ids=[12])), arr_tag="shared-tag"
            ),
        ),
    )
    await manager.service.rules.sync(holder.id)
    await manager.service.rules.sync(other.id)

    radarr = manager.radarr
    assert radarr.tag_labels == ["shared-tag", "shared-tag"]
    # Radarr holds only First, which the holder keeps tagged.
    assert all(not ids for _, ids, add in radarr.tag_edits if not add)


async def test_a_failed_effect_is_recorded_after_members_sync(
    manager: Manager,
) -> None:
    collection = await manager.service.editor.create(
        CollectionCreate(
            collection_group="Films",
            title="Popular",
            rule=library_rule(criteria=_chart(), request_missing=True),
        ),
    )
    with pytest.raises(PublicServiceError, match="Request missing failed"):
        await manager.service.rules.sync(collection.id)
    detail = await manager.service.reader.get(collection.id)
    assert [member.title for member in await members(manager, detail)] == [
        "Second",
        "Manual",
    ]
    assert detail.rule is not None
    assert detail.rule.last_error is not None


async def test_custom_sets_list_their_collections_across_libraries(
    manager: Manager, database: Database
) -> None:
    async with database.write_session() as session:
        session.add(
            served_item(
                media_type=MediaType.MOVIE,
                title="Spare",
                tmdb_id=40,
                server_item_id="x0",
                library_id="1:extra",
            )
        )
    starts = FilterOperator.STARTS_WITH
    generator = CollectionGenerator(
        dimension=SetDimension.CUSTOM,
        library_ids=["1:movies", "1:extra"],
        custom_values=[
            CustomSetValue(name="S", criteria=where(FilterField.TITLE, starts, "S")),
            CustomSetValue(name="F", criteria=where(FilterField.TITLE, starts, "F")),
        ],
    )
    preview = await manager.service.sets.preview(
        CollectionSetPreview(generator=generator, minimum_items=1)
    )
    assert [
        (entry.library_id, entry.title, entry.member_count) for entry in preview
    ] == [
        ("1:movies", "S", 1),
        ("1:movies", "F", 1),
        ("1:extra", "S", 1),
        ("1:extra", "F", 0),
    ]
    await manager.service.groups.save_policy(
        "Letters",
        CollectionGroupPolicy(minimum_items=1, generator=generator),
    )
    _, ids = await group_sync(manager, "Letters")
    # A value is one collection across the libraries holding it.
    assert len(ids) == 2
    spanning = await manager.service.reader.get(ids[0])
    assert spanning.library_ids == ["1:movies", "1:extra"]


async def test_aliases_rename_and_merge_values(manager: Manager) -> None:
    generator = CollectionGenerator(
        dimension=SetDimension.DECADE,
        library_ids=["1:movies"],
        title_format="{value}s",
        aliases=[SetValueAlias(values=["1990", "2000"], name="Turn of the century")],
    )
    preview = await manager.service.sets.preview(
        CollectionSetPreview(generator=generator, minimum_items=1)
    )
    assert [(entry.value, entry.title, entry.member_count) for entry in preview] == [
        ("1990|2000", "Turn of the century", 3)
    ]


async def test_plex_counts_a_dimension_only_it_knows(manager: Manager) -> None:
    manager.provider.choices = {
        "audioLanguage": [("eng", "English"), ("fra", "French")]
    }
    generator = CollectionGenerator(
        dimension=SetDimension.AUDIO_LANGUAGE, library_ids=["1:movies"], smart=True
    )
    preview = await manager.service.sets.preview(
        CollectionSetPreview(generator=generator, minimum_items=2)
    )
    assert [
        (entry.title, entry.member_count, entry.below_minimum) for entry in preview
    ] == [
        ("English", 3, False),
        ("French", 1, True),
    ]
    with pytest.raises(PublicServiceError, match="smart collections"):
        await manager.service.sets.preview(
            CollectionSetPreview(
                generator=generator.model_copy(update={"smart": False}),
            )
        )


async def test_a_smart_collection_tests_a_collection_by_the_index_plex_keys_it_by(
    manager: Manager,
) -> None:
    held = await create(manager, [manager.ids[0]])
    rating_key = (await manager.service.reader.get(held)).copies[0].server_item_id
    # Plex lists its collections by index, with a rating key Overture records.
    manager.provider.choices = {"collection": [("3", rating_key), ("4", "unknown")]}
    await manager.service.discovery.preview(
        CollectionPreviewRequest(
            rule=library_rule(
                criteria=where(FilterField.COLLECTION, FilterOperator.IS, str(held)),
                smart=True,
            ),
        )
    )
    assert "collection=3" in manager.provider.queries[-1]


async def test_a_value_plex_leaves_off_its_list_is_found_through_an_item_holding_it(
    manager: Manager,
) -> None:
    # Plex lists no genres here, while the first movie holds Action as key 12.
    manager.provider.item_choices = {("m0", "genre"): [("12", "Action")]}
    await manager.service.discovery.preview(
        CollectionPreviewRequest(
            rule=library_rule(
                criteria=where(FilterField.GENRE, FilterOperator.IS, "Action"),
                smart=True,
            ),
        )
    )
    assert "genre=12" in manager.provider.queries[-1]


async def test_previews_count_members_before_saving(manager: Manager) -> None:
    local = await manager.service.discovery.preview(
        CollectionPreviewRequest(
            rule=library_rule(
                criteria=where(FilterField.YEAR, FilterOperator.GTE, 2000),
                order_type=CollectionOrder.TITLE_ASC,
            ),
        )
    )
    assert (local.libraries[0].member_count, local.libraries[0].members) == (
        2,
        ["Manual", "Second"],
    )
    smart = await manager.service.discovery.preview(
        CollectionPreviewRequest(
            rule=library_rule(
                criteria=where(FilterField.HDR, FilterOperator.IS, value=True),
                smart=True,
            ),
        )
    )
    assert (smart.libraries[0].member_count, smart.libraries[0].members) == (
        1,
        ["First", "Second"],
    )
    # Plex answers for a smart collection even where Overture knows the field.
    await manager.service.discovery.preview(
        CollectionPreviewRequest(
            rule=library_rule(
                criteria=where(FilterField.YEAR, FilterOperator.GTE, 2000),
                order_type=CollectionOrder.ADDED_DESC,
                smart=True,
            ),
        )
    )
    assert manager.provider.queries[-1] == "sort=addedAt%3Adesc&year%3E=2000"


async def test_source_summary_follows_the_first_list(manager: Manager) -> None:
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Listed",
            summary_format="From TMDB: {source_summary}",
            rule=library_rule(criteria=sources(TmdbListSource(list_ids=[1]))),
        ),
    )
    assert detail.summary == "From TMDB: List 1"


def test_tmdb_facts_are_tested_like_other_metadata() -> None:
    item = holding(
        MediaItem(
            media_type=MediaType.SHOW,
            title="Show",
            original_language="Japanese",
            tmdb_votes=500,
            last_aired=utc_now().date().isoformat(),
        ),
        tmdb_keyword=["christmas"],
        streaming=["Netflix"],
    )
    context = CriteriaContext(sources={}, collections={}, now=utc_now())
    for tested, operator, value in (
        (FilterField.TMDB_KEYWORD, FilterOperator.IS, "Christmas"),
        (FilterField.ORIGINAL_LANGUAGE, FilterOperator.IS, "japanese"),
        (FilterField.TMDB_VOTES, FilterOperator.GTE, 100),
        (FilterField.LAST_AIRED, FilterOperator.IN_LAST, 7),
        (FilterField.STREAMING, FilterOperator.IS_NOT, "Hulu"),
    ):
        assert FIELDS[tested].tmdb
        criteria = FilterGroup(
            conditions=[FieldCondition(field=tested, operator=operator, value=value)]
        )
        assert evaluate([item], criteria, context) == [item], tested
    assert FIELDS[FilterField.VERSIONS].plex is None


async def test_adoption_puts_an_unmanaged_collection_in_its_group(
    manager: Manager, database: Database
) -> None:
    identity = await create_unmanaged(manager, database)
    unmanaged = await manager.service.reader.get(identity)
    assert unmanaged.tmdb_collection_id is None
    # An unmanaged collection is in no stored group, even if it names one;
    # Films is where the helper first made it.
    assert await manager.service.groups.names() == ["Films"]

    detail = await manager.service.adoption.adopt(
        identity, CollectionAdoption(group="Sagas")
    )

    assert await manager.service.groups.names() == ["Films", "Sagas"]
    assert detail.collection_group == "Sagas"
    assert detail.rule is not None
    # Every member belongs to TMDB collection 10, which becomes its source.
    assert detail.rule.libraries[0].criteria == FilterGroup(
        mode="all",
        conditions=[SourceCondition(source=TmdbCollectionSource(collection_id=10))],
    )
    assert detail.member_ids == manager.ids
    assert detail.tmdb_collection_id == 10
    with pytest.raises(PublicServiceError, match="already manages"):
        await manager.service.adoption.adopt(
            identity,
            CollectionAdoption(
                group="Films",
            ),
        )


async def test_adoption_names_members_that_share_no_franchise(
    manager: Manager, database: Database
) -> None:
    identity = await create_unmanaged(manager, database)
    async with database.write_session() as session:
        item = await session.get(MediaItem, manager.ids[-1])
        assert item is not None
        item.tmdb_collection_id = 20
        session.add(item)

    detail = await manager.service.adoption.adopt(
        identity,
        CollectionAdoption(
            group="Films",
        ),
    )

    assert detail.rule is not None
    assert detail.rule.libraries[0].criteria == sources(
        TmdbItemSource(tmdb_ids=[11 + index for index in range(len(manager.ids))])
    )
    assert detail.tmdb_collection_id is None


def test_adoption_names_members_by_tmdb_then_tvdb_then_imdb_then_title() -> None:
    members = [
        holding(
            MediaItem(id=1, media_type=MediaType.SHOW, title="A", tmdb_id=7, tvdb_id=70)
        ),
        holding(
            MediaItem(
                id=2, media_type=MediaType.SHOW, title="B", tvdb_id=80, imdb_id="tt8"
            )
        ),
        holding(MediaItem(id=3, media_type=MediaType.SHOW, title="C", imdb_id="tt9")),
        holding(MediaItem(id=4, media_type=MediaType.SHOW, title="D")),
    ]
    row = MediaCollection(title="Saga")

    criteria = member_criteria(row, members, franchise=None)

    assert criteria == FilterGroup(
        mode="any",
        conditions=[
            SourceCondition(source=TmdbItemSource(tmdb_ids=[7])),
            FieldCondition(field=FilterField.TVDB_ID, value="80"),
            FieldCondition(field=FilterField.IMDB_ID, value="tt9"),
            FieldCondition(field=FilterField.TITLE, value="D"),
        ],
    )
    context = CriteriaContext(sources={}, collections={}, now=utc_now())
    by_ids = FilterGroup(mode="any", conditions=criteria.conditions[1:])
    assert evaluate(members, by_ids, context) == members[1:]


def test_adoption_criteria_name_a_collection_larger_than_one_source_holds() -> None:
    def holding_movie(identity: int, **ids: Any) -> CollectionItem:
        return holding(
            MediaItem(
                id=identity, media_type=MediaType.MOVIE, title=f"M{identity}", **ids
            )
        )

    row = MediaCollection(title="Large")
    tagged = [holding_movie(n, tmdb_id=n) for n in range(1, 1253)]
    untagged = [holding_movie(n, imdb_id=f"tt{n}") for n in range(2000, 2150)]

    criteria = member_criteria(row, [*tagged, *untagged], franchise=None)

    sources = criteria.source_conditions()
    named = [
        tmdb_id
        for condition in sources
        if isinstance(condition.source, TmdbItemSource)
        for tmdb_id in condition.source.tmdb_ids
    ]
    assert named == list(range(1, 1253))
    assert len(criteria.field_conditions()) == len(untagged)
    # The criteria are a valid rule as saved.
    CollectionRuleWrite.model_validate(
        {"libraries": [{"library_id": "1:movies", "criteria": criteria.model_dump()}]}
    )

    too_many = [holding_movie(n, imdb_id=f"tt{n}") for n in range(1, 2002)]
    with pytest.raises(PublicServiceError, match="more titles without a TMDB ID"):
        member_criteria(row, too_many, franchise=None)


async def test_orphan_reverses_adoption_keeping_the_server_copy(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.editor.update(
        identity,
        CollectionOptions(title="Saga", collection_group="Sagas"),
    )

    detail = await manager.service.adoption.orphan(identity)

    assert not detail.managed
    assert detail.rule is None
    assert detail.collection_group is None
    assert not detail.withheld
    assert detail.member_ids == manager.ids
    # The group outlives its last collection, until it is deleted.
    assert await manager.service.groups.names() == ["Films", "Sagas"]
    with pytest.raises(PublicServiceError, match="does not manage"):
        await manager.service.adoption.orphan(identity)
    refused = await manager.service.bulk.run(
        BulkCollectionOperation(collection_ids=[identity], operation="orphan")
    )
    assert refused.errors == {identity: "Adopt the collection before changing it"}

    adopted = await manager.service.adoption.adopt(
        identity, CollectionAdoption(group="Sagas")
    )
    assert adopted.managed
    orphaned = await manager.service.bulk.run(
        BulkCollectionOperation(collection_ids=[identity], operation="orphan")
    )
    assert orphaned.collection_ids == [identity]


async def test_orphan_refuses_a_collection_without_a_server_copy(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.editor.delete(identity, target="server")

    with pytest.raises(PublicServiceError, match="not on the media server"):
        await manager.service.adoption.orphan(identity)
    assert (await manager.service.reader.get(identity)).managed


async def test_bulk_delete_removes_only_the_server_copy_when_asked(
    manager: Manager,
) -> None:
    identity = await create(manager)

    result = await manager.service.bulk.run(
        BulkCollectionOperation(
            collection_ids=[identity],
            operation="delete",
            delete_target="server",
        )
    )

    assert result.collection_ids == [identity]
    detail = await manager.service.reader.get(identity)
    assert detail.withheld
    assert detail.managed


async def test_the_unmanaged_name_is_reserved(manager: Manager) -> None:
    identity = await create(manager)
    await manager.service.editor.update(
        identity,
        CollectionOptions(title="Saga", collection_group="Weekend"),
    )
    with pytest.raises(PublicServiceError, match="reserved"):
        await manager.service.groups.save_policy("unmanaged", CollectionGroupPolicy())
    with pytest.raises(PublicServiceError, match="reserved"):
        await manager.service.groups.rename("Weekend", " UNMANAGED ")
    for invalid in (
        lambda: CollectionOptions(title="Saga", collection_group="Unmanaged"),
        lambda: CollectionGroupRename(name="unmanaged"),
        lambda: CollectionAdoption(group="Unmanaged"),
    ):
        with pytest.raises(ValidationError, match="reserved"):
            invalid()


async def test_group_sync_keeps_plexs_order_for_smart_members_under_a_custom_one(
    manager: Manager,
) -> None:
    regular, smart = [
        await created(
            manager.service,
            CollectionCreate(
                title=title,
                collection_group="Mixed",
                rule=library_rule(
                    criteria=where(FilterField.STUDIO, FilterOperator.IS, "Studio"),
                    smart=title == "Smart",
                ),
            ),
        )
        for title in ("Regular", "Smart")
    ]
    await manager.service.groups.save_policy(
        "Mixed",
        CollectionGroupPolicy(order_type=CollectionOrder.CUSTOM),
    )

    result, _ = await group_sync(manager, "Mixed")

    assert not errors(result)
    assert (await manager.service.reader.get(regular.id)).order_type is (
        CollectionOrder.CUSTOM
    )
    assert (await manager.service.reader.get(smart.id)).order_type is not (
        CollectionOrder.CUSTOM
    )


def test_assigning_or_adopting_into_a_group_names_one() -> None:
    for operation in ("set_group", "adopt"):
        with pytest.raises(ValidationError, match="Choose a group"):
            BulkCollectionOperation(collection_ids=[1], operation=operation)
    with pytest.raises(ValidationError, match="at least 1"):
        CollectionAdoption(group="  ")  # blank, once stripped


@pytest.mark.parametrize(
    ("criteria", "order", "expected"),
    [
        # Native filters alone suit a smart collection, which Plex keeps current.
        (
            where(FilterField.STUDIO, FilterOperator.IS, "Studio"),
            CollectionOrder.TITLE_ASC,
            (CollectionKind.SMART, "Plex filters every condition natively"),
        ),
        (
            where(FilterField.HDR, FilterOperator.IS, True),
            CollectionOrder.TITLE_ASC,
            (CollectionKind.SMART, "Only Plex can test HDR is."),
        ),
        (
            sources(TmdbItemSource(tmdb_ids=[11])),
            CollectionOrder.TITLE_ASC,
            (CollectionKind.REGULAR, "Lists and tags have no Plex filter"),
        ),
        (
            where(FilterField.TMDB_RATING, FilterOperator.GTE, 7),
            CollectionOrder.TITLE_ASC,
            (CollectionKind.REGULAR, "Plex has no filter for TMDB rating is at least"),
        ),
        # Only Plex tests HDR, and a smart collection tests TMDB facts by label.
        (
            FilterGroup(
                conditions=[
                    FieldCondition(field=FilterField.HDR, value=True),
                    FieldCondition(
                        field=FilterField.TMDB_RATING,
                        operator=FilterOperator.GTE,
                        value=7,
                    ),
                ]
            ),
            CollectionOrder.TITLE_ASC,
            (CollectionKind.SMART, "Only Plex can test HDR is."),
        ),
        (
            where(FilterField.STUDIO, FilterOperator.IS, "Studio"),
            CollectionOrder.CUSTOM,
            (CollectionKind.REGULAR, "Plex cannot keep a custom order."),
        ),
    ],
)
def test_kind_recommendation_follows_what_plex_can_evaluate(
    manager: Manager,
    criteria: FilterGroup,
    order: CollectionOrder,
    expected: tuple[CollectionKind, str] | None,
) -> None:
    capabilities = manager.service.discovery.capabilities(MediaType.MOVIE)
    found = recommend_kind(
        criteria, capabilities, media_type=MediaType.MOVIE, order=order
    )
    if expected is None:
        assert found is None
    else:
        assert found is not None
        assert found.kind is expected[0]
        assert found.reason.startswith(expected[1])
    assert (
        recommend_kind(
            criteria,
            capabilities.model_copy(update={"smart": False}),
            media_type=MediaType.MOVIE,
            order=order,
        )
        is None
    )


async def test_preview_counts_titles_tmdb_has_not_described_yet(
    manager: Manager, database: Database
) -> None:
    async with database.write_session() as session:
        item = await session.get(MediaItem, manager.ids[0])
        assert item is not None
        item.tmdb_checked_id = item.tmdb_id
        session.add(item)

    def preview(field: FilterField, value: str) -> CollectionPreviewRequest:
        return CollectionPreviewRequest(
            rule=library_rule(criteria=where(field, FilterOperator.IS, value)),
        )

    keyword = await manager.service.discovery.preview(
        preview(FilterField.TMDB_KEYWORD, "christmas")
    )
    studio = await manager.service.discovery.preview(
        preview(FilterField.STUDIO, "Studio")
    )

    assert (keyword.libraries[0].member_count, keyword.libraries[0].tmdb_unread) == (
        0,
        2,
    )
    assert studio.libraries[0].tmdb_unread == 0


async def test_the_kind_is_recommended_without_a_preview(manager: Manager) -> None:
    recommendation = await manager.service.discovery.recommend(
        CollectionKindRequest(
            rule=library_rule(criteria=sources(TmdbItemSource(tmdb_ids=[11]))),
        )
    )
    assert recommendation is not None
    assert recommendation.kind is CollectionKind.REGULAR


async def test_collection_rows_report_art_size_source_and_shape(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, identity)
        assert row is not None
        seed_asset(
            row,
            ServerAsset.POSTER,
            url="https://image.tmdb.org/t/p/original/a.jpg",
            poster_style=CollectionPosterStyle.INDIVIDUAL,
            file_hash="hash",
            fingerprint="a" * 64,
            width=1000,
            height=1000,
        )
        session.add(row)

    [listed] = await manager.service.reader.listed()

    poster = listed.assets.poster
    assert (poster.width, poster.height, poster.source) == (1000, 1000, "tmdb")
    assert listed.assets.background.width is None
    assert listed.has_incorrect_aspect_ratio


async def test_bulk_clears_forget_collection_art_and_theme_choices(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, identity)
        assert row is not None
        select_art(
            row,
            ServerAsset.POSTER,
            PublicArtUrl("https://image.tmdb.org/t/p/original/a.jpg"),
            poster_style=CollectionPosterStyle.INDIVIDUAL,
        )
        seed_theme(row, "abcdefghijk")
        session.add(row)

    for operation in ("remove_artwork", "remove_themes"):
        result = await manager.service.bulk.run(
            BulkCollectionOperation(
                collection_ids=[identity],
                operation=operation,
            )
        )
        assert result.collection_ids == [identity]

    assert manager.art.removed == [(identity, None, AssetRemoval())]
    detail = await manager.service.reader.get(identity)
    assert detail.assets.theme.youtube_id is None


async def test_unmanaged_collections_accept_only_adoption(
    manager: Manager, database: Database
) -> None:
    identity = await create_unmanaged(manager, database)
    for change in (
        manager.service.editor.update(
            identity, CollectionOptions(collection_group="Films", title="X")
        ),
        manager.service.rules.sync(identity),
        manager.service.editor.delete(identity),
        manager.service.editor.set_monitored(identity, False),
        manager.service.editor.save_rule(
            identity,
            library_rule(criteria=sources(TmdbItemSource(tmdb_ids=[11]))),
        ),
    ):
        with pytest.raises(PublicServiceError, match="Adopt the collection"):
            await change
    refused = await manager.service.bulk.run(
        BulkCollectionOperation(
            collection_ids=[identity],
            operation="set_group",
            collection_group="Sagas",
        )
    )
    assert refused.errors == {identity: "Adopt the collection before changing it"}

    await manager.service.adoption.adopt(
        identity,
        CollectionAdoption(
            group="Films",
        ),
    )
    await manager.service.editor.set_monitored(identity, False)
    again = await manager.service.bulk.run(
        BulkCollectionOperation(
            collection_ids=[identity], operation="adopt", collection_group="Films"
        )
    )
    assert again.errors == {identity: "Overture already manages it"}


async def test_every_dimension_previews_with_its_defaults(manager: Manager) -> None:
    capabilities = manager.service.discovery.capabilities(MediaType.MOVIE)
    for entry in capabilities.dimensions:
        if entry.dimension is SetDimension.CUSTOM:
            continue
        # On Plex every dimension makes a smart set too, testing by label
        # what Plex cannot test itself.
        for smart in {entry.smart_only, True}:
            generator = CollectionGenerator(
                dimension=entry.dimension,
                library_ids=["1:movies"],
                title_format=entry.title_format,
                strip_prefix=entry.strip_prefix,
                strip_suffix=entry.strip_suffix,
                smart=smart,
            )
            await manager.service.sets.preview(
                CollectionSetPreview(generator=generator)
            )


async def test_shows_list_the_resolutions_their_episodes_come_in(
    manager: Manager, database: Database
) -> None:
    async with database.write_session() as session:
        show = (
            await session.exec(
                select(MediaItem).where(MediaItem.title == "Anime Series")
            )
        ).one()
        await assign(session, show, resolution=["4k", "1080"])

    values = await manager.service.discovery.field_values(
        MediaType.SHOW, "1:shows", FilterField.RESOLUTION
    )

    # Sync stores Plex's keys, which every server's resolutions are named as.
    assert [(value.value, value.count) for value in values] == [("1080", 1), ("4k", 1)]


def spanning(
    manager: Manager, *, movies: FilterGroup | None = None, **fields: object
) -> CollectionRuleWrite:
    """A rule holding the first fixture movie and the fixture show."""
    return CollectionRuleWrite.model_validate(
        {
            "libraries": [
                CollectionLibraryCriteria(
                    library_id="1:movies",
                    criteria=movies or sources(TmdbItemSource(tmdb_ids=[11])),
                ),
                CollectionLibraryCriteria(
                    library_id="1:shows",
                    criteria=where(
                        FilterField.TITLE, FilterOperator.IS, "Anime Series"
                    ),
                ),
            ],
            **fields,
        }
    )


async def test_a_collection_spans_a_plex_library_of_each_type_as_one_collection_each(
    manager: Manager,
) -> None:
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films", title="Everything", rule=spanning(manager)
        ),
    )

    # Plex keeps a collection in one library, so each holds its own copy.
    assert manager.provider.created == ["Everything", "Everything"]
    assert manager.provider.members == {"1": ["m0"], "2": ["s1"]}
    assert detail.media_types == [MediaType.MOVIE, MediaType.SHOW]
    assert detail.library_ids == ["1:movies", "1:shows"]
    assert {member.title for member in await members(manager, detail)} == {
        "First",
        "Anime Series",
    }
    assert detail.child_count == 2

    await manager.service.editor.update(
        detail.id,
        CollectionOptions(collection_group="Films", title="Everything", summary="Both"),
    )
    await synced(manager.service, detail.id)
    assert manager.provider.summaries == {"1": "Both", "2": "Both"}
    assert manager.provider.created == ["Everything", "Everything"]

    await manager.service.editor.delete(detail.id)
    assert sorted(manager.provider.deleted) == ["1", "2"]


async def test_a_refused_copy_leaves_the_others_synced_and_placed(
    manager: Manager, database: Database
) -> None:
    manager.provider.refused_libraries = {"1:shows"}
    detail = await manager.service.editor.create(
        CollectionCreate(
            collection_group="Films", title="Everything", rule=spanning(manager)
        )
    )

    outcome = await manager.service.rules.sync(detail.id)

    assert [(c.library_ids, c.created, c.error) for c in outcome.changes] == [
        (("1:movies",), True, None),
        (("1:shows",), False, "Create failed"),
    ]
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(detail.id)
    assert row is not None
    # The copy made before the other server refused stays known, so the next
    # sync updates it instead of making a second.
    assert [part.server_item_id for part in row.libraries] == ["1", None]
    assert (await manager.service.reader.get(detail.id)).unsynced

    manager.provider.refused_libraries = set()
    outcome = await manager.service.rules.sync(detail.id)

    assert outcome.errors is None
    assert manager.provider.created == ["Everything", "Everything"]
    assert manager.provider.members == {"1": ["m0"], "2": ["s1"]}


@pytest.mark.parametrize("smart", [False, True], ids=["regular", "smart"])
async def test_a_collection_a_failed_creation_left_is_found_not_made_again(
    manager: Manager, database: Database, *, smart: bool
) -> None:
    """A server can make a collection and still fail the request that asked."""
    manager.provider.titled["saga"] = ServerCollection(
        "77", "Saga", ("m9",), media_type=MediaType.MOVIE, smart=smart
    )
    manager.provider.members["77"] = ["m9"]

    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Saga",
            rule=chosen(manager, [manager.ids[0]]),
        ),
    )

    async with database.read_session() as session:
        row = await CollectionRepository(session).get(detail.id)
    assert row is not None
    if smart:
        # A smart collection is not what a regular one needs: Overture makes its own.
        assert manager.provider.created == ["Saga"]
        assert [part.server_item_id for part in row.libraries] == ["1"]
    else:
        assert manager.provider.created == []
        assert [part.server_item_id for part in row.libraries] == ["77"]
        assert manager.provider.members["77"] == ["m0"]


async def test_a_server_collection_reusing_a_deleted_ones_id_has_one_owner(
    manager: Manager, database: Database
) -> None:
    """Jellyfin gives a BoxSet made again the ID of the one it deleted."""
    stale = await create_unmanaged(manager, database)
    manager.provider.created = []

    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Again",
            rule=chosen(manager, [manager.ids[0]]),
        ),
    )

    async with database.read_session() as session:
        repository = CollectionRepository(session)
        assert await repository.get(stale) is None
        owner = await repository.find_server(TEST_SERVER_ID, "1")
    assert owner is not None
    assert owner.id == detail.id


async def test_one_boxset_holds_every_library_on_jellyfin(
    manager: Manager, app_config: Settings, database: Database
) -> None:
    provider = JellyfinProvider(app_config)
    service = make_jellyfin_service(manager, app_config, database, provider)
    detail = await created(
        service,
        CollectionCreate(
            collection_group="Films", title="Everything", rule=spanning(manager)
        ),
    )

    assert provider.created == ["Everything"]
    assert provider.members == {"1": ["m0", "s1"]}
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(detail.id)
    assert row is not None
    assert [part.server_item_id for part in row.libraries] == ["1", "1"]
    assert [part.server_item_id for part in row.copies] == ["1"]

    await service.editor.delete(detail.id)
    assert provider.deleted == ["1"]


async def test_libraries_saved_apart_fold_into_one_boxset(
    manager: Manager, app_config: Settings, database: Database
) -> None:
    """A set's per-library collections merge into one on upgrade, BoxSets and all."""
    provider = JellyfinProvider(app_config)
    service = make_jellyfin_service(manager, app_config, database, provider)
    detail = await created(
        service,
        CollectionCreate(
            collection_group="Films", title="Everything", rule=spanning(manager)
        ),
    )
    provider.members["2"] = ["s1"]
    async with database.write_session() as session:
        row = await CollectionRepository(session).get(detail.id)
        assert row is not None
        row.libraries[1].server_item_id = "2"
        session.add(row)

    await service.rules.sync(detail.id)

    assert provider.deleted == ["2"]
    assert provider.members["1"] == ["m0", "s1"]
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(detail.id)
    assert row is not None
    assert [part.server_item_id for part in row.copies] == ["1"]


async def test_adding_a_library_reaches_the_server_only_when_synced(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager, [manager.ids[0]])
    await manager.service.editor.save_rule(identity, spanning(manager))
    assert manager.provider.created == ["Saga"]

    await manager.service.rules.sync(identity)

    assert manager.provider.created == ["Saga", "Saga"]
    assert manager.provider.members["2"] == ["s1"]
    detail = await manager.service.reader.get(identity)
    assert detail.media_types == [MediaType.MOVIE, MediaType.SHOW]
    assert detail.rule is not None
    assert [entry.library_id for entry in detail.rule.libraries] == [
        "1:movies",
        "1:shows",
    ]


async def test_removing_a_library_takes_its_copy_off_at_the_next_sync(
    manager: Manager, database: Database
) -> None:
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films", title="Everything", rule=spanning(manager)
        ),
    )
    await manager.service.editor.save_rule(
        detail.id,
        library_rule(criteria=sources(TmdbItemSource(tmdb_ids=[11]))),
    )

    # Saving never touches the server; the library waits for the next sync.
    assert manager.provider.deleted == []
    saved = await manager.service.reader.get(detail.id)
    assert saved.rule is not None
    assert [entry.library_id for entry in saved.rule.libraries] == ["1:movies"]

    await manager.service.rules.sync(detail.id)

    assert manager.provider.deleted == ["2"]
    synced = await manager.service.reader.get(detail.id)
    assert synced.library_ids == ["1:movies"]
    assert [member.title for member in await members(manager, synced)] == ["First"]


async def test_a_library_with_nothing_to_hold_gets_no_copy_until_it_has(
    manager: Manager, database: Database
) -> None:
    rule = CollectionRuleWrite(
        libraries=[
            CollectionLibraryCriteria(
                library_id="1:movies", criteria=sources(TmdbItemSource(tmdb_ids=[11]))
            ),
            CollectionLibraryCriteria(
                library_id="1:shows",
                criteria=where(FilterField.TITLE, FilterOperator.IS, "Not yet"),
            ),
        ]
    )
    detail = await created(
        manager.service,
        CollectionCreate(collection_group="Films", title="Everything", rule=rule),
    )
    assert manager.provider.created == ["Everything"]
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(detail.id)
    assert row is not None
    assert [part.server_item_id for part in row.libraries] == ["1", None]


async def test_each_library_is_validated_against_what_it_holds(
    manager: Manager,
) -> None:
    with pytest.raises(PublicServiceError, match="movies only"):
        await created(
            manager.service,
            CollectionCreate(
                collection_group="Films",
                title="Everything",
                rule=CollectionRuleWrite(
                    libraries=[
                        CollectionLibraryCriteria(
                            library_id="1:movies",
                            criteria=sources(TmdbItemSource(tmdb_ids=[11])),
                        ),
                        CollectionLibraryCriteria(
                            library_id="1:shows",
                            criteria=sources(RadarrTagSource(tags=["4k"])),
                        ),
                    ]
                ),
            ),
        )
    with pytest.raises(ValidationError, match="one set of criteria"):
        CollectionRuleWrite(
            libraries=[
                CollectionLibraryCriteria(
                    library_id="1:movies",
                    criteria=sources(TmdbItemSource(tmdb_ids=[11])),
                ),
                CollectionLibraryCriteria(
                    library_id="1:movies",
                    criteria=sources(TmdbItemSource(tmdb_ids=[12])),
                ),
            ]
        )


async def test_movie_and_show_collections_share_one_group(manager: Manager) -> None:
    await manager.service.groups.save_policy(
        "Shared", CollectionGroupPolicy(sort_title_format="1_{title}")
    )
    for title, library_id, criteria in (
        ("Films", "1:movies", sources(TmdbItemSource(tmdb_ids=[11]))),
        (
            "Series",
            "1:shows",
            where(FilterField.TITLE, FilterOperator.IS, "Anime Series"),
        ),
    ):
        await created(
            manager.service,
            CollectionCreate(
                title=title,
                collection_group="Shared",
                rule=library_rule(criteria=criteria, library_id=library_id),
            ),
        )

    assert "Shared" in await manager.service.groups.names()
    assert set(manager.provider.sort_titles.values()) == {"1_Films", "1_Series"}
    result, _ = await group_sync(manager, "Shared")
    assert not errors(result)
    assert {
        tuple(row.media_types)
        for row in await manager.service.reader.listed()
        if row.collection_group == "Shared"
    } == {(MediaType.MOVIE,), (MediaType.SHOW,)}


async def test_orphaning_leaves_plex_copies_for_the_next_sync_to_list(
    manager: Manager, database: Database
) -> None:
    detail = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films", title="Everything", rule=spanning(manager)
        ),
    )

    orphaned = await manager.service.adoption.orphan(detail.id)

    assert orphaned.managed is False
    assert orphaned.library_ids == ["1:movies"]
    assert manager.provider.deleted == []
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(detail.id)
        assert row is not None
        assert [
            delivery.server_item_id
            for delivery in read_asset(row, ServerAsset.POSTER).deliveries
        ] == ["1"]


async def test_a_new_copy_receives_the_saved_art_and_theme(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager, [manager.ids[0]])
    async with database.write_session() as session:
        row = await CollectionRepository(session).get(identity)
        assert row is not None
        select_art(
            row,
            ServerAsset.POSTER,
            PublicArtUrl("https://example.test/poster.jpg"),
            poster_style=CollectionPosterStyle.INDIVIDUAL,
        )
        session.add(row)
    await manager.service.editor.save_rule(identity, spanning(manager))

    await manager.service.rules.sync(identity)

    assert manager.art.selections == [ArtType.POSTER]


async def test_a_group_takes_a_sort_every_collection_it_holds_can_use(
    manager: Manager,
) -> None:
    only_movies = CollectionOrder.DURATION_DESC
    await created(
        manager.service,
        CollectionCreate(
            title="Long films",
            collection_group="Films",
            rule=library_rule(criteria=sources(TmdbItemSource(tmdb_ids=[11]))),
        ),
    )

    # Shows have no Plex duration sort, but this group holds only movies.
    await manager.service.groups.save_policy(
        "Films", CollectionGroupPolicy(order_type=only_movies)
    )

    # A group that could come to hold either offers what both can use.
    with pytest.raises(PublicServiceError, match="can order"):
        await manager.service.groups.save_policy(
            "Empty", CollectionGroupPolicy(order_type=only_movies)
        )


async def test_monitoring_tells_clients_only_the_new_flag(manager: Manager) -> None:
    identity = await create(manager)
    manager.publisher.broadcasts.clear()

    await manager.service.editor.set_monitored(identity, False)

    assert manager.publisher.broadcasts == [
        ("collection.monitored", {"collection_id": identity, "monitored": False})
    ]


async def test_a_catch_all_collection_holds_what_no_other_collection_does(
    manager: Manager,
) -> None:
    await create(manager, [manager.ids[0]])
    collectionless = FilterGroup(
        conditions=[
            FieldCondition(
                field=FilterField.IN_COLLECTION, operator=FilterOperator.IS, value=False
            )
        ]
    )
    catch_all = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Everything else",
            rule=library_rule(criteria=collectionless),
        ),
    )
    assert catch_all.member_ids == manager.ids[1:]

    # Its own members never count as held elsewhere, so a sync keeps them.
    await manager.service.rules.sync(catch_all.id)
    detail = await manager.service.reader.get(catch_all.id)
    assert detail.member_ids == manager.ids[1:]


async def test_a_collection_condition_follows_the_collection_through_a_rename(
    manager: Manager,
) -> None:
    held = await create(manager, [manager.ids[0]])
    in_saga = FilterGroup(
        conditions=[
            FieldCondition(
                field=FilterField.COLLECTION,
                operator=FilterOperator.IS,
                value=str(held),
            )
        ]
    )
    following = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Saga picks",
            rule=library_rule(criteria=in_saga),
        ),
    )
    assert following.member_ids == [manager.ids[0]]

    await manager.service.editor.update(
        held, CollectionOptions(collection_group="Films", title="Renamed")
    )
    await manager.service.rules.sync(following.id)

    detail = await manager.service.reader.get(following.id)
    assert detail.member_ids == [manager.ids[0]]


async def test_a_plex_group_separator_heads_its_collections_while_it_is_on(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    await manager.service.editor.update(
        identity, CollectionOptions(title="Saga", collection_group="Sagas")
    )
    manager.art.selections.clear()

    await manager.service.groups.save_policy(
        "Sagas",
        CollectionGroupPolicy(separator=True, sort_title_format="{group} {title}"),
    )
    # Saving only writes; the group's next sync adds the separator.
    async with database.read_session() as session:
        assert all(
            row.kind is not CollectionKind.SEPARATOR
            for row in await CollectionRepository(session).list_listed()
        )
    await manager.service.groups.sync("Sagas", RecordedReport())

    # The group keeps it, so it is never listed on its own.
    assert all(
        row.kind is not CollectionKind.SEPARATOR
        for row in await manager.service.reader.listed()
    )
    async with database.read_session() as session:
        [separator] = [
            row
            for row in await CollectionRepository(session).list_listed()
            if row.kind is CollectionKind.SEPARATOR
        ]
    assert (separator.title, separator.group_name) == ("Sagas", "Sagas")
    assert separator.child_count == 0
    assert separator.id is not None
    assert copy_id(separator) is not None
    # Its sort title is the group's with no title, so it sorts first.
    assert manager.provider.sort_titles[copy_id(separator) or ""] == "Sagas"
    # Empty, it has no Plex hub to show or hide.
    assert manager.provider.empty[copy_id(separator) or ""] is True
    assert ArtType.POSTER in manager.art.selections
    with pytest.raises(PublicServiceError, match="group keeps the separator"):
        await manager.service.editor.update(
            separator.id, CollectionOptions(collection_group="Films", title="Other")
        )

    await manager.service.groups.save_policy(
        "Sagas", CollectionGroupPolicy(sort_title_format="{group} {title}")
    )
    await manager.service.groups.sync("Sagas", RecordedReport())
    async with database.read_session() as session:
        assert not [
            row
            for row in await CollectionRepository(session).list_listed()
            if row.kind is CollectionKind.SEPARATOR
        ]


async def test_automatic_art_keeps_an_upload_and_generates_a_missing_poster(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        await session.merge(
            settings_row(
                collection_auto_art=[
                    AutoArtSource.OVERTUREDB,
                    AutoArtSource.TMDB,
                    AutoArtSource.GENERATE,
                ]
            )
        )
        row = await CollectionRepository(session).get(identity)
        assert row is not None
        # An uploaded background every copy already shows.
        seed_asset(
            row, ServerAsset.BACKGROUND, upload_hash="b" * 64, file_hash="b" * 64
        )
        session.add(row)
    manager.art.selections.clear()

    await manager.service.rules.sync(identity)

    # Only the empty poster is matched; the uploaded background stays chosen.
    assert manager.art.selections == [ArtType.POSTER]
    manager.art.fail = True
    manager.art.selections.clear()
    await manager.service.groups.save_policy(
        "Films",
        CollectionGroupPolicy(
            auto_art=[AutoArtSource.GENERATE], generated_title_only=True
        ),
    )
    async with database.write_session() as session:
        row = await CollectionRepository(session).get(identity)
        assert row is not None
        clear_selection(row, ServerAsset.POSTER)
        session.add(row)
    manager.art.fail = False
    await manager.service.rules.sync(identity)
    assert manager.art.selections == [ArtType.POSTER]
    assert manager.art.generated == [ArtType.POSTER]
    # The group says its generated posters show the title alone.
    assert manager.art.title_only == [True]


@pytest.mark.parametrize(
    ("auto_art", "urls"),
    [
        (
            [AutoArtSource.OVERTUREDB, AutoArtSource.TMDB],
            ["https://overturedb.test/a.jpg"],
        ),
        ([AutoArtSource.TMDB], ["https://example.test/poster.jpg"]),
        ([AutoArtSource.OVERTUREDB], ["https://overturedb.test/a.jpg"]),
        (
            [AutoArtSource.TMDB, AutoArtSource.OVERTUREDB],
            ["https://example.test/poster.jpg"],
        ),
        # Generating stops the order, so a source after it is never asked.
        ([AutoArtSource.GENERATE, AutoArtSource.OVERTUREDB], [None]),
        ([], []),
    ],
)
async def test_automatic_art_takes_the_first_source_in_its_order(
    manager: Manager,
    database: Database,
    auto_art: list[AutoArtSource],
    urls: list[str | None],
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        await session.merge(
            settings_row(collection_auto_art=auto_art, collection_backgrounds=False)
        )
    manager.art.offered = {
        "overturedb": [ArtCandidate(url="https://overturedb.test/a.jpg")],
        **manager.art.offered,
    }
    manager.art.urls.clear()

    await manager.service.rules.sync(identity)

    assert manager.art.urls == urls


async def test_automatic_art_never_takes_the_servers_own_art_and_generates_without_any(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        await session.merge(
            settings_row(
                collection_auto_art=[AutoArtSource.OVERTUREDB, AutoArtSource.GENERATE],
                collection_backgrounds=False,
            )
        )
    manager.art.selections.clear()
    manager.art.urls.clear()

    await manager.service.rules.sync(identity)

    assert manager.art.urls == [None]
    assert manager.art.generated == [ArtType.POSTER]


async def test_a_separated_group_without_a_sort_title_still_sorts_behind_its_separator(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    await manager.service.editor.update(
        identity, CollectionOptions(title="The Saga", collection_group="The Sagas")
    )

    await manager.service.groups.save_policy(
        "The Sagas", CollectionGroupPolicy(separator=True)
    )
    await manager.service.groups.sync("The Sagas", RecordedReport())

    async with database.read_session() as session:
        rows = await CollectionRepository(session).list_listed()
    [separator] = [row for row in rows if row.kind is CollectionKind.SEPARATOR]
    [member] = [row for row in rows if row.kind is not CollectionKind.SEPARATOR]
    sort_titles = manager.provider.sort_titles
    assert sort_titles[copy_id(separator) or ""] == "Sagas"
    assert sort_titles[copy_id(member) or ""] == "Sagas Saga"
    assert min(title or "" for title in sort_titles.values()) == "Sagas"
    # A separator belongs to its group, which alone shows it.
    assert separator.group_name == "The Sagas"
    assert separator.id not in {row.id for row in await manager.service.reader.listed()}
    with pytest.raises(PublicServiceError, match="Collection not found"):
        await manager.service.reader.get(separator.id or 0)


async def test_deleting_group_with_separator_discards_separator(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.editor.update(
        identity, CollectionOptions(title="Saga", collection_group="Sagas")
    )
    await manager.service.groups.save_policy(
        "Sagas",
        CollectionGroupPolicy(separator=True, sort_title_format="{group} {title}"),
    )
    await manager.service.groups.sync("Sagas", RecordedReport())
    async with manager.database.read_session() as session:
        listed = await CollectionRepository(session).list_listed()
    assert any(row.kind is CollectionKind.SEPARATOR for row in listed)

    result = await manager.service.groups.delete(
        "Sagas", CollectionGroupDelete(collections="both")
    )
    assert not result.errors
    async with manager.database.read_session() as session:
        assert not await CollectionRepository(session).list_listed()


async def test_separator_apply_raises_title_taken_on_collision(
    manager: Manager,
) -> None:
    await created(
        manager.service,
        CollectionCreate(title="Sagas", collection_group="Other", rule=chosen(manager)),
    )
    await created(
        manager.service,
        CollectionCreate(
            title="Part 2", collection_group="Sagas", rule=chosen(manager)
        ),
    )
    with pytest.raises(
        PublicServiceError, match="already has a collection titled Sagas"
    ):
        await manager.service.groups.save_policy(
            "Sagas", CollectionGroupPolicy(separator=True)
        )
    async with manager.database.read_session() as session:
        group = await CollectionRepository(session).group("Sagas")
    assert group is not None
    assert not group.separator


async def test_renaming_a_separated_group_to_a_taken_title_changes_nothing(
    manager: Manager,
) -> None:
    await created(
        manager.service,
        CollectionCreate(title="Sagas", collection_group="Other", rule=chosen(manager)),
    )
    await created(
        manager.service,
        CollectionCreate(
            title="Part 2", collection_group="Parts", rule=chosen(manager)
        ),
    )
    await manager.service.groups.save_policy(
        "Parts", CollectionGroupPolicy(separator=True)
    )
    with pytest.raises(
        PublicServiceError, match="already has a collection titled Sagas"
    ):
        await manager.service.groups.rename("Parts", "Sagas")
    async with manager.database.read_session() as session:
        repo = CollectionRepository(session)
        assert await repo.group("Parts") is not None
        assert await repo.group("Sagas") is None


async def test_preview_smart_collection_with_labelled_fields_evaluates_locally(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.groups.save_policy(
        "Films", CollectionGroupPolicy(order_type=CollectionOrder.RELEASE_ASC)
    )
    preview = await manager.service.discovery.preview(
        CollectionPreviewRequest(
            collection_id=identity,
            rule=library_rule(
                criteria=where(FilterField.TMDB_ID, FilterOperator.IS, "11"),
                smart=True,
            ),
        )
    )
    assert len(preview.libraries) == 1
    assert preview.libraries[0].member_count == 1
    assert preview.libraries[0].members == ["First"]


async def test_generator_validation_rejects_sources_when_plex_counts(
    manager: Manager,
) -> None:
    generator = CollectionGenerator(
        dimension=SetDimension.AUDIO_LANGUAGE,
        library_ids=["1:movies"],
        smart=True,
        criteria=sources(TmdbCollectionSource(collection_id=10)),
    )
    with pytest.raises(
        PublicServiceError,
        match="every collection's conditions must be ones Plex tests itself",
    ):
        await manager.service.groups.save_policy(
            "Languages", CollectionGroupPolicy(generator=generator)
        )


@pytest.mark.parametrize("backgrounds", [True, False])
async def test_automatic_generation_titles_posters_and_generates_backgrounds_it_needs(
    manager: Manager, database: Database, backgrounds: bool
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        await session.merge(
            settings_row(
                collection_auto_art=[AutoArtSource.GENERATE],
                collection_backgrounds=backgrounds,
            )
        )
    manager.art.selections.clear()

    await manager.service.rules.sync(identity)

    wanted = [ArtType.POSTER, ArtType.BACKGROUND] if backgrounds else [ArtType.POSTER]
    assert manager.art.generated == wanted
    detail = await manager.service.reader.get(identity)
    assert detail.assets.background.needed is backgrounds
    if not backgrounds:
        assert detail.assets.background.status is AssetStatus.COMPLETE


async def test_chosen_collections_sync_alone(manager: Manager) -> None:
    rule = library_rule(criteria=sources(TmdbItemSource(tmdb_ids=[11])))
    chosen_one = await manager.service.editor.create(
        CollectionCreate(collection_group="Films", title="Chosen", rule=rule)
    )
    await manager.service.editor.create(
        CollectionCreate(collection_group="Films", title="Left", rule=rule)
    )

    result = RecordedReport()
    await manager.service.groups.sync_collections([chosen_one.id, 999], result)

    assert result.lines == ["[Plex] Added Chosen - created in Movies with 1 title"]
    assert manager.provider.created == ["Chosen"]


async def test_a_server_leaving_keeps_managed_collections_and_forgets_its_own(
    manager: Manager, app_config: Settings, database: Database
) -> None:
    await MediaServerRoster(
        database=database, provider_registry=ProviderRegistry(app_config=app_config)
    ).reconcile()
    saga = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films",
            title="Saga",
            collection_mode=CollectionMode.HIDE_ITEMS,
            visible_home=True,
            order_type=CollectionOrder.CUSTOM,
            rule=chosen(manager),
        ),
    )
    unmanaged = await created(
        manager.service,
        CollectionCreate(
            collection_group="Films", title="Theirs", rule=chosen(manager)
        ),
    )
    async with database.write_session() as session:
        rule = await CollectionRepository(session).rule(unmanaged.id)
        await session.delete(rule)

    configure(app_config, type=ServerType.JELLYFIN)
    configure(app_config, url="http://jellyfin.test:8096")
    await MediaServerRoster(
        database=database, provider_registry=ProviderRegistry(app_config=app_config)
    ).reconcile()

    async with database.read_session() as session:
        repo = CollectionRepository(session)
        assert await repo.get(unmanaged.id) is None
        row = await repo.get(saga.id)
        libraries = await LibraryRepository(session).listed()
    assert row is not None
    # Its Plex copy waits for Plex's return, or for a sync to move the
    # collection to the library its titles turn up in; its choices stay, and
    # each server keeps those it can.
    assert [(part.server_id, part.server_item_id) for part in row.copies] == [(1, "1")]
    assert (row.collection_mode, row.visible_home, row.order_type) == (
        CollectionMode.HIDE_ITEMS,
        True,
        CollectionOrder.CUSTOM,
    )
    assert all(library.server_id != 1 for library in libraries)


async def test_a_collection_takes_over_the_server_one_of_its_title(
    manager: Manager, database: Database
) -> None:
    saved = await manager.service.editor.create(
        CollectionCreate(collection_group="Films", title="Saga", rule=chosen(manager))
    )
    async with database.write_session() as session:
        session.add(
            stored_collection(
                server_item_id="9",
                library_id="1:movies",
                title="Saga",
                last_synced_at=utc_now(),
            )
        )

    detail = await synced(manager.service, saved.id)

    assert manager.provider.created == []
    assert [copy.server_item_id for copy in detail.copies] == ["9"]
    assert [row.title for row in await manager.service.reader.listed()] == ["Saga"]


async def test_a_collection_takes_over_the_server_one_of_its_franchise(
    manager: Manager, database: Database
) -> None:
    saved = await manager.service.editor.create(
        CollectionCreate(collection_group="Films", title="Saga", rule=chosen(manager))
    )
    async with database.write_session() as session:
        row = await session.get(MediaCollection, saved.id)
        assert row is not None
        row.tmdb_collection_id = 1565
        session.add(row)
        # Emby names the franchise collection it makes after TMDB.
        session.add(
            stored_collection(
                server_item_id="9",
                library_id="1:movies",
                title="Saga Collection",
                tmdb_collection_id=1565,
                last_synced_at=utc_now(),
            )
        )

    detail = await synced(manager.service, saved.id)

    assert manager.provider.created == []
    assert [copy.server_item_id for copy in detail.copies] == ["9"]
    assert [row.title for row in await manager.service.reader.listed()] == ["Saga"]


async def test_collections_sets_and_schedules_follow_a_moved_library(
    manager: Manager, app_config: Settings, database: Database
) -> None:
    saga = await created(
        manager.service,
        CollectionCreate(collection_group="Films", title="Saga", rule=chosen(manager)),
    )
    await manager.service.groups.save_policy(
        "Decades",
        CollectionGroupPolicy(
            generator=CollectionGenerator(
                dimension=SetDimension.DECADE, library_ids=["1:movies"]
            )
        ),
    )
    async with database.write_session() as session:
        session.add(
            SavedSchedule(
                kind=ScheduleKind.ASSETS,
                name="Nightly",
                cron_expression="0 3 * * *",
                payload={"library_ids": ["1:movies", "1:shows"]},
                created_at=utc_now(),
                updated_at=utc_now(),
            )
        )
        # The server now lists the movies under another library.
        await LibraryRepository(session).record(
            TEST_SERVER_ID,
            [
                ServerSection(
                    "new-movies", "Films", MediaType.MOVIE, library_id="1:new-movies"
                ),
                ServerSection("shows", "Shows", MediaType.SHOW, library_id="1:shows"),
            ],
            utc_now(),
        )
    reconciler = LibraryReconciler(
        publisher=manager.publisher,
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=unused(DownloadService),
        app_config=app_config,
        database=database,
    )

    followed = await reconciler.follow_moved_libraries(
        Counter(
            {
                ("1:movies", MediaType.MOVIE, "1:new-movies"): 3,
                ("1:movies", MediaType.MOVIE, "1:shows"): 1,
            }
        )
    )

    assert followed == [("1:movies", "1:new-movies")]
    assert (await manager.service.reader.get(saga.id)).library_ids == ["1:new-movies"]
    policy = await manager.service.groups.policy("Decades")
    assert policy.generator is not None
    assert policy.generator.library_ids == ["1:new-movies"]
    async with database.read_session() as session:
        (schedule,) = (await session.exec(select(SavedSchedule))).all()
    assert schedule.payload["library_ids"] == ["1:new-movies", "1:shows"]


async def test_a_library_filter_matches_each_condition_on_its_own(
    manager: Manager,
) -> None:
    filters = manager.service.library_filters
    first, second, manual = manager.ids
    action = FieldCondition(
        field=FilterField.GENRE, operator=FilterOperator.IS, value="Action"
    )
    named = FieldCondition(
        field=FilterField.TITLE, operator=FilterOperator.IS_NOT, value="Manual"
    )
    # The show holds it, in a library of another media type.
    animation = FieldCondition(
        field=FilterField.GENRE, operator=FilterOperator.IS, value="Animation"
    )

    matched = await filters.match(
        LibraryFilterMatchRequest(
            media_type=MediaType.MOVIE, conditions=[action, named, animation]
        )
    )

    assert matched.item_ids == [[first, second, manual], [first, second], []]
    unarted = FieldCondition(
        field=FilterField.ART_STATUS, operator=FilterOperator.IS, value="missing"
    )
    with pytest.raises(PublicServiceError, match="tested in the browser"):
        await filters.match(
            LibraryFilterMatchRequest(media_type=MediaType.MOVIE, conditions=[unarted])
        )


async def test_library_status_fields_are_library_filters_only(manager: Manager) -> None:
    capabilities = manager.service.library_filters.capabilities(MediaType.MOVIE)
    offered = {entry.field: entry for entry in capabilities.fields}
    assert offered[FilterField.ART_STATUS].library_status
    assert [choice.value for choice in offered[FilterField.ART_STATUS].choices] == [
        "complete",
        "partial",
        "missing",
    ]
    assert not offered[FilterField.GENRE].library_status
    assert FilterField.OVERTUREDB_POSTER in offered
    # Movies have no seasons.
    assert FilterField.SEASON_POSTERS_STATUS not in offered
    collection_fields = manager.service.discovery.capabilities(MediaType.MOVIE).fields
    assert FilterField.ART_STATUS not in {entry.field for entry in collection_fields}
    with pytest.raises(PublicServiceError, match="not available"):
        await manager.service.editor.create(
            CollectionCreate(
                collection_group="Films",
                title="Unarted",
                rule=library_rule(
                    criteria=where(FilterField.ART_STATUS, FilterOperator.IS, "missing")
                ),
            )
        )


async def test_saved_filters_are_kept_by_name_for_every_media_type_they_suit(
    manager: Manager,
) -> None:
    saved = manager.service.saved_filters
    horror = where(FilterField.GENRE, FilterOperator.IS, "Horror")

    created = await saved.create(
        SavedFilterWrite(
            name="  Late   night ", criteria=horror, media_type=MediaType.MOVIE
        )
    )
    assert (created.name, created.media_types) == (
        "Late night",
        [MediaType.MOVIE, MediaType.SHOW],
    )
    with pytest.raises(PublicServiceError, match="already named"):
        await saved.create(
            SavedFilterWrite(
                name="LATE NIGHT", criteria=horror, media_type=MediaType.SHOW
            )
        )
    # Only shows have seasons, so the filter is offered for shows alone.
    seasons = await saved.create(
        SavedFilterWrite(
            name="Seasons",
            media_type=MediaType.SHOW,
            criteria=where(
                FilterField.SEASON_POSTERS_STATUS, FilterOperator.IS, "missing"
            ),
        )
    )
    assert seasons.media_types == [MediaType.SHOW]
    assert seasons.unavailable[MediaType.MOVIE].endswith(
        "is not available for movies on Plex"
    )

    renamed = await saved.update(
        created.id,
        SavedFilterWrite(name="Horror", criteria=horror, media_type=MediaType.SHOW),
    )
    assert [entry.name for entry in await saved.list()] == ["Horror", "Seasons"]
    assert renamed.criteria == horror

    # TMDB IDs name the titles of the media type the filter is made for.
    picks = await saved.create(
        SavedFilterWrite(
            name="Picks",
            media_type=MediaType.MOVIE,
            criteria=sources(TmdbItemSource(tmdb_ids=[1])),
        )
    )
    assert (picks.media_type, picks.media_types) == (MediaType.MOVIE, [MediaType.MOVIE])
    assert picks.unavailable == {MediaType.SHOW: "Its TMDB IDs name movies"}
    assert renamed.media_type is None

    await saved.delete(created.id)
    assert [entry.name for entry in await saved.list()] == ["Picks", "Seasons"]
    with pytest.raises(PublicServiceError, match="not found"):
        await saved.delete(created.id)


async def test_collection_mutations_keep_ledger_needs_and_deliveries_current(
    manager: Manager, database: Database
) -> None:
    await manager.service.groups.save_policy(
        "Minimal", CollectionGroupPolicy(backgrounds=False, themes=False)
    )
    created_detail = await manager.service.editor.create(
        CollectionCreate(
            title="Minimal Saga",
            collection_group="Minimal",
            rule=chosen(manager),
        )
    )
    assert created_detail.assets.background.needed is False
    assert created_detail.assets.background.status is AssetStatus.COMPLETE
    assert created_detail.assets.theme.needed is False
    assert created_detail.assets.theme.status is AssetStatus.COMPLETE

    moved = await manager.service.editor.update(
        created_detail.id,
        CollectionOptions(title="Minimal Saga", collection_group="Other"),
    )
    assert moved.assets.background.needed is True
    assert moved.assets.theme.needed is True

    # Moving back and deleting the group re-evaluates inherited needs.
    await manager.service.editor.update(
        created_detail.id,
        CollectionOptions(title="Minimal Saga", collection_group="Minimal"),
    )
    assert (
        await manager.service.reader.get(created_detail.id)
    ).assets.theme.needed is False
    await manager.service.groups.delete(
        "Minimal", CollectionGroupDelete(collections="move", group="Films")
    )
    after_group_delete = await manager.service.reader.get(created_detail.id)
    assert after_group_delete.assets.background.needed is True
    assert after_group_delete.assets.theme.needed is True

    # Withholding removes delivery targets at once.
    synced_detail = await synced(manager.service, created_detail.id)
    assert len(synced_detail.assets.poster.deliveries) == 1
    await manager.service.editor.delete(created_detail.id, target="server")
    withheld = await manager.service.reader.get(created_detail.id)
    assert withheld.assets.poster.deliveries == []

    # Orphaning clears non-lead copies and former group policy on the ledger.
    await manager.service.groups.save_policy(
        "Themeless", CollectionGroupPolicy(themes=False)
    )
    spanned = await created(
        manager.service,
        CollectionCreate(
            title="Everything",
            collection_group="Themeless",
            rule=spanning(manager),
        ),
    )
    assert spanned.assets.theme.needed is False
    orphaned = await manager.service.adoption.orphan(spanned.id)
    assert orphaned.assets.theme.needed is True
    assert orphaned.assets.theme.status is AssetStatus.MISSING
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(spanned.id)
        assert row is not None
        assert [
            delivery.server_item_id
            for delivery in read_asset(row, ServerAsset.POSTER).deliveries
        ] == ["2"]


async def test_a_sync_logs_what_it_did_to_each_server_collection(
    manager: Manager, database: Database
) -> None:
    async with database.write_session() as session:
        session.add(
            served_item(
                media_type=MediaType.MOVIE,
                title="Spare",
                tmdb_id=40,
                server_item_id="x0",
                library_id="1:extra",
            )
        )
    starts = where(FilterField.TITLE, FilterOperator.STARTS_WITH, "S")
    detail = await manager.service.editor.create(
        CollectionCreate(
            collection_group="Films",
            title="Esses",
            rule=CollectionRuleWrite(
                libraries=[
                    CollectionLibraryCriteria(library_id=library, criteria=starts)
                    for library in ("1:movies", "1:extra")
                ],
                minimum_items=1,
            ),
        )
    )
    first = RecordedReport()
    await manager.service.groups.sync_collections([detail.id], first)
    again = RecordedReport()
    await manager.service.groups.sync_collections([detail.id], again)
    await manager.service.editor.save_rule(
        detail.id, library_rule(criteria=starts, minimum_items=1)
    )
    unticked = RecordedReport()
    await manager.service.groups.sync_collections([detail.id], unticked)

    assert first.lines == [
        "[Plex] Added Esses - created in Movies with 1 title",
        "[Plex] Added Esses - created in Extra movies with 1 title",
    ]
    assert again.lines == [
        "[Plex] Unchanged Esses - holds the same 1 title in Movies",
        "[Plex] Unchanged Esses - holds the same 1 title in Extra movies",
    ]
    assert unticked.lines == [
        (
            "[Plex] Removed Esses - deleted from Extra movies: "
            "the collection no longer spans that library"
        ),
        "[Plex] Unchanged Esses - holds the same 1 title in Movies",
    ]


def test_a_library_filter_asks_no_more_than_one_group_of_conditions_holds() -> None:
    """It is tested as one group, so a longer list is refused as the request."""
    condition = FieldCondition(field=FilterField.HDR, value=False)
    LibraryFilterMatchRequest(
        media_type=MediaType.SHOW, conditions=[condition] * GROUP_CONDITIONS_MAX
    )
    with pytest.raises(ValidationError):
        LibraryFilterMatchRequest(
            media_type=MediaType.SHOW,
            conditions=[condition] * (GROUP_CONDITIONS_MAX + 1),
        )
