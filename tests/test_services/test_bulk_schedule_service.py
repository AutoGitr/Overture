"""Bulk assets schedule persistence and queued execution tests."""

lazy import asyncio
lazy from typing import override

lazy import pytest
lazy from pydantic import ValidationError

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.domain import ArtBulkSource, ArtType, RecentUnit, ThemeBulkSource
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import JobContext
lazy from overture.jobs.slot import ManagedBackgroundJob
lazy from overture.schemas.bulk import (
    BulkAssetsArtConfig,
    BulkAssetsRequest,
    BulkAssetsScheduleWrite,
    BulkAssetsStopRequest,
    BulkAssetsThemeConfig,
    BulkMatchArtRequest,
    BulkThemeRequest,
)
lazy from overture.schemas.common import Status
lazy from overture.services import assets as module
lazy from overture.services.art.candidates import ArtCandidates
lazy from overture.services.art.matcher import ArtMatcher
lazy from overture.services.art.phash import PhashService
lazy from overture.services.assets import AssetsService
lazy from overture.services.scheduler import SchedulerService
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.errors import PublicServiceError
lazy from overture.ws.state import BackgroundJobRegistry
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    make_download_service,
    make_local_assets,
    unused,
)


def _assets_body(
    name: str,
    *,
    art: bool = True,
    enabled: bool = True,
    cron_expression: str = "0 3 * * *",
    library_id: str = "1",
    themes: bool = True,
) -> BulkAssetsScheduleWrite:
    return BulkAssetsScheduleWrite(
        name=name,
        enabled=enabled,
        cron_expression=cron_expression,
        config=BulkAssetsRequest(
            library_ids=[library_id],
            skip_recent_val=1,
            skip_recent_unit=RecentUnit.DAYS,
            art=(
                BulkAssetsArtConfig(
                    art_types=[ArtType.POSTER],
                    source_order=[ArtBulkSource.LOCAL_ART_MATCHING],
                )
                if art
                else None
            ),
            themes=(
                BulkAssetsThemeConfig(source_order=[ThemeBulkSource.YOUTUBE_SEARCH])
                if themes
                else None
            ),
        ),
    )


def _bulk_schedule_service(
    background_jobs: BackgroundJobRegistry | None = None,
    *,
    app_config: Settings,
    database: Database,
) -> AssetsService:
    publisher = NullEventPublisher()
    asset_storage = AssetStorage(app_config=app_config)
    phash = PhashService(app_config=app_config)
    provider_registry = NoopProviderRegistry()
    downloads = make_download_service(
        publisher,
        provider_registry=provider_registry,
        asset_storage=asset_storage,
        phash=phash,
        image_clients=unused(ProxyClientManager),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    return AssetsService(
        background_jobs=background_jobs or BackgroundJobRegistry(publisher),
        downloads=downloads,
        art_matcher=ArtMatcher(
            phash=phash,
            local_assets=make_local_assets(
                app_config=app_config, database=database, asset_storage=asset_storage
            ),
            provider_registry=provider_registry,
            candidates=unused(ArtCandidates),
            image_clients=unused(ProxyClientManager),
            app_config=app_config,
            database=database,
        ),
        youtube_resolver=unused(YouTubeResolver),
        scheduler=SchedulerService(app_config=app_config),
        publisher=publisher,
        app_config=app_config,
        local_assets=make_local_assets(
            app_config=app_config, database=database, asset_storage=asset_storage
        ),
        database=database,
    )


class FakeManagedJob(ManagedBackgroundJob):
    def __init__(self, kind: JobKind, *, running: bool) -> None:
        super().__init__(ManagedJobLifecycle(kind), NullEventPublisher())
        self._running = running

    @property
    @override
    def running(self) -> bool:
        return self._running


class FakeBackgroundJobs(BackgroundJobRegistry):
    def __init__(self, *, art_running: bool, themes_running: bool) -> None:
        super().__init__(NullEventPublisher())
        self.art_match = FakeManagedJob(JobKind.BULK_ART, running=art_running)
        self.theme_match = FakeManagedJob(JobKind.BULK_THEME, running=themes_running)


def _bulk_schedule_service_with_jobs(
    background_jobs: BackgroundJobRegistry, *, app_config: Settings, database: Database
) -> AssetsService:
    return _bulk_schedule_service(
        background_jobs, app_config=app_config, database=database
    )


def test_stop_assets_run_stops_only_selected_running_jobs(
    *, app_config: Settings, database: Database
) -> None:
    background_jobs = FakeBackgroundJobs(art_running=True, themes_running=True)
    service = _bulk_schedule_service_with_jobs(
        background_jobs, app_config=app_config, database=database
    )

    response = service.stop_run(BulkAssetsStopRequest(art=True, themes=False))

    assert response.status == Status.STOPPING
    assert background_jobs.art_match.stop_requested is True
    assert background_jobs.theme_match.stop_requested is False


def test_stop_assets_run_by_default_stops_all_running_jobs(
    *, app_config: Settings, database: Database
) -> None:
    background_jobs = FakeBackgroundJobs(art_running=True, themes_running=True)
    service = _bulk_schedule_service_with_jobs(
        background_jobs, app_config=app_config, database=database
    )

    response = service.stop_run(BulkAssetsStopRequest())

    assert response.status == Status.STOPPING
    assert background_jobs.art_match.stop_requested is True
    assert background_jobs.theme_match.stop_requested is True


def test_stop_assets_run_ignores_idle_or_unselected_jobs(
    *, app_config: Settings, database: Database
) -> None:
    background_jobs = FakeBackgroundJobs(art_running=False, themes_running=True)
    service = _bulk_schedule_service_with_jobs(
        background_jobs, app_config=app_config, database=database
    )

    response = service.stop_run(BulkAssetsStopRequest(art=True, themes=False))

    assert response.status == Status.IDLE
    assert background_jobs.art_match.stop_requested is False
    assert background_jobs.theme_match.stop_requested is False


def test_stop_assets_run_reports_no_selection(
    *, app_config: Settings, database: Database
) -> None:
    background_jobs = FakeBackgroundJobs(art_running=True, themes_running=True)
    service = _bulk_schedule_service_with_jobs(
        background_jobs, app_config=app_config, database=database
    )

    response = service.stop_run(BulkAssetsStopRequest(art=False, themes=False))

    assert response.status == Status.NO_JOBS_SELECTED
    assert background_jobs.art_match.stop_requested is False
    assert background_jobs.theme_match.stop_requested is False


async def test_bulk_assets_schedule_crud_validates_names_and_cron(
    *,
    app_config: Settings,
    database: Database,
) -> None:
    service = _bulk_schedule_service(app_config=app_config, database=database)

    created = await service.schedules.create(_assets_body(" Nightly assets "))

    assert created.id
    assert created.name == "Nightly assets"
    assert created.enabled is True
    assert created.kind == "assets"
    assert created.config.library_ids == ["1"]
    assert created.config.skip_recent_val == 1
    assert created.config.art is not None
    assert created.config.themes is not None

    for duplicate in ("Nightly assets", "NIGHTLY Assets"):
        with pytest.raises(PublicServiceError, match="already exists"):
            await service.schedules.create(_assets_body(duplicate))
    renamed = await service.schedules.update(created.id, _assets_body("nightly ASSETS"))
    assert renamed.name == "nightly ASSETS"

    with pytest.raises(ValidationError, match="cron_expression"):
        _assets_body("Invalid", cron_expression="not cron")

    updated = await service.schedules.update(
        created.id, _assets_body("Weekend assets", enabled=False, library_id="2")
    )

    assert updated.name == "Weekend assets"
    assert updated.enabled is False
    assert updated.config.library_ids == ["2"]
    assert not service.schedules.scheduler.job_info(
        f"saved_schedule:{created.id}"
    ).enabled

    await service.schedules.delete(created.id)
    assert await service.schedules.all() == []
    await service.stop()


@pytest.mark.parametrize(
    ("art", "themes", "expected"),
    [
        (True, False, [("art", "1")]),
        (False, True, [("themes", "1")]),
        (True, True, [("art", "1"), ("themes", "1")]),
    ],
)
async def test_bulk_assets_schedule_runs_selected_jobs(
    monkeypatch: pytest.MonkeyPatch,
    art: bool,
    themes: bool,
    expected: list[tuple[str, str]],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    service = _bulk_schedule_service(app_config=app_config, database=database)
    started: list[tuple[str, str]] = []

    async def fake_run_art(
        _context: JobContext,
        params: BulkMatchArtRequest,
        *_deps: object,
        **_kwargs: object,
    ) -> None:
        started.append(("art", params.library_ids[0]))
        await asyncio.sleep(0)

    async def fake_run_themes(
        _context: JobContext,
        params: BulkThemeRequest,
        *_deps: object,
        **_kwargs: object,
    ) -> None:
        started.append(("themes", params.library_ids[0]))
        await asyncio.sleep(0)

    monkeypatch.setattr(module, "run_bulk_art_match", fake_run_art)
    monkeypatch.setattr(module, "run_bulk_themes", fake_run_themes)

    schedule = await service.schedules.create(
        _assets_body("Assets", art=art, themes=themes, library_id="1")
    )

    await service.schedules.run_now(schedule.id)
    await asyncio.wait_for(service.schedules.wait_for_pending_runs(), timeout=1)

    assert sorted(started) == sorted(expected)
    await service.stop()


async def test_assets_run_now_is_refused_during_a_full_sync(
    *,
    app_config: Settings,
    database: Database,
) -> None:
    background_jobs = BackgroundJobRegistry(NullEventPublisher())
    service = _bulk_schedule_service(
        background_jobs, app_config=app_config, database=database
    )
    sync = ManagedBackgroundJob(ManagedJobLifecycle(JobKind.SYNC), NullEventPublisher())
    release = asyncio.Event()

    async def hold(_context: JobContext) -> None:
        await release.wait()

    assert background_jobs.library_gate.start("sync", sync, hold)

    with pytest.raises(PublicServiceError, match="Wait for full sync to finish"):
        service.start_run(
            BulkAssetsRequest(library_ids=["1"], art=BulkAssetsArtConfig())
        )

    assert background_jobs.art_match.running is False
    release.set()
    await sync.wait_idle()
