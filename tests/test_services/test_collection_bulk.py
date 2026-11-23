"""Collection catalog downloads share bulk scope, skip rules and asset locks."""

lazy from pathlib import Path
lazy from typing import Any

lazy import pytest
lazy from pydantic import ValidationError
lazy from sqlmodel import select

lazy from overture.config import Settings
lazy from overture.db.ledger import Destination, place
lazy from overture.db.models.catalog import CatalogCollection
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.session import Database
lazy from overture.domain import (
    CURRENT_SELECTION,
    DeliveryChannel,
    IncrementalThemeOrder,
    MediaType,
    ServerAsset,
    ServerType,
    ThemeBulkSource,
)
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from overture.media_servers.plex import PlexProvider
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.schemas.bulk import (
    BulkAssetsRequest,
    BulkAssetsScheduleWrite,
    BulkThemeRequest,
)
lazy from overture.services.asset_runs import run as asset_run
lazy from overture.services.asset_runs.plan import AssetPlan, plan_run
lazy from overture.services.catalog.downloads import (
    queue_catalog_themes_for_collections,
)
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.hashing import compute_bytes_hash
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_catalog, make_bulk_downloads
lazy from tests.collection_helpers import managing_rule, stored_collection
lazy from tests.factories import seed_theme, theme_of
lazy from tests.media_servers import TEST_SERVER_ID, configure, server_of
lazy from tests.runtime_helpers import JobProbe, make_local_assets, unused


async def _seed(database: Database, *, saved: str | None = None) -> None:
    async with database.write_session() as session:
        session.add(
            seed_theme(
                stored_collection(
                    id=1,
                    server_item_id="opaque-server-id",
                    media_type=MediaType.MOVIE,
                    library_id="1:movies",
                    title="Saga",
                    tmdb_collection_id=10,
                    last_synced_at=utc_now(),
                ),
                saved,
            )
        )
        await session.flush()
        session.add(managing_rule(1))
        session.add(
            CatalogCollection(
                tmdb_id=10,
                title="Saga",
                youtube_id_overturedb="o" * 11,
                youtube_id_themerrdb="t" * 11,
            )
        )
        await enable_catalog(session)


def collection_total(plan: AssetPlan) -> int:
    """Return how many collection targets *plan* reports on."""
    decided = sum(
        count for (collection, _, _), count in plan.decided.items() if collection
    )
    return decided + sum(
        len(slots)
        for batch in plan.batches()
        if batch.collections
        for slots in batch.visits.values()
    )


async def _queued(
    params: BulkThemeRequest,
    downloads: DownloadService,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> list[JobTarget]:
    """Run an Assets theme job and return the downloads it queued."""
    queued: list[JobTarget] = []

    async def record(target: JobTarget, **_kwargs: Any) -> bool:
        queued.append(target)
        return True

    monkeypatch.setattr(asset_run, "queue_download", record)
    await asset_run.run_themes(
        JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_THEME)).context,
        params,
        downloads=downloads,
        youtube_resolver=unused(YouTubeResolver),
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )
    return queued


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        ([ThemeBulkSource.THEMERRDB, ThemeBulkSource.OVERTUREDB], "t" * 11),
        ([ThemeBulkSource.YOUTUBE_SEARCH, ThemeBulkSource.OVERTUREDB], "o" * 11),
        ([ThemeBulkSource.YOUTUBE_SEARCH], None),
    ],
)
async def test_bulk_collection_scope_uses_catalog_order_and_never_searches_youtube(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
    sources: list[ThemeBulkSource],
    expected: str | None,
) -> None:
    await _seed(database)
    params = BulkThemeRequest(
        collection_ids=[1], source_order=[CURRENT_SELECTION, *sources]
    )
    plan = await plan_run(params, database=database)
    assert plan.total == 1
    downloads = make_bulk_downloads(
        app_config=app_config,
        database=database,
        provider=PlexProvider(
            server=server_of(app_config),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
    )
    queued = await _queued(
        params, downloads, monkeypatch, app_config=app_config, database=database
    )
    assert [target.target_url for target in queued] == (
        [] if expected is None else [expected]
    )
    assert all(
        (target.collection_id, target.media_item_id) == (1, None) for target in queued
    )


async def test_collections_run_beside_libraries_only_when_chosen(
    *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    for params, total in [
        (BulkThemeRequest(library_ids=["1:movies"]), 0),
        (BulkThemeRequest(library_ids=["1:movies"], all_collections=True), 1),
        (BulkThemeRequest(library_ids=["1:elsewhere"], all_collections=True), 1),
        (BulkThemeRequest(item_ids=[1]), 0),
    ]:
        plan = await plan_run(params, database=database)
        assert collection_total(plan) == total


async def test_incremental_fill_keeps_choices_and_deletion_cascades_jobs(
    *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    downloads = make_bulk_downloads(
        app_config=app_config,
        database=database,
        provider=PlexProvider(
            server=server_of(app_config),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
    )
    async with database.write_session() as session:
        chosen_id, _ = await downloads.queue_job(
            session, JobTarget.collection_theme(1, "Saga", "chosenTheme")
        )
    queued = await queue_catalog_themes_for_collections(
        [1],
        theme_order=IncrementalThemeOrder.OVERTUREDB_THEMERRDB,
        downloads=downloads,
        database=database,
    )
    assert queued.themes == 0
    async with database.read_session() as session:
        jobs = (await session.exec(select(DownloadJob))).all()
        assert [(job.id, job.target_url) for job in jobs] == [
            (chosen_id, "chosenTheme")
        ]
    async with database.write_session() as session:
        await CollectionRepository(session).delete_ids([1])
    async with database.read_session() as session:
        assert (await session.exec(select(DownloadJob))).all() == []


def test_bulk_requests_choose_collections_beside_libraries_and_items_alone() -> None:
    invalid: list[dict[str, Any]] = [
        {"collection_ids": [1], "all_collections": True, "themes": {}},
        {"collection_groups": ["Sagas"], "all_collections": True, "themes": {}},
        {"item_ids": [1], "collection_ids": [1], "themes": {}},
        {"collection_ids": [], "themes": {}},
        {"collection_groups": [], "art": {}},
        {"themes": {}},
    ]
    for fields in invalid:
        with pytest.raises(ValidationError):
            BulkAssetsRequest.model_validate(fields)
    for scope in (
        {"collection_ids": [1]},
        {"collection_groups": ["Sagas"]},
        {"collection_ids": [1], "collection_groups": ["Sagas"]},
        {"collection_ids": [1], "library_ids": ["1:movies"]},
        {"all_collections": True},
    ):
        request = BulkAssetsRequest.model_validate({**scope, "art": {}, "themes": {}})
        assert request.collection_scope


def test_schedules_take_collection_scopes_but_not_sidebar_items() -> None:
    def schedule(config: dict[str, Any]) -> BulkAssetsScheduleWrite:
        return BulkAssetsScheduleWrite.model_validate(
            {"name": "Collections", "cron_expression": "0 3 * * *", "config": config}
        )

    assert schedule({"collection_groups": ["Sagas"], "art": {}}).config.art
    assert schedule({"all_collections": True, "themes": {}}).config.themes
    with pytest.raises(ValidationError, match="Scheduled assets require"):
        schedule({"item_ids": [1], "themes": {}})


@pytest.mark.parametrize(
    ("disk_state", "expected"),
    [
        ("unchanged", []),
        ("missing", ["savedTheme1"]),
        ("deleted_after_sync", ["savedTheme1"]),
        ("replaced_after_sync", ["savedTheme1"]),
    ],
)
async def test_jellyfin_restores_a_missing_or_replaced_theme_and_keeps_an_unchanged_one(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
    disk_state: str,
    expected: list[str],
) -> None:
    await _seed(database, saved="savedTheme1")
    folder = tmp_path / "Saga [boxset]"
    folder.mkdir()
    written = b"saved collection theme"
    theme_path = folder / "theme.mp3"
    if disk_state != "missing":
        theme_path.write_bytes(written)
        stat = theme_path.stat()
        recorded_hash = compute_bytes_hash(written)
    else:
        stat = None
        recorded_hash = None
    configure(app_config, collections_path=tmp_path)
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        row.libraries[0].server_path = "/config/collections/Saga [boxset]"
        folder_copy = Destination(
            TEST_SERVER_ID, "opaque-server-id", DeliveryChannel.FILE
        )
        place(row, ServerAsset.THEME, (folder_copy,))
        if stat is not None and recorded_hash is not None:
            seed_theme(
                row,
                "savedTheme1",
                file_hash=recorded_hash,
                file_mtime_ns=stat.st_mtime_ns,
                file_size=stat.st_size,
                destination=folder_copy,
            )
        session.add(row)
    if disk_state == "deleted_after_sync":
        theme_path.unlink()
    elif disk_state == "replaced_after_sync":
        theme_path.write_bytes(b"replaced by another application")
    downloads = make_bulk_downloads(
        app_config=app_config,
        database=database,
        provider=JellyfinProvider(
            server=server_of(app_config, ServerType.JELLYFIN),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
    )
    queued = await _queued(
        BulkThemeRequest(collection_ids=[1]),
        downloads,
        monkeypatch,
        app_config=app_config,
        database=database,
    )
    async with database.read_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        assert theme_of(row).youtube_id == "savedTheme1"
    assert [target.target_url for target in queued] == expected


async def test_runs_leave_unmanaged_collections_alone(
    *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    async with database.write_session() as session:
        rule = await CollectionRepository(session).rule(1)
        await session.delete(rule)
    plan = await plan_run(BulkThemeRequest(all_collections=True), database=database)
    assert collection_total(plan) == 0
