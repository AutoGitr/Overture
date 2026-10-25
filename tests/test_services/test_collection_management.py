"""Collection lifecycle and rule runs against the real database."""

lazy from dataclasses import dataclass, field
lazy from typing import override

lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.art_slots import select_art
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import PublicDatasetCollection
lazy from overture.db.models.settings import AppSettings, get_app_settings
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    CollectionMode,
    CollectionOrder,
    CollectionPreset,
    MediaType,
    RuleSourceType,
    SyncMode,
)
lazy from overture.integrations.mdblist import MDBListClient
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import TMDBClient, TmdbCollection, TmdbTitle
lazy from overture.media_servers.adapters import ServerCollection, ServerSection
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.plex.provider import PlexProvider
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.schemas.art import ArtCandidate, ArtSourcesResponse, SaveArtRequest
lazy from overture.schemas.collections import (
    BulkCollectionOperation,
    CollectionCreate,
    CollectionFilter,
    CollectionGenerateRequest,
    CollectionGroupPolicy,
    CollectionMembersUpdate,
    CollectionOptions,
    CollectionRuleWrite,
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
        self.fail = False

    @override
    async def _list_sections(self) -> list[ServerSection]:
        return [ServerSection("movies", "Movies", MediaType.MOVIE)]

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
    ) -> None:
        self.options[server_collection_id] = title, mode, order, visible_home
        self.sort_titles[server_collection_id] = sort_title

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

    @override
    async def get_collection(self, collection_id: int) -> TmdbCollection | None:
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
        )


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
        CollectionRuleWrite(source_type=RuleSourceType.TMDB, source_identifier="10"),
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
            source_type=RuleSourceType.MDBLIST,
            source_identifier="person/list",
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
        CollectionRuleWrite(source_type=RuleSourceType.MDBLIST, source_identifier="42"),
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
        CollectionRuleWrite(source_type=RuleSourceType.MDBLIST, source_identifier="42"),
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
        CollectionRuleWrite(source_type=RuleSourceType.TMDB, source_identifier="10"),
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
            source_type=RuleSourceType.FILTER,
            filters=CollectionFilter(decade=2000, studio="studio", genre="action"),
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


@pytest.mark.parametrize(
    ("preset", "titles"),
    [
        (CollectionPreset.DECADES, ["1990s", "2000s"]),
        (CollectionPreset.GENRES, ["Action"]),
        (CollectionPreset.STUDIOS, ["Studio"]),
        (CollectionPreset.TMDB_COLLECTIONS, ["Saga"]),
    ],
)
async def test_presets_preview_and_generate_persistent_rules(
    manager: Manager, preset: CollectionPreset, titles: list[str]
) -> None:
    body = CollectionGenerateRequest(
        media_type=MediaType.MOVIE, library_id="movies", preset=preset
    )
    preview = await manager.service.presets(body)
    assert [option.title for option in preview] == titles
    body.titles = titles
    result = await manager.service.generate(body)
    assert len(result.created) == len(titles)
    assert not result.errors
    assert await manager.service.presets(body) == []
    for identity in result.created:
        detail = await manager.service.get_collection(identity, MediaType.MOVIE)
        assert detail.rule
        assert detail.collection_group == preset.collection_group
        assert detail.rule.source_type is (
            RuleSourceType.TMDB
            if preset is CollectionPreset.TMDB_COLLECTIONS
            else RuleSourceType.FILTER
        )
        if preset is CollectionPreset.TMDB_COLLECTIONS:
            assert detail.rule.source_identifier == "10"
            assert len(detail.members) == preview[0].count == 2
            assert detail.tmdb_collection_id == 10


async def test_generator_counts_failures_and_does_not_accept_stale_selection(
    manager: Manager,
) -> None:
    body = CollectionGenerateRequest(
        media_type=MediaType.MOVIE,
        library_id="movies",
        preset=CollectionPreset.DECADES,
        titles=["missing"],
    )
    with pytest.raises(PublicServiceError, match="current preview"):
        await manager.service.generate(body)
    body.titles = ["1990s", "2000s"]
    manager.provider.fail = True
    result = await manager.service.generate(body)
    assert result.created == []
    assert set(result.errors) == set(body.titles)


async def test_scheduler_honors_due_times_and_stops_its_client(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.save_rule(
        identity,
        MediaType.MOVIE,
        CollectionRuleWrite(source_type=RuleSourceType.MDBLIST, source_identifier="42"),
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
        CollectionRuleWrite(source_type=RuleSourceType.TMDB, source_identifier="10"),
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
        CollectionRuleWrite(source_type=RuleSourceType.TMDB, source_identifier="10"),
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
            source_type=RuleSourceType.MDBLIST,
            source_identifier="42",
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
            source_type=RuleSourceType.MDBLIST,
            source_identifier="42",
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
    assert set(groups) == {preset.collection_group for preset in CollectionPreset} | {
        "Weekend"
    }
    listed = await manager.service.list_collections(MediaType.MOVIE)
    assert listed[0].collection_group == "Weekend"
    detail = await manager.service.update(
        identity,
        MediaType.MOVIE,
        CollectionOptions(title="Saga", collection_group=" "),
    )
    assert detail.collection_group is None


async def test_franchise_generator_excludes_existing_matches_with_other_titles(
    manager: Manager,
) -> None:
    identity = await create(manager)
    await manager.service.update(
        identity,
        MediaType.MOVIE,
        CollectionOptions(title="My franchise", tmdb_collection_id=10),
    )
    body = CollectionGenerateRequest(
        media_type=MediaType.MOVIE,
        library_id="movies",
        preset=CollectionPreset.TMDB_COLLECTIONS,
    )
    assert await manager.service.presets(body) == []


async def test_franchise_generator_respects_minimum_and_missing_tmdb(
    manager: Manager, database: Database
) -> None:
    body = CollectionGenerateRequest(
        media_type=MediaType.MOVIE,
        library_id="movies",
        preset=CollectionPreset.TMDB_COLLECTIONS,
    )
    async with database.write_session() as session:
        settings = await get_app_settings(session)
        settings.collection_minimum_items = 4
        session.add(settings)
    assert await manager.service.presets(body) == []
    async with database.write_session() as session:
        settings = await get_app_settings(session)
        settings.collection_minimum_items = 1
        session.add(settings)
    manager.tmdb.found = False
    assert await manager.service.presets(body) == []


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
                source_type=RuleSourceType.TMDB, source_identifier="10"
            ),
        )
    )
    assert detail.tmdb_collection_id == 10
    assert [member.tmdb_id for member in detail.members] == [11, 12]
    assert detail.rule is not None
    assert detail.rule.source_identifier == "10"


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
        CollectionRuleWrite(source_type=RuleSourceType.MDBLIST, source_identifier="42"),
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
            source_type=RuleSourceType.MDBLIST,
            source_identifier="42",
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
            source_type=RuleSourceType.MDBLIST,
            source_identifier="42",
            minimum_items=1,
            sync_mode=SyncMode.APPEND,
        ),
    )
    assert (
        await manager.service.get_collection(identity, MediaType.MOVIE)
    ).effective_sync_mode is SyncMode.APPEND


async def test_generator_overrides_group_threshold_and_persists_rule_choices(
    manager: Manager,
) -> None:
    await manager.service.save_group_policy(
        MediaType.MOVIE, "Weekend", CollectionGroupPolicy(minimum_items=3)
    )
    body = CollectionGenerateRequest(
        media_type=MediaType.MOVIE,
        library_id="movies",
        preset=CollectionPreset.DECADES,
        collection_group="Weekend",
        minimum_items=2,
        sync_mode=SyncMode.APPEND,
        auto_match_art=False,
        titles=["2000s"],
        sort_title_format="!{title}",
    )
    preview = await manager.service.presets(body)
    assert [(row.title, row.count) for row in preview] == [("2000s", 2)]
    result = await manager.service.generate(body)
    assert not result.errors
    detail = await manager.service.get_collection(result.created[0], MediaType.MOVIE)
    assert detail.rule is not None
    assert detail.rule.minimum_items == 2
    assert detail.rule.sync_mode is SyncMode.APPEND
    assert detail.rule.auto_match_art is False
    assert detail.collection_group == "Weekend"
    assert detail.sort_title == "!2000s"
    assert manager.provider.sort_titles["1"] == "!2000s"


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
