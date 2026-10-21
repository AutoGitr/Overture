"""Bulk assets route background job gate behavior."""

lazy from typing import override

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.domain import ArtBulkSource, ArtType, RecentUnit, ThemeBulkSource
lazy from overture.routers import bulk_assets
lazy from overture.schemas.bulk import (
    BulkAssetsArtConfig,
    BulkAssetsRequest,
    BulkAssetsRunResponse,
    BulkAssetsScheduleWrite,
    BulkAssetsStopRequest,
    BulkAssetsThemeConfig,
)
lazy from overture.schemas.common import Status, StatusResponse
lazy from tests.runtime_helpers import NoopAssets, RecordingSchedules


async def test_bulk_assets_start_reports_per_asset_status(
    *, app_config: Settings, database: Database
) -> None:
    class FakeBulkSchedules(NoopAssets):
        @override
        def start_run(self, params: BulkAssetsRequest) -> BulkAssetsRunResponse:
            return BulkAssetsRunResponse(
                art="started",
                themes="already_running",
            )

    service = FakeBulkSchedules(app_config=app_config)

    response = await bulk_assets.start_bulk_assets(
        BulkAssetsRequest(
            library_ids=["movies"],
            art=BulkAssetsArtConfig(),
            themes=BulkAssetsThemeConfig(),
        ),
        service,
    )

    assert response.art == "started"
    assert response.themes == "already_running"


async def test_bulk_assets_stop_requests_all_asset_jobs(
    *, app_config: Settings, database: Database
) -> None:
    bodies: list[BulkAssetsStopRequest] = []

    class FakeBulkSchedules(NoopAssets):
        @override
        def stop_run(self, params: BulkAssetsStopRequest) -> StatusResponse:
            bodies.append(params)
            return StatusResponse(status=Status.STOPPING)

    service = FakeBulkSchedules(app_config=app_config)

    assert (await bulk_assets.stop_bulk_assets(service)).status == Status.STOPPING
    # Without a body every asset job is asked to stop.
    assert bodies == [BulkAssetsStopRequest(art=True, themes=True)]


async def test_bulk_assets_stop_forwards_selected_asset_jobs(
    *, app_config: Settings, database: Database
) -> None:
    bodies: list[BulkAssetsStopRequest] = []

    class FakeBulkSchedules(NoopAssets):
        @override
        def stop_run(self, params: BulkAssetsStopRequest) -> StatusResponse:
            bodies.append(params)
            return StatusResponse(status=Status.STOPPING)

    service = FakeBulkSchedules(app_config=app_config)

    response = await bulk_assets.stop_bulk_assets(
        service,
        BulkAssetsStopRequest(art=True, themes=False),
    )

    assert response.status == Status.STOPPING
    assert bodies == [BulkAssetsStopRequest(art=True, themes=False)]


def _assets_body() -> BulkAssetsScheduleWrite:
    return BulkAssetsScheduleWrite(
        name="Nightly assets",
        enabled=True,
        cron_expression="0 3 * * *",
        config=BulkAssetsRequest(
            library_ids=["1"],
            skip_recent_val=1,
            skip_recent_unit=RecentUnit.DAYS,
            art=BulkAssetsArtConfig(
                art_types=[ArtType.POSTER],
                source_order=[ArtBulkSource.LOCAL_ART_MATCHING],
            ),
            themes=BulkAssetsThemeConfig(source_order=[ThemeBulkSource.YOUTUBE_SEARCH]),
        ),
    )


async def test_bulk_assets_schedule_routes_delegate(
    *, app_config: Settings, database: Database
) -> None:
    service = NoopAssets(app_config=app_config)
    schedules = RecordingSchedules(app_config=app_config)
    service.schedules = schedules
    body = _assets_body()

    assert await bulk_assets.list_bulk_assets_schedules(service) == []
    await bulk_assets.create_bulk_assets_schedule(body, service)
    await bulk_assets.update_bulk_assets_schedule(1, body, service)
    assert (await bulk_assets.run_bulk_assets_schedule(1, service)).status == "queued"
    assert (
        await bulk_assets.delete_bulk_assets_schedule(1, service)
    ).status == "deleted"

    assert schedules.calls == [
        ("list", None),
        ("create", ("Nightly assets", body.config)),
        ("update", (1, "Nightly assets", body.config)),
        ("run", 1),
        ("delete", 1),
    ]
