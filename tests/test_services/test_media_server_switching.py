"""Tests for media-server switching and external ID matching priority."""

lazy from datetime import UTC, datetime
lazy from pathlib import Path
lazy from typing import Any

lazy import pytest
lazy from sqlalchemy.ext.asyncio import async_sessionmaker
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings, media_server_identity
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.saved_schedule import SavedSchedule
lazy from overture.db.session import Database
lazy from overture.domain import MediaType, ServerType
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.jobs.gate import LibraryGate
lazy from overture.media_servers.adapters import ServerItem, ServerSection
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from overture.repositories.media_items import MediaItemRepository
lazy from overture.schemas.sync import SyncScheduleConfig, SyncScheduleWrite
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.schedule_store import (
    SYNC_SERVER_SCHEDULE,
    SyncServerPayload,
    load_schedule,
    save_schedule,
)
lazy from overture.services.scheduler import SchedulerService
lazy from overture.services.sync.engine import SyncEngine
lazy from overture.services.sync.item_sync import ItemReconciler
lazy from overture.services.sync.reconciler import LibraryReconciler
lazy from overture.utils.time import parse_utc_datetime
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopDownloads,
    NoopProviderRegistry,
    make_local_assets,
    unused,
)
lazy from tests.sync_helpers import sync_full


def _make_server_item(
    item_id: str,
    title: str,
    *,
    media_type: MediaType = MediaType.MOVIE,
    year: int = 2020,
    guids: dict[str, str] | None = None,
    server_link: str = "",
    library_id: str = "lib-1",
    folder_path: str | None = None,
    director: str | None = None,
    studio: str | None = None,
) -> ServerItem:
    return ServerItem(
        id=item_id,
        title=title,
        year=year,
        guids=guids or {},
        media_type=media_type,
        poster_url=None,
        background_url=None,
        server_link=server_link or f"https://server.test/items/{item_id}",
        library_id=library_id,
        folder_path=folder_path,
        director=director,
        studio=studio,
    )


async def test_switch_media_server_updates_link_and_verified_timestamp(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Switching from Plex to Jellyfin correlates via TMDB ID and updates
    server_link and verified timestamp.
    """
    old_verified = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)
    async with isolated_session_factory() as session:
        plex_item = MediaItem(
            media_type=MediaType.MOVIE,
            title="The Matrix",
            year=1999,
            tmdb_id=603,
            imdb_id="tt0133093",
            server_item_id="plex-101",
            server_link="https://app.plex.tv/desktop/#!/server/abc/details?key=101",
            server_verified_at=old_verified,
            library_id="1",
        )
        session.add(plex_item)
        await session.commit()
        item_id = plex_item.id

    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    jellyfin_items = [
        _make_server_item(
            "jf-uuid-603",
            "The Matrix",
            year=1999,
            guids={"tmdb": "603", "imdb": "tt0133093"},
            server_link="http://jellyfin.local:8096/web/index.html#!/details?id=jf-uuid-603",
            library_id="jf-movies-lib",
        )
    ]

    stats = await sync_full(reconciler, jellyfin_items)

    assert stats.tally.errors == 0
    assert stats.created_item_ids == []

    async with isolated_session_factory() as session:
        all_items = (await session.exec(select(MediaItem))).all()
        assert len(all_items) == 1
        updated = all_items[0]

        assert updated.id == item_id
        assert updated.server_item_id == "jf-uuid-603"
        assert (
            updated.server_link
            == "http://jellyfin.local:8096/web/index.html#!/details?id=jf-uuid-603"
        )
        assert updated.library_id == "jf-movies-lib"
        assert updated.server_verified_at is not None
        verified_at = parse_utc_datetime(updated.server_verified_at)
        assert verified_at is not None
        assert verified_at > old_verified
        assert updated.server_removed_at is None


async def test_id_collision_immunity_across_servers(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """When two servers use the same numeric IDs for different movies,
    external GUIDs prevent cross-contamination.
    """
    async with isolated_session_factory() as session:
        session.add_all(
            [
                MediaItem(
                    id=10,
                    media_type=MediaType.MOVIE,
                    title="Alien",
                    year=1979,
                    tmdb_id=348,
                    server_item_id="1",  # Plex ratingKey "1" is Alien
                    server_link="https://plex/1",
                    library_id="lib1",
                ),
                MediaItem(
                    id=20,
                    media_type=MediaType.MOVIE,
                    title="Toy Story",
                    year=1995,
                    tmdb_id=862,
                    server_item_id="2",  # Plex ratingKey "2" is Toy Story
                    server_link="https://plex/2",
                    library_id="lib1",
                ),
            ]
        )
        await session.commit()

    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    # In Emby, item "1" is Toy Story and item "2" is Alien (swapped IDs!)
    emby_items = [
        _make_server_item(
            "1",
            "Toy Story",
            year=1995,
            guids={"tmdb": "862"},
            server_link="http://emby/item/1",
        ),
        _make_server_item(
            "2",
            "Alien",
            year=1979,
            guids={"tmdb": "348"},
            server_link="http://emby/item/2",
        ),
    ]

    stats = await sync_full(reconciler, emby_items)
    assert stats.tally.errors == 0
    assert stats.created_item_ids == []

    async with isolated_session_factory() as session:
        alien = await session.get(MediaItem, 10)
        toy_story = await session.get(MediaItem, 20)

        assert alien is not None
        assert alien.title == "Alien"
        assert alien.tmdb_id == 348
        assert alien.server_item_id == "2"  # Correctly matched Emby item "2"
        assert alien.server_link == "http://emby/item/2"

        assert toy_story is not None
        assert toy_story.title == "Toy Story"
        assert toy_story.tmdb_id == 862
        assert toy_story.server_item_id == "1"  # Correctly matched Emby item "1"
        assert toy_story.server_link == "http://emby/item/1"


async def test_unmatched_media_migrates_via_folder_path(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Home videos or uncurated media without external GUIDs correlate by
    folder_path across servers.
    """
    folder = "/media/home_videos/trip_2023"
    async with isolated_session_factory() as session:
        session.add(
            MediaItem(
                id=50,
                media_type=MediaType.MOVIE,
                title="Summer Vacation",
                folder_path=folder,
                server_item_id="plex-video-42",
                server_link="https://plex/video/42",
            )
        )
        await session.commit()

    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    new_server_items = [
        _make_server_item(
            "jf-video-99",
            "Summer Vacation",
            guids={},  # No external IDs
            folder_path=folder,
            server_link="http://jellyfin/items/jf-video-99",
        )
    ]

    stats = await sync_full(reconciler, new_server_items)
    assert stats.tally.errors == 0
    assert stats.created_item_ids == []

    async with isolated_session_factory() as session:
        item = await session.get(MediaItem, 50)
        assert item is not None
        assert item.server_item_id == "jf-video-99"
        assert item.server_link == "http://jellyfin/items/jf-video-99"
        assert item.server_removed_at is None


async def test_multiple_editions_with_same_tmdb_id_do_not_overwrite(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Two separate cuts sharing the same TMDB ID are reconciled independently
    without overwriting each other.
    """
    async with isolated_session_factory() as session:
        session.add_all(
            [
                MediaItem(
                    id=101,
                    media_type=MediaType.MOVIE,
                    title="Blade Runner (Theatrical)",
                    tmdb_id=78,
                    server_item_id="cut-1",
                    server_link="https://server/cut-1",
                ),
                MediaItem(
                    id=102,
                    media_type=MediaType.MOVIE,
                    title="Blade Runner (Final Cut)",
                    tmdb_id=78,
                    server_item_id="cut-2",
                    server_link="https://server/cut-2",
                ),
            ]
        )
        await session.commit()

    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    server_items = [
        _make_server_item(
            "cut-1",
            "Blade Runner (Theatrical)",
            guids={"tmdb": "78"},
            server_link="https://server/cut-1",
        ),
        _make_server_item(
            "cut-2",
            "Blade Runner (Final Cut)",
            guids={"tmdb": "78"},
            server_link="https://server/cut-2",
        ),
    ]

    stats = await sync_full(reconciler, server_items)
    assert stats.tally.errors == 0

    async with isolated_session_factory() as session:
        cut1 = await session.get(MediaItem, 101)
        cut2 = await session.get(MediaItem, 102)

        assert cut1 is not None
        assert cut1.server_item_id == "cut-1"
        assert cut2 is not None
        assert cut2.server_item_id == "cut-2"


async def test_media_server_switch_resets_schedule_filters(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """When MEDIA_SERVER or URL changes, SyncEngine resets library_ids and
    incremental checkpoints on every saved sync schedule.
    """

    def make_engine() -> SyncEngine:
        return SyncEngine(
            tmdb_client=unused(TMDBClient),
            downloads=unused(DownloadService),
            provider_registry=NoopProviderRegistry(),
            scheduler=SchedulerService(app_config=app_config),
            publisher=NullEventPublisher(),
            library_gate=LibraryGate(),
            local_assets=make_local_assets(app_config=app_config, database=database),
            app_config=app_config,
            database=database,
            config_dir=tmp_path,
        )

    # Pre-seed schedules saved against the old server
    async with isolated_session_factory() as session:
        await save_schedule(
            session,
            SYNC_SERVER_SCHEDULE,
            payload=SyncServerPayload(
                last_media_server=media_server_identity(
                    "plex", "http://192.168.1.10:32400"
                )
            ),
        )
        await session.commit()
    seeding = make_engine()
    ids: list[int] = []
    for name, mode in (("Full", "full"), ("Poll", "incremental")):
        body = SyncScheduleWrite(
            name=name,
            cron_expression="0 3 * * *",
            config=SyncScheduleConfig.model_validate(
                {"mode": mode, "library_ids": ["plex-lib-1", "plex-lib-2"]}
            ),
        )
        ids.append((await seeding.schedules.create(body)).id)
    async with isolated_session_factory() as session:
        for schedule_id in ids:
            record = await session.get(SavedSchedule, schedule_id)
            assert record is not None
            record.state = {"checkpoint": "2026-01-01T00:00:00Z"}
            session.add(record)
        await session.commit()
    await seeding.schedules.stop()

    # Configure active app settings to a new server
    app_config.MEDIA_SERVER = ServerType.JELLYFIN
    app_config.MEDIA_SERVER_URL = "http://jellyfin.local:8096"

    engine = make_engine()
    await engine.start()

    async with isolated_session_factory() as session:
        server = await load_schedule(session, SYNC_SERVER_SCHEDULE)
    schedules = await engine.schedules.all()

    # Filters must be reset to "all libraries" to prevent accidental data loss
    assert server.payload.last_media_server == media_server_identity(
        "jellyfin", "http://jellyfin.local:8096"
    )
    assert [schedule.config.library_ids for schedule in schedules] == [[], []]
    assert [schedule.state.checkpoint for schedule in schedules] == [None, None]
    await engine.stop()

    async with isolated_session_factory() as session:
        for schedule_id in ids:
            record = await session.get(SavedSchedule, schedule_id)
            assert record is not None
            record.payload = {**record.payload, "library_ids": ["current-library"]}
            record.state = {"checkpoint": "2026-01-02T00:00:00Z"}
            session.add(record)
        await session.commit()
    app_config.MEDIA_SERVER_URL += "/"
    restarted = make_engine()
    await restarted.start()
    try:
        restored = await restarted.schedules.all()
        assert [schedule.config.library_ids for schedule in restored] == [
            ["current-library"],
            ["current-library"],
        ]
        assert all(
            schedule.state.checkpoint == datetime(2026, 1, 2, tzinfo=UTC)
            for schedule in restored
        )
        assert all(
            schedule.last_run_at is None and schedule.run_status == "idle"
            for schedule in restored
        )
    finally:
        await restarted.stop()


async def test_server_item_id_collision_with_conflicting_guids_creates_new_item(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """When switching media server, if incoming item happens to share the same
    server_item_id as an existing item but has conflicting GUIDs or folder paths,
    it must NOT overwrite the existing item; it must create a new record.
    """
    async with isolated_session_factory() as session:
        old_item = MediaItem(
            media_type=MediaType.MOVIE,
            title="The Godfather",
            year=1972,
            tmdb_id=238,
            server_item_id="42",  # Old Plex ratingKey
            server_link="https://app.plex.tv/details?key=42",
            folder_path="/media/movies/The Godfather (1972)",
            library_id="1",
        )
        session.add(old_item)
        await session.commit()
        old_id = old_item.id

    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    # Jellyfin has a completely different movie (Goodfellas)
    # that coincidentally has id="42"
    jellyfin_items = [
        _make_server_item(
            "42",
            "Goodfellas",
            year=1990,
            guids={"tmdb": "769"},
            folder_path="/media/movies/Goodfellas (1990)",
            library_id="jelly-movies",
        )
    ]

    await sync_full(reconciler, jellyfin_items)

    async with isolated_session_factory() as session:
        items = (await session.exec(select(MediaItem))).all()
        assert len(items) == 2

        godfather = next(i for i in items if i.id == old_id)
        assert godfather.title == "The Godfather"
        assert godfather.tmdb_id == 238
        # Since Godfather was not on Jellyfin, full sync marks it removed
        assert godfather.server_removed_at is not None

        goodfellas = next(i for i in items if i.id != old_id)
        assert goodfellas.title == "Goodfellas"
        assert goodfellas.tmdb_id == 769
        assert goodfellas.server_item_id == "42"
        assert goodfellas.server_removed_at is None


async def test_switch_media_server_folder_path_slash_normalization(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Folder paths with trailing slashes or backslash variants match cleanly."""
    async with isolated_session_factory() as session:
        home_video = MediaItem(
            media_type=MediaType.MOVIE,
            title="Summer Holiday 2024",
            year=2024,
            server_item_id="plex-home-1",
            folder_path="/media/home_videos/Summer 2024",  # No trailing slash
            library_id="1",
        )
        session.add(home_video)
        await session.commit()
        item_id = home_video.id

    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    # Jellyfin returns the path with a trailing slash
    jellyfin_items = [
        _make_server_item(
            "jf-home-1",
            "Summer Holiday 2024",
            year=2024,
            guids={},
            folder_path="/media/home_videos/Summer 2024/",
            library_id="jf-home-lib",
        )
    ]

    await sync_full(reconciler, jellyfin_items)

    async with isolated_session_factory() as session:
        updated = await session.get(MediaItem, item_id)
        assert updated is not None
        assert updated.server_item_id == "jf-home-1"
        assert updated.server_removed_at is None


async def test_selected_sections_empty_library_ids_selects_all(
    monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    """No library filter, empty or absent, selects every section."""
    sections = [
        ServerSection("lib-1", "Movies", MediaType.MOVIE),
        ServerSection("lib-2", "Shows", MediaType.SHOW),
    ]
    provider = JellyfinProvider(app_config=app_config)

    async def get_sections() -> list[ServerSection]:
        return sections

    monkeypatch.setattr(provider, "get_sections", get_sections)

    assert await provider.select_sections([]) == sections
    assert await provider.select_sections(None) == sections
    assert await provider.select_sections(["lib-1"]) == sections[:1]


async def test_switch_media_server_updates_title_year_director_and_guids(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """When switching media servers, items matched via external identifiers
    update their title, year, director, studio, and GUIDs from the new server.
    """
    async with isolated_session_factory() as session:
        plex_item = MediaItem(
            media_type=MediaType.MOVIE,
            title="12 Monkeys",
            year=1995,
            tmdb_id=63,
            tvdb_id=1234,
            server_item_id="plex-12",
            server_link="https://app.plex.tv/desktop/#!/server/abc/details?key=12",
            library_id="plex-lib-1",
            director="T. Gilliam",
            studio="Universal",
        )
        session.add(plex_item)
        await session.commit()
        item_id = plex_item.id

    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    jellyfin_items = [
        _make_server_item(
            "jf-uuid-twelve-monkeys",
            "Twelve Monkeys",
            year=1996,
            guids={"tmdb": "63", "imdb": "tt0114746"},
            server_link="http://jellyfin.local:8096/web/index.html#!/details?id=jf-uuid-twelve-monkeys",
            library_id="jf-movies-lib",
            director="Terry Gilliam",
            studio="Universal Pictures",
        )
    ]

    stats = await sync_full(reconciler, jellyfin_items)

    assert stats.tally.errors == 0
    assert stats.created_item_ids == []

    async with isolated_session_factory() as session:
        updated = await session.get(MediaItem, item_id)
        assert updated is not None
        assert updated.id == item_id
        assert updated.title == "Twelve Monkeys"
        assert updated.year == 1996
        assert updated.director == "Terry Gilliam"
        assert updated.studio == "Universal Pictures"
        assert updated.server_item_id == "jf-uuid-twelve-monkeys"
        assert updated.imdb_id == "tt0114746"
        assert updated.tmdb_id == 63
        assert updated.tvdb_id == 1234
        assert (
            updated.server_link
            == "http://jellyfin.local:8096/web/index.html#!/details?id=jf-uuid-twelve-monkeys"
        )
        assert updated.library_id == "jf-movies-lib"


async def test_sync_clears_or_omits_director_for_tv_shows(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """TV shows must never store a director, and existing show directors are cleared."""
    async with isolated_session_factory() as session:
        existing_show = MediaItem(
            media_type=MediaType.SHOW,
            title="Old Show",
            year=2020,
            tvdb_id=999,
            server_item_id="old-server-show",
            director="Accidental Director",
            library_id="lib-shows",
        )
        session.add(existing_show)
        await session.commit()
        show_id = existing_show.id

    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    items = [
        _make_server_item(
            "new-server-show",
            "Old Show",
            media_type=MediaType.SHOW,
            year=2020,
            guids={"tvdb": "999"},
            library_id="lib-shows",
            director="Server Show Director",
        ),
        _make_server_item(
            "brand-new-show",
            "Brand New Show",
            media_type=MediaType.SHOW,
            year=2024,
            guids={"tvdb": "888"},
            library_id="lib-shows",
            director="Another Show Director",
        ),
    ]

    stats = await sync_full(reconciler, items)
    assert stats.tally.errors == 0

    async with isolated_session_factory() as session:
        updated_show = await session.get(MediaItem, show_id)
        assert updated_show is not None
        assert updated_show.director is None

        repo = MediaItemRepository(session)
        created_show = await repo.find_by_server_id("brand-new-show", "show")
        assert created_show is not None
        assert created_show.director is None


async def test_sync_isolates_item_level_runtime_error_resource_unavailable(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """If an item hits a RuntimeError ('Resource temporarily unavailable'),
    only that item fails and rolls back; subsequent items sync successfully.
    """
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    original_sync_item = ItemReconciler.sync_item

    async def flaky_sync_item(
        self: ItemReconciler,
        session: Any,
        server_item: ServerItem,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        if server_item.id == "jf-failing":
            raise RuntimeError("Resource temporarily unavailable")
        return await original_sync_item(self, session, server_item, *args, **kwargs)

    monkeypatch.setattr(ItemReconciler, "sync_item", flaky_sync_item)

    items = [
        _make_server_item(
            "jf-failing",
            "Failing Movie",
            guids={"tmdb": "99999"},
        ),
        _make_server_item(
            "jf-succeeding",
            "Twelve Monkeys",
            guids={"tmdb": "63"},
        ),
    ]

    stats = await sync_full(reconciler, items)

    assert stats.tally.total == 2
    assert stats.tally.errors == 1
    assert stats.tally.added == 1
    assert len(stats.created_item_ids) == 1

    async with isolated_session_factory() as session:
        all_items = (await session.exec(select(MediaItem))).all()
        assert len(all_items) == 1
        assert all_items[0].title == "Twelve Monkeys"
        assert all_items[0].server_item_id == "jf-succeeding"
