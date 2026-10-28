"""Collection catalog downloads share bulk scope, skip rules and asset locks."""

lazy from pathlib import Path
lazy from typing import Any

lazy import pytest
lazy from pydantic import ValidationError
lazy from sqlmodel import select

lazy from overture.config import Settings
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.public_dataset import PublicDatasetCollection
lazy from overture.db.session import Database
lazy from overture.domain import (
    IncrementalThemeOrder,
    MediaType,
    ServerType,
    ThemeBulkSource,
)
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import run_managed_job
lazy from overture.jobs.tally import BulkAssetTally
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from overture.media_servers.plex import PlexProvider
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.schemas.bulk import (
    BulkAssetsRequest,
    BulkAssetsScheduleWrite,
    BulkThemeRequest,
)
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.public_dataset.downloads import (
    queue_catalog_themes_for_collections,
)
lazy from overture.services.themes.collection_bulk import (
    plan_collection_themes,
    run_collection_themes,
)
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_public_dataset, make_bulk_downloads
lazy from tests.runtime_helpers import JobProbe


async def _seed(database: Database, *, saved: str | None = None) -> None:
    async with database.write_session() as session:
        session.add(
            MediaCollection(
                id=1,
                server_item_id="opaque-server-id",
                server_type=ServerType.PLEX,
                media_type=MediaType.MOVIE,
                library_id="movies",
                title="Saga",
                tmdb_collection_id=10,
                youtube_id=saved,
                last_synced_at=utc_now(),
            )
        )
        session.add(
            PublicDatasetCollection(
                tmdb_id=10,
                title="Saga",
                youtube_id_overturedb="o" * 11,
                youtube_id_themerrdb="t" * 11,
            )
        )
        await enable_public_dataset(session)


@pytest.mark.parametrize(
    ("sources", "expected"),
    [
        ([ThemeBulkSource.THEMERRDB, ThemeBulkSource.OVERTUREDB], "t" * 11),
        ([ThemeBulkSource.YOUTUBE_SEARCH, ThemeBulkSource.OVERTUREDB], "o" * 11),
        ([ThemeBulkSource.YOUTUBE_SEARCH], None),
    ],
)
async def test_bulk_collection_scope_uses_catalog_order_and_never_searches_youtube(
    *,
    app_config: Settings,
    database: Database,
    sources: list[ThemeBulkSource],
    expected: str | None,
) -> None:
    await _seed(database)
    params = BulkThemeRequest(collection_ids=[1], source_order=sources)
    plan = await plan_collection_themes(
        params, app_config=app_config, database=database
    )
    assert plan.total == 1
    downloads = make_bulk_downloads(
        app_config=app_config,
        database=database,
        provider=PlexProvider(app_config=app_config),
    )
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_THEME))
    with downloads.watch() as watch:
        async with run_managed_job(
            probe.context, BulkAssetTally(), database=database
        ) as job:
            await job.started()
            await job.planned(plan.total)
            await run_collection_themes(
                job,
                params,
                plan,
                downloads=downloads,
                watch=watch,
                app_config=app_config,
                database=database,
            )
    async with database.read_session() as session:
        jobs = (await session.exec(select(DownloadJob))).all()
    assert [job.target_url for job in jobs] == ([] if expected is None else [expected])
    if jobs:
        assert jobs[0].collection_id == 1
        assert jobs[0].media_item_id is None


async def test_library_and_item_scopes_keep_collections_opt_in(
    *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    for params, total in [
        (BulkThemeRequest(library_ids=["movies"]), 0),
        (BulkThemeRequest(library_ids=["movies"], include_collections=True), 1),
        (BulkThemeRequest(library_ids=["elsewhere"], include_collections=True), 0),
        (BulkThemeRequest(item_ids=[1], include_collections=True), 0),
    ]:
        plan = await plan_collection_themes(
            params, app_config=app_config, database=database
        )
        assert plan.total == total


async def test_incremental_fill_keeps_choices_and_deletion_cascades_jobs(
    *, app_config: Settings, database: Database
) -> None:
    await _seed(database)
    downloads = make_bulk_downloads(
        app_config=app_config,
        database=database,
        provider=PlexProvider(app_config=app_config),
    )
    async with database.write_session() as session:
        chosen_id, _ = await downloads.queue_job(
            session, JobTarget.collection_theme(1, "Saga", "chosenTheme")
        )
    queued = await queue_catalog_themes_for_collections(
        [1],
        theme_order=IncrementalThemeOrder.OVERTUREDB_THEMERRDB,
        downloads=downloads,
        app_config=app_config,
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


def test_collection_requests_reject_art_mixed_scopes_and_saved_sidebar_snapshots() -> (
    None
):

    invalid: list[dict[str, Any]] = [
        {"collection_ids": [1], "art": {}},
        {"collection_ids": [1], "library_ids": ["movies"], "themes": {}},
        {"collection_ids": [], "themes": {}},
    ]
    for fields in invalid:
        with pytest.raises(ValidationError):
            BulkAssetsRequest.model_validate(fields)
    with pytest.raises(ValidationError, match="library selection"):
        BulkAssetsScheduleWrite.model_validate(
            {
                "name": "Collections",
                "cron_expression": "0 3 * * *",
                "config": {"collection_ids": [1], "themes": {}},
            }
        )


@pytest.mark.parametrize("existing_file", [False, True])
async def test_jellyfin_restores_a_missing_theme_and_keeps_a_recorded_one(
    tmp_path: Path, *, app_config: Settings, database: Database, existing_file: bool
) -> None:
    await _seed(database, saved="savedTheme1")
    folder = tmp_path / "Saga [boxset]"
    folder.mkdir()
    if existing_file:
        (folder / "theme.mp3").write_bytes(b"replaced by another application")
    app_config.JELLYFIN_COLLECTIONS_PATH = tmp_path
    async with database.write_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        row.server_type = ServerType.JELLYFIN
        row.server_path = "/config/collections/Saga [boxset]"
        # Planning trusts the recorded file facts: none recorded means missing.
        row.theme_file_hash = "previous-file" if existing_file else None
        session.add(row)
    downloads = make_bulk_downloads(
        app_config=app_config,
        database=database,
        provider=JellyfinProvider(app_config=app_config),
    )
    params = BulkThemeRequest(collection_ids=[1])
    plan = await plan_collection_themes(
        params, app_config=app_config, database=database
    )
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_THEME))
    with downloads.watch() as watch:
        async with run_managed_job(
            probe.context, BulkAssetTally(), database=database
        ) as job:
            await job.started()
            await job.planned(plan.total)
            await run_collection_themes(
                job,
                params,
                plan,
                downloads=downloads,
                watch=watch,
                app_config=app_config,
                database=database,
            )
    async with database.read_session() as session:
        row = await session.get(MediaCollection, 1)
        assert row is not None
        jobs = (await session.exec(select(DownloadJob))).all()
        assert row.youtube_id == "savedTheme1"
        assert [job.target_url for job in jobs] == (
            [] if existing_file else ["savedTheme1"]
        )
