"""Coverage for sync route-facing service operations."""

lazy from pathlib import Path
lazy from typing import Any, override

lazy import pytest
lazy from pydantic import ValidationError

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.domain import IncrementalThemeOrder
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.jobs.gate import LibraryGate
lazy from overture.schemas.common import Status, StatusResponse
lazy from overture.schemas.sync import (
    SyncRunRequest,
    SyncScheduleConfig,
    SyncScheduleWrite,
)
lazy from overture.services import sync as sync_package
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.local_assets.service import LocalAssets
lazy from overture.services.scheduler import SchedulerService
lazy from overture.services.sync.engine import SyncEngine
lazy from overture.utils.errors import PublicServiceError
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import NoopProviderRegistry, unused

assert sync_package  # imported for package init coverage bookkeeping


def _schedule_request(**overrides: Any) -> SyncScheduleWrite:
    values = {
        "name": "New media",
        "enabled": True,
        "cron_expression": "*/15 * * * *",
        "config": {
            "mode": "incremental",
            "library_ids": ["1", "2"],
            "download_overturedb_art": True,
            "download_themes": "overturedb_themerrdb",
        },
        **overrides,
    }
    return SyncScheduleWrite.model_validate(values)


class FakeSyncEngine(SyncEngine):
    """A `SyncEngine` subclass whose state the test sets directly."""

    def __init__(
        self,
        *,
        can_start: bool = True,
        app_config: Settings,
        database: Database,
    ) -> None:
        super().__init__(
            tmdb_client=unused(TMDBClient),
            config_dir=unused(Path, "config_dir"),
            downloads=unused(DownloadService),
            provider_registry=NoopProviderRegistry(),
            scheduler=SchedulerService(app_config=app_config),
            publisher=NullEventPublisher(),
            library_gate=LibraryGate(),
            local_assets=unused(LocalAssets),
            app_config=app_config,
            database=database,
        )
        self.can_start = can_start
        self.started_with: dict[str, Any] | None = None

    @override
    def start_background_sync(self, *, library_ids: list[str] | None = None) -> bool:
        if not self.can_start:
            return False
        self.started_with = {"library_ids": library_ids}
        return True


def test_run_sync_returns_started_when_engine_accepts(
    *, app_config: Settings, database: Database
) -> None:
    engine = FakeSyncEngine(can_start=True, app_config=app_config, database=database)

    result = engine.run_sync(SyncRunRequest(library_ids=["1"]))

    assert result == StatusResponse(status=Status.STARTED)
    assert engine.started_with == {"library_ids": ["1"]}


def test_run_sync_returns_already_running_when_engine_declines(
    *, app_config: Settings, database: Database
) -> None:
    engine = FakeSyncEngine(can_start=False, app_config=app_config, database=database)

    result = engine.run_sync(SyncRunRequest())

    assert result == StatusResponse(status=Status.ALREADY_RUNNING)


async def test_sync_schedules_save_register_and_delete(
    *, app_config: Settings, database: Database
) -> None:
    engine = FakeSyncEngine(app_config=app_config, database=database)
    schedules = engine.schedules

    created = await schedules.create(_schedule_request())

    assert created.kind == "sync"
    assert created.name == "New media"
    assert created.config.mode == "incremental"
    assert created.config.library_ids == ["1", "2"]
    assert created.config.download_themes == "overturedb_themerrdb"
    assert created.state.checkpoint is None
    assert created.timezone == app_config.TZ
    assert created.next_run is not None

    disabled = await schedules.update(created.id, _schedule_request(enabled=False))
    assert disabled.enabled is False
    assert disabled.next_run is None
    assert [schedule.id for schedule in await schedules.all()] == [created.id]

    await schedules.delete(created.id)
    assert await schedules.all() == []
    await schedules.stop()


async def test_sync_schedules_reject_invalid_cron_and_duplicate_names(
    *, app_config: Settings, database: Database
) -> None:
    engine = FakeSyncEngine(app_config=app_config, database=database)
    schedules = engine.schedules
    await schedules.create(_schedule_request())

    with pytest.raises(ValidationError, match="cron_expression"):
        _schedule_request(name="Other", cron_expression="not-a-cron")
    with pytest.raises(PublicServiceError, match="already exists"):
        await schedules.create(_schedule_request())

    await schedules.stop()


def test_full_sync_schedules_reject_new_media_downloads() -> None:
    with pytest.raises(ValueError, match="only to incremental"):
        SyncScheduleConfig(mode="full", download_overturedb_art=True)
    with pytest.raises(ValueError, match="only to incremental"):
        SyncScheduleConfig(
            mode="full", download_themes=IncrementalThemeOrder.THEMERRDB_OVERTUREDB
        )
