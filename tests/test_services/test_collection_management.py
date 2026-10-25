"""Collection lifecycle and rule runs against the real database."""

lazy from collections.abc import Sequence
lazy from dataclasses import dataclass, field
lazy from typing import ClassVar, override

lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.art_slots import select_art
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import PublicDatasetCollection
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    CollectionFiltering,
    CollectionKind,
    CollectionMode,
    CollectionOrder,
    FilterField,
    FilterOperator,
    MediaType,
    ServerType,
    SmartSortOrder,
    SyncMode,
    TmdbPersonRole,
)
lazy from overture.integrations.arr import ArrClient, ArrTag, ArrTagMatches
lazy from overture.integrations.mdblist import MDBListClient
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import (
    TMDBClient,
    TmdbCollection,
    TmdbPerson,
    TmdbTitle,
)
lazy from overture.media_servers.adapters import ServerCollection, ServerSection
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.plex.provider import PlexProvider
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.schemas.art import ArtCandidate, ArtSourcesResponse, SaveArtRequest
lazy from overture.schemas.collections import (
    BulkCollectionOperation,
    CollectionCreate,
    CollectionGroupPolicy,
    CollectionMembersUpdate,
    CollectionOptions,
    CollectionRuleWrite,
    DynamicTmdbGroupConfig,
    FilterCondition,
    FilterGroup,
    LibraryFilterBuilder,
    MdblistBuilder,
    RadarrTagBuilder,
    SmartCollectionConfig,
    SonarrTagBuilder,
    TmdbCollectionBuilder,
    TmdbItemBuilder,
    TmdbPersonBuilder,
)
lazy from overture.schemas.common import Status, StatusResponse
lazy from overture.services.art.service import ArtService
lazy from overture.services.collections.service import CollectionsService
lazy from overture.services.scheduler import SchedulerService
lazy from overture.utils.errors import PublicServiceError
lazy from tests.bulk_helpers import enable_public_dataset
lazy from tests.runtime_helpers import NoopProviderRegistry, unused
lazy from tests.test_services.test_collections_service import (
    FakeDownloads,
    FakePublisher,
)


class Provider(PlexProvider):
    def __init__(self, app_config: Settings) -> None:
        super().__init__(app_config=app_config)
        self.created: list[str] = []
        self.deleted: list[str] = []
        self.members: dict[str, list[str]] = {}
        self.options: dict[str, tuple[str, CollectionMode, CollectionOrder, bool]] = {}
        self.sort_titles: dict[str, str | None] = {}
        self.summaries: dict[str, str | None] = {}
        self.smart_filters: dict[str, str] = {}
        self.synced_labels: list[tuple[str, list[str], list[str]]] = []
        self.fail = False

    @override
    async def _list_sections(self) -> list[ServerSection]:
        return [
            ServerSection("movies", "Movies", MediaType.MOVIE),
            ServerSection("shows", "Shows", MediaType.SHOW),
        ]

    @override
    async def create_collection(
        self, section_key: str, title: str, media_type: MediaType, member_ids: list[str]
    ) -> ServerCollection:
        if self.fail:
            raise MediaServerError("Create failed")
        self.created.append(title)
        identity = str(len(self.created))
        self.members[identity] = member_ids
        return ServerCollection(
            identity,
            title,
            tuple(member_ids),
            "https://server.test/collection",
            media_type=media_type,
            library_id=section_key,
        )

    @override
    async def create_smart_collection(
        self, section_key: str, title: str, media_type: MediaType, filter_query: str
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
            "https://server.test/collection",
            media_type=media_type,
            library_id=section_key,
            smart=True,
        )

    @override
    async def update_smart_collection_filter(
        self,
        server_collection_id: str,
        section_key: str,
        media_type: MediaType,
        filter_query: str,
    ) -> None:
        self.smart_filters[server_collection_id] = filter_query

    @override
    async def sync_item_labels(
        self,
        section_key: str,
        media_type: MediaType,
        label: str,
        *,
        add_ids: list[str],
        remove_ids: list[str],
    ) -> None:
        self.synced_labels.append((label, add_ids, remove_ids))

    @override
    async def update_collection_details(
        self,
        server_collection_id: str,
        *,
        title: str,
        summary: str | None,
        sort_title: str | None,
        mode: CollectionMode,
        order: CollectionOrder,
        visible_home: bool,
        visible_shared: bool = False,
        visible_library: bool = False,
        filtering: CollectionFiltering | None = None,
    ) -> None:
        self.options[server_collection_id] = title, mode, order, visible_home
        self.sort_titles[server_collection_id] = sort_title
        self.summaries[server_collection_id] = summary

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
    ) -> list[str]:
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
        self.members[server_collection_id] = server_item_ids
        return server_item_ids

    @override
    async def delete_collection(self, server_collection_id: str) -> None:
        self.deleted.append(server_collection_id)


class JellyfinProvider(Provider):
    server_type: ClassVar[ServerType] = ServerType.JELLYFIN


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
    async def close(self) -> None:
        self.closed = True


class Tmdb(TMDBClient):
    def __init__(self) -> None:
        self.found = True
        self.error: Exception | None = None

    @override
    async def get_collection(self, collection_id: int) -> TmdbCollection | None:
        if self.error is not None:
            raise self.error
        if not self.found:
            return None
        return TmdbCollection(
            collection_id,
            "Saga",
            "Collection overview",
            (
                TmdbTitle(12, "Second", 2005, "2005-01-01", None),
                TmdbTitle(11, "First", 1995, "1995-01-01", None),
            ),
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


class Art(ArtService):
    def __init__(self) -> None:
        self.selections: list[ArtType] = []
        self.fail = False

    @override
    async def get_collection_sources(
        self, collection_id: int, media_type: MediaType, art_type: ArtType
    ) -> ArtSourcesResponse:
        if self.fail:
            raise PublicServiceError(502, "Artwork source unavailable")
        return ArtSourcesResponse(
            sources={"tmdb": [ArtCandidate(url="https://example.test/poster.jpg")]}
        )

    @override
    async def save_collection(
        self,
        collection_id: int,
        media_type: MediaType,
        art_type: ArtType,
        body: SaveArtRequest,
    ) -> StatusResponse:
        self.selections.append(art_type)
        return StatusResponse(status=Status.OK)


class FakeArrClient(ArrClient):
    def __init__(self, tag_id: int, label: str) -> None:
        self._tag = ArrTag(id=tag_id, label=label)
        self.closed = False

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
    ids: list[int] = field(default_factory=list[int])


@pytest.fixture
async def manager(database: Database, app_config: Settings) -> Manager:
    provider = Provider(app_config)
    lists = Lists()
    tmdb = Tmdb()
    publisher = FakePublisher()
    art = Art()
    downloads = FakeDownloads()
    async with database.write_session() as session:
        items = [
            MediaItem(
                media_type=MediaType.MOVIE,
                title=title,
                year=year,
                tmdb_id=11 + index,
                server_item_id=f"m{index}",
                library_id="movies",
                studio="Studio",
                genres=["Action"],
                tmdb_collection_id=10,
            )
            for index, (title, year) in enumerate(
                (("First", 1995), ("Second", 2005), ("Manual", 2006))
            )
        ]
        session.add_all(items)
        session.add(
            MediaItem(
                media_type=MediaType.SHOW,
                title="Anime Series",
                year=2020,
                tmdb_id=11,
                server_item_id="s1",
                library_id="shows",
                studio="Studio",
                genres=["Animation"],
            )
        )
        await session.flush()
        ids = [item.id or 0 for item in items]
    service = CollectionsService(
        database=database,
        provider_registry=NoopProviderRegistry(provider),
        publisher=publisher,
        downloads=downloads,
        proxy_clients=unused(ProxyClientManager),
        app_config=app_config,
        tmdb=tmdb,
        mdblist=lists,
        scheduler=SchedulerService(app_config=app_config),
        art=art,
        radarr=FakeArrClient(1, "4k"),
        sonarr=FakeArrClient(2, "anime"),
    )
    return Manager(service, provider, lists, tmdb, publisher, art, downloads, ids)


async def create(manager: Manager, ids: list[int] | None = None) -> int:
    result = await manager.service.create(
        CollectionCreate(
            title="Saga",
            media_type=MediaType.MOVIE,
            library_id="movies",
            member_ids=manager.ids if ids is None else ids,
        )
    )
    return result.id


def make_jellyfin_service(
    manager: Manager, app_config: Settings, database: Database
) -> CollectionsService:
    provider = JellyfinProvider(app_config)
    return CollectionsService(
        database=database,
        provider_registry=NoopProviderRegistry(provider),
        publisher=manager.publisher,
        downloads=manager.downloads,
        proxy_clients=unused(ProxyClientManager),
        app_config=app_config,
        tmdb=manager.tmdb,
        mdblist=manager.lists,
        scheduler=SchedulerService(app_config=app_config),
        art=manager.art,
        radarr=FakeArrClient(1, "4k"),
        sonarr=FakeArrClient(2, "anime"),
    )


async def test_create_edit_order_and_delete_preserve_media(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    detail = await manager.service.update(
        identity,
        MediaType.MOVIE,
        CollectionOptions(
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
    detail = await manager.service.set_members(
        identity,
        MediaType.MOVIE,
        CollectionMembersUpdate(
            member_ids=list(reversed(manager.ids)), order_type=CollectionOrder.CUSTOM
        ),
    )
    assert [member.id for member in detail.members] == list(reversed(manager.ids))
    assert manager.provider.members["1"] == ["m2", "m1", "m0"]
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(builders=[TmdbCollectionBuilder(collection_id=10)]),
    )
    async with database.write_session() as session:
        row = await session.get(MediaCollection, identity)
        assert row is not None
        select_art(row, ArtType.POSTER, "https://example.test/poster.jpg")
        session.add(row)
    await manager.service.delete(identity, MediaType.MOVIE)
    assert manager.provider.deleted == ["1"]
    async with database.read_session() as session:
        assert await session.get(MediaCollection, identity) is None
        assert await CollectionRepository(session).rule(identity) is None
        assert (
            len(
                await CollectionRepository(session).library_items(
                    MediaType.MOVIE, "movies"
                )
            )
            == 3
        )
    assert manager.publisher.broadcasts[-1][0] == "collections.changed"


@pytest.mark.parametrize("ids", [[999], [1, 1]])
async def test_invalid_members_never_reach_the_server(
    manager: Manager, ids: list[int]
) -> None:
    with pytest.raises(PublicServiceError, match="distinct active"):
        await manager.service.create(
            CollectionCreate(
                title="Invalid",
                library_id="movies",
                media_type=MediaType.MOVIE,
                member_ids=ids,
            )
        )
    assert manager.provider.created == []


async def test_create_validates_library_and_duplicate_titles(manager: Manager) -> None:
    with pytest.raises(PublicServiceError, match="Select a library"):
        await manager.service.create(
            CollectionCreate(
                title="Saga",
                library_id="other",
                media_type=MediaType.MOVIE,
                member_ids=manager.ids,
            )
        )
    await create(manager)
    with pytest.raises(PublicServiceError, match="already exists"):
        await create(manager)
    assert manager.provider.created == ["Saga"]


async def test_failed_server_membership_keeps_committed_members(
    manager: Manager,
) -> None:
    identity = await create(manager)
    manager.provider.fail = True
    with pytest.raises(MediaServerError):
        await manager.service.set_members(
            identity,
            MediaType.MOVIE,
            CollectionMembersUpdate(
                member_ids=[manager.ids[0]], order_type=CollectionOrder.RELEASE
            ),
        )
    detail = await manager.service.get_collection(identity, MediaType.MOVIE)
    assert len(detail.members) == 3


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
        session.add(AppSettings(collection_sync_mode=global_mode))
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(
            builders=[MdblistBuilder(identifiers=["person/list"])],
            sync_mode=override,
        ),
    )
    result = await manager.service.sync_rule(identity, MediaType.MOVIE)
    detail = await manager.service.get_collection(identity, MediaType.MOVIE)
    assert len(detail.members) == expected
    assert result.removed == 3 - expected
    assert detail.rule is not None
    assert detail.rule.last_synced_at is not None
    assert manager.provider.members["1"] == (
        ["m1", "m0"] if expected == 2 else ["m1", "m0", "m2"]
    )


@pytest.mark.parametrize("delete", [False, True])
async def test_below_minimum_keeps_or_deletes_collection(
    manager: Manager, database: Database, *, delete: bool
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        session.add(
            AppSettings(
                collection_minimum_items=3, collection_delete_below_minimum=delete
            )
        )
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(builders=[MdblistBuilder(identifiers=["42"])]),
    )
    result = await manager.service.sync_rule(identity, MediaType.MOVIE)
    assert result.deleted is delete
    assert result.skipped is not delete
    if not delete:
        assert (
            len(
                (
                    await manager.service.get_collection(identity, MediaType.MOVIE)
                ).members
            )
            == 3
        )


async def test_failed_source_preserves_members_and_records_safe_error(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(builders=[MdblistBuilder(identifiers=["42"])]),
    )
    manager.lists.failure = True
    with pytest.raises(PublicServiceError, match="Source unavailable"):
        await manager.service.sync_rule(identity, MediaType.MOVIE)
    detail = await manager.service.get_collection(identity, MediaType.MOVIE)
    assert len(detail.members) == 3
    assert detail.rule
    assert detail.rule.last_error == "Source unavailable"


async def test_tmdb_and_intersected_filters_resolve_only_library_members(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(builders=[TmdbCollectionBuilder(collection_id=10)]),
    )
    await manager.service.sync_rule(identity, MediaType.MOVIE)
    assert manager.provider.members["1"] == ["m0", "m1"]
    manager.tmdb.found = False
    with pytest.raises(PublicServiceError, match="membership was kept"):
        await manager.service.sync_rule(identity, MediaType.MOVIE)
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(
            builders=[
                LibraryFilterBuilder(
                    filter_group=FilterGroup(
                        mode="all",
                        conditions=[
                            FilterCondition(
                                field=FilterField.DECADE,
                                operator=FilterOperator.IS,
                                value=2000,
                            ),
                            FilterCondition(
                                field=FilterField.STUDIO,
                                operator=FilterOperator.IS,
                                value="studio",
                            ),
                            FilterCondition(
                                field=FilterField.GENRE,
                                operator=FilterOperator.IS,
                                value="action",
                            ),
                        ],
                    )
                )
            ]
        ),
    )
    await manager.service.sync_rule(identity, MediaType.MOVIE)
    assert manager.provider.members["1"] == ["m1", "m2"]
    await manager.service.delete_rule(identity, MediaType.MOVIE)
    assert (
        await manager.service.get_collection(identity, MediaType.MOVIE)
    ).rule is None
    with pytest.raises(PublicServiceError, match="no dynamic rule"):
        await manager.service.sync_rule(identity, MediaType.MOVIE)


async def test_scheduler_honors_due_times_and_stops_its_client(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(builders=[MdblistBuilder(identifiers=["42"])]),
    )
    await manager.service.start()
    await manager.service.sync_due()
    count = len(manager.publisher.broadcasts)
    await manager.service.sync_due()
    assert len(manager.publisher.broadcasts) == count
    await manager.service.stop()
    assert manager.lists.closed


async def test_rule_sync_uses_shared_automatic_art_and_theme_pipelines(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        session.add(
            AppSettings(
                collection_auto_match_art=True, collection_auto_match_theme=True
            )
        )
        session.add(
            PublicDatasetCollection(
                tmdb_id=10, title="Saga", youtube_id_overturedb="a" * 11
            )
        )
    async with database.write_session() as session:
        await enable_public_dataset(session)
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(builders=[TmdbCollectionBuilder(collection_id=10)]),
    )
    await manager.service.sync_rule(identity, MediaType.MOVIE)
    assert manager.art.selections == [ArtType.POSTER, ArtType.BACKGROUND]
    assert manager.downloads.targets[0].collection_id == identity


async def test_auto_asset_failure_keeps_synced_members_and_records_the_failure(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        session.add(AppSettings(collection_auto_match_art=True))
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(builders=[TmdbCollectionBuilder(collection_id=10)]),
    )
    manager.art.fail = True
    with pytest.raises(
        PublicServiceError, match="Members synced; automatic assets failed"
    ):
        await manager.service.sync_rule(identity, MediaType.MOVIE)
    detail = await manager.service.get_collection(identity, MediaType.MOVIE)
    assert len(detail.members) == 2
    assert detail.rule is not None
    assert detail.rule.last_error is not None
    assert "Artwork source unavailable" in detail.rule.last_error


async def test_append_keeps_new_server_members_and_counts_them_for_minimum(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager, manager.ids[:2])
    manager.provider.members["1"].extend(["m2", "unimported"])
    async with database.write_session() as session:
        session.add(
            AppSettings(
                collection_minimum_items=4, collection_delete_below_minimum=True
            )
        )
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(
            builders=[MdblistBuilder(identifiers=["42"])],
            sync_mode=SyncMode.APPEND,
        ),
    )
    result = await manager.service.sync_rule(identity, MediaType.MOVIE)
    assert not result.skipped
    assert not result.deleted
    assert manager.provider.members["1"] == ["m1", "m0", "m2", "unimported"]
    detail = await manager.service.get_collection(identity, MediaType.MOVIE)
    assert detail.child_count == 4
    assert len(detail.members) == 3


async def test_append_does_not_restore_a_manual_member_removed_on_the_server(
    manager: Manager,
) -> None:
    identity = await create(manager)
    manager.provider.members["1"] = ["m0", "m1"]
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(
            builders=[MdblistBuilder(identifiers=["42"])],
            sync_mode=SyncMode.APPEND,
        ),
    )
    await manager.service.sync_rule(identity, MediaType.MOVIE)
    assert manager.provider.members["1"] == ["m1", "m0"]
    assert (
        await manager.service.get_collection(identity, MediaType.MOVIE)
    ).child_count == 2


async def test_custom_group_round_trips_and_joins_group_choices(
    manager: Manager,
) -> None:
    identity = await create(manager)
    detail = await manager.service.update(
        identity,
        MediaType.MOVIE,
        CollectionOptions(title="Saga", collection_group="  Weekend  "),
    )
    assert detail.collection_group == "Weekend"
    groups = await manager.service.groups(MediaType.MOVIE)
    assert set(groups) == {"Weekend"}
    listed = await manager.service.list_collections(MediaType.MOVIE)
    assert listed[0].collection_group == "Weekend"
    detail = await manager.service.update(
        identity,
        MediaType.MOVIE,
        CollectionOptions(title="Saga", collection_group=" "),
    )
    assert detail.collection_group is None


async def test_explicit_identity_survives_membership_changes(manager: Manager) -> None:
    identity = await create(manager)
    detail = await manager.service.get_collection(identity, MediaType.MOVIE)
    assert detail.tmdb_collection_id is None
    await manager.service.update(
        identity,
        MediaType.MOVIE,
        CollectionOptions(title="Saga", tmdb_collection_id=99),
    )
    detail = await manager.service.set_members(
        identity,
        MediaType.MOVIE,
        CollectionMembersUpdate(
            member_ids=manager.ids, order_type=CollectionOrder.RELEASE
        ),
    )
    assert detail.tmdb_collection_id == 99
    detail = await manager.service.update(
        identity, MediaType.MOVIE, CollectionOptions(title="Renamed")
    )
    assert detail.tmdb_collection_id == 99
    detail = await manager.service.update(
        identity,
        MediaType.MOVIE,
        CollectionOptions(title="Renamed", tmdb_collection_id=None),
    )
    assert detail.tmdb_collection_id is None


async def test_creation_resolves_a_dynamic_rule_and_saves_it_with_identity(
    manager: Manager,
) -> None:
    detail = await manager.service.create(
        CollectionCreate(
            title="Dynamic",
            library_id="movies",
            media_type=MediaType.MOVIE,
            rule=CollectionRuleWrite(
                builders=[TmdbCollectionBuilder(collection_id=10)]
            ),
        )
    )
    assert detail.tmdb_collection_id == 10
    assert [member.tmdb_id for member in detail.members] == [11, 12]
    assert detail.rule is not None
    assert detail.rule.builders == [TmdbCollectionBuilder(collection_id=10)]


async def test_group_defaults_and_explicit_rule_choices_resolve_in_order(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    async with database.write_session() as session:
        session.add(
            AppSettings(
                collection_minimum_items=3,
                collection_delete_below_minimum=True,
                collection_auto_match_art=True,
            )
        )
    policy = CollectionGroupPolicy(
        sync_mode=SyncMode.SYNC,
        minimum_items=2,
        delete_below_minimum=False,
        auto_match_art=False,
        collection_mode=CollectionMode.HIDE,
        sort_title_format="+{group} - {title}",
    )
    await manager.service.save_group_policy(MediaType.MOVIE, "Weekend", policy)
    assert await manager.service.group_policy(MediaType.MOVIE, "Weekend") == policy
    assert (
        await manager.service.group_policy(MediaType.SHOW, "Weekend")
        == CollectionGroupPolicy()
    )
    await manager.service.update(
        identity,
        MediaType.MOVIE,
        CollectionOptions(title="Saga", collection_group="Weekend"),
    )
    assert manager.provider.options["1"][1] is CollectionMode.HIDE
    assert manager.provider.sort_titles["1"] == "+Weekend - Saga"
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(builders=[MdblistBuilder(identifiers=["42"])]),
    )
    await manager.service.sync_rule(identity, MediaType.MOVIE)
    detail = await manager.service.get_collection(identity, MediaType.MOVIE)
    assert len(detail.members) == 2
    assert not detail.below_minimum
    assert manager.art.selections == []
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(
            builders=[MdblistBuilder(identifiers=["42"])],
            minimum_items=3,
            delete_below_minimum=False,
        ),
    )
    result = await manager.service.sync_rule(identity, MediaType.MOVIE)
    assert result.skipped
    assert not result.deleted
    listed = await manager.service.list_collections(MediaType.MOVIE)
    assert listed[0].below_minimum
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(
            builders=[MdblistBuilder(identifiers=["42"])],
            minimum_items=1,
            sync_mode=SyncMode.APPEND,
        ),
    )
    assert (
        await manager.service.get_collection(identity, MediaType.MOVIE)
    ).effective_sync_mode is SyncMode.APPEND


async def test_bulk_operations_commit_successes_and_report_invalid_targets(
    manager: Manager, database: Database
) -> None:
    identity = await create(manager)
    result = await manager.service.bulk_operation(
        BulkCollectionOperation(
            collection_ids=[999, identity],
            media_type=MediaType.MOVIE,
            operation="set_group",
            collection_group=" Weekend ",
        )
    )
    assert result.collection_ids == [identity]
    assert set(result.errors) == {999}
    detail = await manager.service.get_collection(identity, MediaType.MOVIE)
    assert detail.collection_group == "Weekend"
    result = await manager.service.bulk_operation(
        BulkCollectionOperation(
            collection_ids=[identity],
            media_type=MediaType.MOVIE,
            operation="apply_sort_title_format",
            sort_title_format="+{group}: {title}",
        )
    )
    assert result.collection_ids == [identity]
    assert manager.provider.sort_titles["1"] == "+Weekend: Saga"
    result = await manager.service.bulk_operation(
        BulkCollectionOperation(
            collection_ids=[identity],
            media_type=MediaType.MOVIE,
            operation="set_monitored",
            monitored=False,
        )
    )
    assert result.collection_ids == [identity]
    assert not (
        await manager.service.get_collection(identity, MediaType.MOVIE)
    ).monitored
    result = await manager.service.bulk_operation(
        BulkCollectionOperation(
            collection_ids=[identity], media_type=MediaType.MOVIE, operation="delete"
        )
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
    await manager.service.save_group_policy(
        MediaType.MOVIE,
        "Directors",
        CollectionGroupPolicy(summary_format="Famous director. {summary}"),
    )
    detail = await manager.service.create(
        CollectionCreate(
            title="Director Spotlight",
            library_id="movies",
            media_type=MediaType.MOVIE,
            collection_group="Directors",
            order_type=CollectionOrder.CUSTOM,
            rule=CollectionRuleWrite(
                builders=[
                    TmdbPersonBuilder(
                        person_id=500,
                        roles=[TmdbPersonRole.DIRECTOR],
                        use_biography=True,
                    ),
                    TmdbItemBuilder(tmdb_ids=[12]),
                ]
            ),
        )
    )
    assert [m.tmdb_id for m in detail.members] == [11, 13, 12]
    assert detail.summary == "Famous director. Person biography"
    assert manager.provider.summaries["1"] == "Famous director. Person biography"


async def test_smart_collection_with_managed_label_and_filters(
    manager: Manager,
) -> None:
    detail = await manager.service.create(
        CollectionCreate(
            title="Requests",
            library_id="movies",
            media_type=MediaType.MOVIE,
            kind=CollectionKind.SMART,
            collection_filtering=CollectionFiltering.USER,
            rule=CollectionRuleWrite(
                builders=[
                    LibraryFilterBuilder(
                        filter_group=FilterGroup(
                            mode="all",
                            conditions=[
                                FilterCondition(
                                    field=FilterField.YEAR,
                                    operator=FilterOperator.GTE,
                                    value=2000,
                                )
                            ],
                        ),
                    )
                ],
                managed_label="request",
                smart_filter=SmartCollectionConfig(
                    sort_by=SmartSortOrder.ADDED_DESC,
                    filter_group=FilterGroup(
                        mode="all",
                        conditions=[
                            FilterCondition(
                                field=FilterField.LABEL,
                                operator=FilterOperator.IS,
                                value="request",
                            ),
                            FilterCondition(
                                field=FilterField.UNPLAYED,
                                operator=FilterOperator.IS,
                                value=True,
                            ),
                        ],
                    ),
                ),
            ),
        )
    )
    assert detail.kind is CollectionKind.SMART
    assert manager.provider.synced_labels == [("request", ["m1", "m2"], [])]
    assert (
        manager.provider.smart_filters["1"]
        == "sort=addedAt:desc&push=1&label==request&unwatched=1&pop=1"
    )

    # Syncing an existing smart collection updates its filter query and counts
    sync_res = await manager.service.sync_rule(detail.id, MediaType.MOVIE)
    assert sync_res.added == 0


async def test_seasonal_inactive_withholds_and_deletes_server_collection(
    manager: Manager,
) -> None:
    detail = await manager.service.create(
        CollectionCreate(
            title="Holiday",
            library_id="movies",
            media_type=MediaType.MOVIE,
            active_start_mmdd="01-01",
            active_end_mmdd="01-02",
            rule=CollectionRuleWrite(
                builders=[TmdbItemBuilder(tmdb_ids=[11, 12])],
                delete_when_inactive=True,
            ),
        )
    )
    assert detail.withheld
    assert manager.provider.created == []

    # Active collection transitions to inactive and deletes server copy
    active = await manager.service.create(
        CollectionCreate(
            title="Active Seasonal",
            library_id="movies",
            media_type=MediaType.MOVIE,
            active_start_mmdd="01-01",
            active_end_mmdd="12-31",
            rule=CollectionRuleWrite(
                builders=[TmdbItemBuilder(tmdb_ids=[11, 12])],
                delete_when_inactive=True,
            ),
        )
    )
    assert not active.withheld
    assert active.title in manager.provider.created

    await manager.service.update(
        active.id,
        MediaType.MOVIE,
        CollectionOptions(
            title="Active Seasonal",
            active_start_mmdd="01-01",
            active_end_mmdd="01-02",
        ),
    )
    await manager.service.sync_rule(active.id, MediaType.MOVIE)
    refreshed = await manager.service.get_collection(active.id, MediaType.MOVIE)
    assert refreshed.withheld is True
    assert refreshed.child_count == 0


async def test_dynamic_tmdb_group_discovers_and_creates_franchises(
    manager: Manager,
) -> None:
    await manager.service.save_group_policy(
        MediaType.MOVIE,
        "Franchises",
        CollectionGroupPolicy(
            minimum_items=2,
            sort_title_format="+1_{title}",
            dynamic_tmdb=DynamicTmdbGroupConfig(
                enabled=True,
                library_id="movies",
            ),
        ),
    )
    await manager.service.sync_group(MediaType.MOVIE, "Franchises")
    listed = await manager.service.list_collections(MediaType.MOVIE)
    assert len(listed) == 1
    assert listed[0].title == "Saga"
    assert listed[0].collection_group == "Franchises"
    assert listed[0].sort_title == "+1_Saga"


async def test_non_plex_option_validation(
    manager: Manager, app_config: Settings, database: Database
) -> None:
    identity = await create(manager)
    jellyfin_service = make_jellyfin_service(manager, app_config, database)

    with pytest.raises(PublicServiceError, match="Custom member order"):
        await jellyfin_service.set_members(
            identity,
            MediaType.MOVIE,
            CollectionMembersUpdate(member_ids=[1], order_type=CollectionOrder.CUSTOM),
        )

    with pytest.raises(PublicServiceError, match="Smart collections"):
        await jellyfin_service.update(
            identity,
            MediaType.MOVIE,
            CollectionOptions(title="Smart", kind=CollectionKind.SMART),
        )

    with pytest.raises(PublicServiceError, match="Visibility and home promotion"):
        await jellyfin_service.update(
            identity,
            MediaType.MOVIE,
            CollectionOptions(title="Home", visible_home=True),
        )

    with pytest.raises(PublicServiceError, match="Visibility and home promotion"):
        await jellyfin_service.update(
            identity,
            MediaType.MOVIE,
            CollectionOptions(title="Shared", visible_shared=True),
        )

    with pytest.raises(PublicServiceError, match="Visibility and home promotion"):
        await jellyfin_service.update(
            identity,
            MediaType.MOVIE,
            CollectionOptions(title="Lib", visible_library=True),
        )

    with pytest.raises(PublicServiceError, match="Visibility and home promotion"):
        await jellyfin_service.update(
            identity,
            MediaType.MOVIE,
            CollectionOptions(title="Mode", collection_mode=CollectionMode.HIDE),
        )

    with pytest.raises(PublicServiceError, match="Visibility and home promotion"):
        await jellyfin_service.update(
            identity,
            MediaType.MOVIE,
            CollectionOptions(
                title="Filter", collection_filtering=CollectionFiltering.ADMIN
            ),
        )


async def test_rule_media_type_and_provider_validation(
    manager: Manager, app_config: Settings, database: Database
) -> None:
    identity = await create(manager)

    # RadarrTagBuilder on SHOW collections
    with pytest.raises(PublicServiceError, match="only available for movies"):
        await manager.service.save_rule(
            identity,
            MediaType.SHOW,
            CollectionRuleWrite(builders=[RadarrTagBuilder(tags=["4k"])]),
        )

    # TmdbCollectionBuilder on SHOW collections
    with pytest.raises(PublicServiceError, match="only available for movies"):
        await manager.service.save_rule(
            identity,
            MediaType.SHOW,
            CollectionRuleWrite(builders=[TmdbCollectionBuilder(collection_id=10)]),
        )

    # SonarrTagBuilder on MOVIE collections
    with pytest.raises(PublicServiceError, match="only available for TV shows"):
        await manager.service.save_rule(
            identity,
            MediaType.MOVIE,
            CollectionRuleWrite(builders=[SonarrTagBuilder(tags=["anime"])]),
        )

    # Smart filter on non-Plex
    jellyfin_service = make_jellyfin_service(manager, app_config, database)
    with pytest.raises(
        PublicServiceError, match="Smart collections are only supported by Plex"
    ):
        await jellyfin_service.save_rule(
            identity,
            MediaType.MOVIE,
            CollectionRuleWrite(
                builders=[],
                smart_filter=SmartCollectionConfig(
                    filter_group=FilterGroup(
                        conditions=[
                            FilterCondition(
                                field=FilterField.GENRE,
                                operator=FilterOperator.IS,
                                value="Action",
                            )
                        ]
                    )
                ),
            ),
        )


async def test_list_arr_tags(manager: Manager) -> None:
    radarr_tags = await manager.service.list_radarr_tags()
    assert len(radarr_tags) == 1
    assert radarr_tags[0].id == 1
    assert radarr_tags[0].label == "4k"

    sonarr_tags = await manager.service.list_sonarr_tags()
    assert len(sonarr_tags) == 1
    assert sonarr_tags[0].id == 2
    assert sonarr_tags[0].label == "anime"


async def test_formatted_options(manager: Manager) -> None:
    identity = await create(manager)

    # Valid sort_title_format
    updated = await manager.service.update(
        identity,
        MediaType.MOVIE,
        CollectionOptions(
            title="Star Wars",
            collection_group="Sci-Fi",
            sort_title_format="+1_{title}",
        ),
    )
    assert updated.sort_title == "+1_Star Wars"

    # Too long sort_title_format raises PublicServiceError(422)
    with pytest.raises(PublicServiceError):
        await manager.service.update(
            identity,
            MediaType.MOVIE,
            CollectionOptions(
                title="A" * 150,
                collection_group="B" * 60,
                sort_title_format="{title}_{group}",
            ),
        )

    # Valid summary_format
    updated_summary = await manager.service.update(
        identity,
        MediaType.MOVIE,
        CollectionOptions(
            title="Star Wars",
            summary_format="{title} complete saga",
        ),
    )
    assert updated_summary.summary == "Star Wars complete saga"

    # Too long summary_format raises PublicServiceError(422)
    with pytest.raises(PublicServiceError):
        await manager.service.update(
            identity,
            MediaType.MOVIE,
            CollectionOptions(
                title="A" * 200,
                summary_format="X" * 1900 + "{title}",
            ),
        )


async def test_sync_due_runs_due_rules_and_dynamic_tmdb(manager: Manager) -> None:
    # Save a group with dynamic tmdb config
    await manager.service.save_group_policy(
        MediaType.MOVIE,
        "Franchises",
        CollectionGroupPolicy(
            minimum_items=2,
            dynamic_tmdb=DynamicTmdbGroupConfig(
                enabled=True,
                library_id="movies",
            ),
        ),
    )
    # Create a collection with a rule
    created = await manager.service.create(
        CollectionCreate(
            title="Due Collection",
            library_id="movies",
            media_type=MediaType.MOVIE,
            rule=CollectionRuleWrite(
                builders=[TmdbItemBuilder(tmdb_ids=[11, 12])],
                sync_interval_hours=1,
            ),
        )
    )
    # Run sync_due
    await manager.service.sync_due()
    detail = await manager.service.get_collection(created.id, MediaType.MOVIE)
    assert detail.rule is not None
    assert detail.rule.last_synced_at is not None

    # Running sync_due again immediately skips rule because it's not due yet
    await manager.service.sync_due()


async def test_radarr_and_sonarr_tag_builder_sync(manager: Manager) -> None:
    # RadarrTagBuilder sync
    radarr_col = await manager.service.create(
        CollectionCreate(
            title="4K Movies",
            library_id="movies",
            media_type=MediaType.MOVIE,
            rule=CollectionRuleWrite(
                builders=[RadarrTagBuilder(tags=["4k"])],
            ),
        )
    )
    assert radarr_col.child_count == 2
    res = await manager.service.sync_rule(radarr_col.id, MediaType.MOVIE)
    assert res.added == 0

    # SonarrTagBuilder sync
    sonarr_col = await manager.service.create(
        CollectionCreate(
            title="Anime Shows",
            library_id="shows",
            media_type=MediaType.SHOW,
            rule=CollectionRuleWrite(
                builders=[SonarrTagBuilder(tags=["anime"])],
                minimum_items=1,
            ),
        )
    )
    assert sonarr_col.child_count == 1
    show_res = await manager.service.sync_rule(sonarr_col.id, MediaType.SHOW)
    assert show_res.added == 0


async def test_create_collection_custom_order(manager: Manager) -> None:
    col = await manager.service.create(
        CollectionCreate(
            title="Custom Order",
            library_id="movies",
            media_type=MediaType.MOVIE,
            order_type=CollectionOrder.CUSTOM,
            member_ids=manager.ids,
        )
    )
    assert col.order_type is CollectionOrder.CUSTOM


async def test_delete_rule_preserves_collection(manager: Manager) -> None:
    col = await manager.service.create(
        CollectionCreate(
            title="Rule To Delete",
            library_id="movies",
            media_type=MediaType.MOVIE,
            rule=CollectionRuleWrite(
                builders=[TmdbItemBuilder(tmdb_ids=[11, 12])],
            ),
        )
    )
    assert (
        await manager.service.delete_rule(col.id, MediaType.MOVIE)
    ).status == Status.DELETED
    detail = await manager.service.get_collection(col.id, MediaType.MOVIE)
    assert detail.rule is None


async def test_seasonal_smart_collection_sync_creates_server_copy(
    manager: Manager,
) -> None:
    # Inactive smart collection starts withheld with no server_item_id
    detail = await manager.service.create(
        CollectionCreate(
            title="Seasonal Smart",
            library_id="movies",
            media_type=MediaType.MOVIE,
            active_start_mmdd="01-01",
            active_end_mmdd="01-02",
            rule=CollectionRuleWrite(
                builders=[],
                delete_when_inactive=True,
                smart_filter=SmartCollectionConfig(
                    filter_group=FilterGroup(
                        conditions=[
                            FilterCondition(
                                field=FilterField.GENRE,
                                operator=FilterOperator.IS,
                                value="Action",
                            )
                        ]
                    )
                ),
            ),
        )
    )
    assert detail.withheld

    # Make it active and sync, which invokes create_smart_collection
    await manager.service.update(
        detail.id,
        MediaType.MOVIE,
        CollectionOptions(
            title="Seasonal Smart",
            active_start_mmdd="01-01",
            active_end_mmdd="12-31",
        ),
    )
    res = await manager.service.sync_rule(detail.id, MediaType.MOVIE)
    assert res.skipped is False
    refreshed = await manager.service.get_collection(detail.id, MediaType.MOVIE)
    assert not refreshed.withheld


async def test_inherited_format_overflow_raises_422(manager: Manager) -> None:
    await manager.service.save_group_policy(
        MediaType.MOVIE,
        "LongGroup",
        CollectionGroupPolicy(
            sort_title_format="Prefix_" + ("A" * 60) + "_{title}",
            summary_format="SummaryPrefix_" + ("B" * 50) + "_{summary}",
        ),
    )
    with pytest.raises(PublicServiceError, match="at most 200 characters"):
        await manager.service.create(
            CollectionCreate(
                title="T" * 150,
                collection_group="LongGroup",
                library_id="movies",
                media_type=MediaType.MOVIE,
            )
        )
    with pytest.raises(PublicServiceError, match="at most 2000 characters"):
        await manager.service.create(
            CollectionCreate(
                title="Normal",
                summary="S" * 1960,
                collection_group="LongGroup",
                library_id="movies",
                media_type=MediaType.MOVIE,
            )
        )


async def test_smart_collection_requires_filter(manager: Manager) -> None:
    with pytest.raises(
        PublicServiceError, match="Smart collections require a smart filter"
    ):
        await manager.service.create(
            CollectionCreate(
                title="Smart No Filter",
                library_id="movies",
                media_type=MediaType.MOVIE,
                kind=CollectionKind.SMART,
            )
        )


async def test_set_members_on_smart_collection_raises_422(manager: Manager) -> None:
    detail = await manager.service.create(
        CollectionCreate(
            title="Smart Collection",
            library_id="movies",
            media_type=MediaType.MOVIE,
            kind=CollectionKind.SMART,
            rule=CollectionRuleWrite(
                builders=[],
                smart_filter=SmartCollectionConfig(
                    filter_group=FilterGroup(
                        conditions=[
                            FilterCondition(
                                field=FilterField.GENRE,
                                operator=FilterOperator.IS,
                                value="Comedy",
                            )
                        ]
                    )
                ),
            ),
        )
    )
    with pytest.raises(PublicServiceError, match="controlled by their filter"):
        await manager.service.set_members(
            detail.id,
            MediaType.MOVIE,
            CollectionMembersUpdate(
                member_ids=[1],
                order_type=CollectionOrder.RELEASE,
            ),
        )


async def test_group_policy_validation_errors(
    manager: Manager, app_config: Settings, database: Database
) -> None:
    with pytest.raises(PublicServiceError, match="A group needs a name"):
        await manager.service.save_group_policy(
            MediaType.MOVIE, "   ", CollectionGroupPolicy()
        )
    with pytest.raises(PublicServiceError, match="only available for movies"):
        await manager.service.save_group_policy(
            MediaType.SHOW,
            "ShowFranchises",
            CollectionGroupPolicy(
                dynamic_tmdb=DynamicTmdbGroupConfig(enabled=True, library_id="shows")
            ),
        )
    jellyfin_service = make_jellyfin_service(manager, app_config, database)
    with pytest.raises(PublicServiceError, match="Collection visibility requires Plex"):
        await jellyfin_service.save_group_policy(
            MediaType.MOVIE,
            "NonPlexGroup",
            CollectionGroupPolicy(visible_home=True),
        )


async def test_sync_due_dynamic_tmdb_discovery_failure(manager: Manager) -> None:
    await manager.service.save_group_policy(
        MediaType.MOVIE,
        "FaultyFranchises",
        CollectionGroupPolicy(
            dynamic_tmdb=DynamicTmdbGroupConfig(enabled=True, library_id="movies"),
        ),
    )
    manager.tmdb.error = RuntimeError("TMDB upstream connection reset")
    # sync_due handles discovery exceptions per-group and logs warnings
    await manager.service.sync_due()


async def test_dynamic_tmdb_exclusions_from_existing_collections(
    manager: Manager,
) -> None:
    other = await manager.service.create(
        CollectionCreate(
            title="External Franchise",
            library_id="movies",
            media_type=MediaType.MOVIE,
            collection_group="OtherGroup",
            tmdb_collection_id=1,
            rule=CollectionRuleWrite(
                builders=[TmdbCollectionBuilder(collection_id=1)],
            ),
        )
    )
    await manager.service.save_group_policy(
        MediaType.MOVIE,
        "AutoExcludedGroup",
        CollectionGroupPolicy(
            minimum_items=1,
            dynamic_tmdb=DynamicTmdbGroupConfig(
                enabled=True,
                library_id="movies",
                auto_exclude_from_other_collections=True,
                exclude_tmdb_ids=[999],
            ),
        ),
    )
    res = await manager.service.sync_group(MediaType.MOVIE, "AutoExcludedGroup")
    assert other.id not in res.created


async def test_bulk_operation_trigger_sync(manager: Manager) -> None:
    col = await manager.service.create(
        CollectionCreate(
            title="Bulk Target",
            library_id="movies",
            media_type=MediaType.MOVIE,
            rule=CollectionRuleWrite(builders=[TmdbItemBuilder(tmdb_ids=[11])]),
        )
    )
    res = await manager.service.bulk_operation(
        BulkCollectionOperation(
            operation="trigger_sync",
            collection_ids=[col.id],
            media_type=MediaType.MOVIE,
        )
    )
    assert res.collection_ids == [col.id]
    assert res.errors == {}
    refreshed = await manager.service.get_collection(col.id, MediaType.MOVIE)
    assert refreshed.rule is not None
    assert refreshed.rule.last_synced_at is not None


async def test_get_collection_theme_status(manager: Manager) -> None:
    col = await manager.service.create(
        CollectionCreate(
            title="Theme Target",
            library_id="movies",
            media_type=MediaType.MOVIE,
            member_ids=manager.ids,
        )
    )
    theme = await manager.service.get_collection_theme(col.id, MediaType.MOVIE)
    assert theme.has_theme is False


async def test_sync_group_records_rule_errors(manager: Manager) -> None:
    await manager.service.create(
        CollectionCreate(
            title="Will Fail",
            library_id="movies",
            media_type=MediaType.MOVIE,
            collection_group="ErrorGroup",
            member_ids=manager.ids,
            rule=CollectionRuleWrite(builders=[MdblistBuilder(identifiers=["1234"])]),
        )
    )
    manager.lists.failure = True
    res = await manager.service.sync_group(MediaType.MOVIE, "ErrorGroup")
    assert "Will Fail" in res.errors


async def test_create_collection_below_minimum_raises_422(manager: Manager) -> None:
    with pytest.raises(
        PublicServiceError, match="fewer members than the effective minimum"
    ):
        await manager.service.create(
            CollectionCreate(
                title="Empty",
                library_id="movies",
                media_type=MediaType.MOVIE,
                member_ids=[],
            )
        )


async def test_save_rule_converts_collection_to_smart_kind(manager: Manager) -> None:
    col = await manager.service.create(
        CollectionCreate(
            title="Convert To Smart",
            library_id="movies",
            media_type=MediaType.MOVIE,
            member_ids=manager.ids,
        )
    )
    assert col.kind is CollectionKind.REGULAR

    await manager.service.save_rule(
        col.id,
        MediaType.MOVIE,
        CollectionRuleWrite(
            builders=[],
            smart_filter=SmartCollectionConfig(
                filter_group=FilterGroup(
                    conditions=[
                        FilterCondition(
                            field=FilterField.GENRE,
                            operator=FilterOperator.IS,
                            value="Drama",
                        )
                    ]
                )
            ),
        ),
    )
    refreshed = await manager.service.get_collection(col.id, MediaType.MOVIE)
    assert refreshed.kind is CollectionKind.SMART


async def test_standard_collection_sync_with_managed_label(manager: Manager) -> None:
    col = await manager.service.create(
        CollectionCreate(
            title="Labeled Standard",
            library_id="movies",
            media_type=MediaType.MOVIE,
            member_ids=manager.ids,
            rule=CollectionRuleWrite(
                builders=[TmdbItemBuilder(tmdb_ids=[11])],
                managed_label="classic",
            ),
        )
    )
    res = await manager.service.sync_rule(col.id, MediaType.MOVIE)
    assert res.skipped is False
    assert any(label == "classic" for label, _, _ in manager.provider.synced_labels)


async def test_scheduled_sync_rule_skips_when_not_due(manager: Manager) -> None:
    col = await manager.service.create(
        CollectionCreate(
            title="Scheduled Skip",
            library_id="movies",
            media_type=MediaType.MOVIE,
            member_ids=manager.ids,
            rule=CollectionRuleWrite(
                builders=[TmdbItemBuilder(tmdb_ids=[11])],
            ),
        )
    )
    # First sync runs
    first = await manager.service.sync_rule(col.id, MediaType.MOVIE, scheduled=False)
    assert first.skipped is False

    # Second scheduled sync skips because not enough time elapsed
    second = await manager.service.sync_rule(col.id, MediaType.MOVIE, scheduled=True)
    assert second.skipped is True


async def test_inactive_rule_without_delete_skips_sync(manager: Manager) -> None:
    col = await manager.service.create(
        CollectionCreate(
            title="Inactive Seasonal",
            library_id="movies",
            media_type=MediaType.MOVIE,
            member_ids=manager.ids,
            active_start_mmdd="01-01",
            active_end_mmdd="01-02",
            rule=CollectionRuleWrite(
                builders=[TmdbItemBuilder(tmdb_ids=[11])],
                delete_when_inactive=False,
            ),
        )
    )
    res = await manager.service.sync_rule(col.id, MediaType.MOVIE)
    assert res.skipped is True


async def test_bulk_operations_order_and_visibility(manager: Manager) -> None:
    col = await manager.service.create(
        CollectionCreate(
            title="Bulk Config",
            library_id="movies",
            media_type=MediaType.MOVIE,
            member_ids=manager.ids,
        )
    )
    # set_order
    res_order = await manager.service.bulk_operation(
        BulkCollectionOperation(
            operation="set_order",
            collection_ids=[col.id],
            media_type=MediaType.MOVIE,
            order_type=CollectionOrder.RELEASE,
        )
    )
    assert res_order.collection_ids == [col.id]

    # set_visibility
    res_vis = await manager.service.bulk_operation(
        BulkCollectionOperation(
            operation="set_visibility",
            collection_ids=[col.id],
            media_type=MediaType.MOVIE,
            collection_mode=CollectionMode.HIDE,
            visible_home=True,
            visible_shared=True,
            visible_library=True,
        )
    )
    assert res_vis.collection_ids == [col.id]
    refreshed = await manager.service.get_collection(col.id, MediaType.MOVIE)
    assert refreshed.order_type is CollectionOrder.RELEASE
    assert refreshed.collection_mode is CollectionMode.HIDE
    assert refreshed.visible_home is True
    assert refreshed.visible_shared is True
    assert refreshed.visible_library is True
