"""Backup orchestration, persisted schedules and failure events."""

lazy import asyncio
lazy from contextlib import asynccontextmanager
lazy from pathlib import Path
lazy from typing import Any
lazy from unittest.mock import AsyncMock

lazy import pytest
lazy from fastapi import FastAPI
lazy from sqlalchemy.exc import SQLAlchemyError
lazy from sqlalchemy.ext.asyncio import async_sessionmaker
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.jobs.kinds import INTERRUPTED_MESSAGE, JobKind
lazy from overture.runtime import RuntimeServices
lazy from overture.schemas.backup import BackupRetention, BackupScheduleUpdate
lazy from overture.services import job_results
lazy from overture.services.backup import service as backup_module
lazy from overture.services.backup.events import BackupEvents
lazy from overture.services.backup.files import (
    BackupInProgressError,
    BackupStore,
)
lazy from overture.services.backup.service import BackupService
lazy from overture.services.realtime import RealtimeSnapshotBuilder
lazy from overture.services.scheduler import ScheduledJobInfo, SchedulerService
lazy from overture.services.storage.image_cache import ImageCache
lazy from overture.utils.errors import PublicServiceError
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    RecordingPublisher,
    database_for,
    make_image_cache,
)


def _store(tmp_path: Path) -> BackupStore:
    return BackupStore(tmp_path / "overture.db", tmp_path / "backups")


@pytest.mark.parametrize("retention_fails", [False, True])
async def test_scheduled_backup_is_independent_of_retention(
    retention_fails: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    publisher = RecordingPublisher()
    scheduler = SchedulerService(app_config=app_config)
    service = BackupService(
        scheduler=scheduler,
        events=BackupEvents(publisher),
        store=_store(tmp_path),
        image_cache=make_image_cache(app_config),
        app_config=app_config,
        database=database,
    )
    operations: list[str] = []

    async def create(
        *, retention: BackupRetention, reject_if_busy: bool = False
    ) -> str:
        assert retention == BackupRetention()
        assert not reject_if_busy
        assert publisher.names() == ["backup.started"]
        operations.append("backup")
        return "backup.db"

    async def retention(*, database: Database, image_cache: ImageCache) -> None:
        del image_cache
        assert operations == ["backup"]
        assert publisher.names() == ["backup.started"]
        operations.append("retention")
        if retention_fails:
            raise SQLAlchemyError("retention failed")

    monkeypatch.setattr(service.store, "create", create)
    monkeypatch.setattr(backup_module, "run_retention_pass", retention)
    await service.update_schedule(BackupScheduleUpdate(enabled=True))
    await scheduler.trigger_job("auto_backup")
    terminal = "backup.completed"
    assert operations == ["backup"]
    assert publisher.names() == ["backup.started", terminal]
    assert service.events.job.last_event == terminal
    payload = publisher.payloads(terminal)[0]
    assert payload["scheduled"] is True
    assert payload["job"]["id"] == "backup:scheduled"


async def test_manual_backup_rejects_busy_storage_with_409(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    publisher = RecordingPublisher()
    service = BackupService(
        scheduler=SchedulerService(app_config=app_config),
        events=BackupEvents(publisher),
        store=_store(tmp_path),
        image_cache=make_image_cache(app_config),
        app_config=app_config,
        database=database,
    )

    async def create(
        *, retention: BackupRetention, reject_if_busy: bool = False
    ) -> str:
        del retention
        assert reject_if_busy
        raise BackupInProgressError("busy")

    monkeypatch.setattr(service.store, "create", create)
    with pytest.raises(PublicServiceError) as raised:
        await service.backup_now()
    assert raised.value.status_code == 409
    assert publisher.names() == ["backup.started", "backup.failed"]
    assert service.events.job.last_event == "backup.failed"


@pytest.fixture
def image_cache(app_config: Settings) -> ImageCache:
    return make_image_cache(app_config)


@pytest.fixture
def backup_service(
    tmp_path: Path,
    app_config: Settings,
    database: Database,
    image_cache: ImageCache,
) -> BackupService:
    return BackupService(
        scheduler=SchedulerService(app_config=app_config),
        events=BackupEvents(RecordingPublisher()),
        store=_store(tmp_path),
        image_cache=image_cache,
        app_config=app_config,
        database=database,
    )


async def test_manual_backup_success_announces_and_lists_the_saved_file(
    backup_service: BackupService, monkeypatch: pytest.MonkeyPatch
) -> None:
    publisher = RecordingPublisher()
    backup_service.events = BackupEvents(publisher)
    create = AsyncMock(return_value="overture_20260101_030000.db")
    monkeypatch.setattr(backup_service.store, "create", create)
    backup_service.store.directory.mkdir()
    (backup_service.store.directory / "overture_20260101_030000.db").write_bytes(
        b"backup"
    )

    response = await backup_service.backup_now()

    assert response.filename == "overture_20260101_030000.db"
    create.assert_awaited_once_with(retention=BackupRetention(), reject_if_busy=True)
    assert publisher.names() == ["backup.started", "backup.completed"]
    completed = publisher.payloads("backup.completed")[0]
    assert completed["scheduled"] is False
    assert completed["filename"] == response.filename
    assert (
        completed["started_at"] == publisher.payloads("backup.started")[0]["started_at"]
    )
    assert completed["finished_at"] is not None
    assert [entry.filename for entry in backup_service.list_backups().backups] == [
        response.filename
    ]


@pytest.mark.parametrize("cancel", [False, True])
async def test_inflight_backup_snapshot_and_durable_terminal_state(
    backup_service: BackupService,
    database: Database,
    test_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    *,
    cancel: bool,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()

    async def create(**_kwargs: Any) -> str:
        entered.set()
        await release.wait()
        return "backup.db"

    monkeypatch.setattr(backup_service.store, "create", create)
    runtime: RuntimeServices = test_app.state.runtime
    runtime.backups = backup_service
    builder = RealtimeSnapshotBuilder(runtime)
    task = asyncio.create_task(backup_service.backup_now())
    stopping: asyncio.Task[None] | None = None
    try:
        await asyncio.wait_for(entered.wait(), timeout=2)
        [snapshot] = builder.capture()["jobs"]
        assert snapshot.event == "backup.progress"
        with pytest.raises(PublicServiceError) as raised:
            await backup_service.backup_now()
        assert raised.value.status_code == 409
        stopping = asyncio.create_task(backup_service.stop())
        await asyncio.sleep(0)
        assert not stopping.done()
        if cancel:
            task.cancel()
        else:
            release.set()
        await asyncio.gather(task, return_exceptions=True)
        await stopping
        latest = (await job_results.latest_runs(database))[JobKind.BACKUP]
        assert latest.event == ("backup.stopped" if cancel else "backup.completed")
        assert latest.finished_at is not None
        [snapshot] = builder.capture()["jobs"]
        assert snapshot.event == latest.event
        if cancel:
            assert latest.summary["job"]["error"] == {"message": INTERRUPTED_MESSAGE}
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        if stopping is not None:
            await stopping


@pytest.mark.parametrize("scheduled", [False, True])
@pytest.mark.parametrize(
    "failure", [OSError("disk unavailable"), SQLAlchemyError("database unavailable")]
)
async def test_backup_failure_is_announced_and_manual_calls_raise(
    backup_service: BackupService,
    monkeypatch: pytest.MonkeyPatch,
    scheduled: bool,
    failure: Exception,
) -> None:
    publisher = RecordingPublisher()
    backup_service.events = BackupEvents(publisher)
    monkeypatch.setattr(backup_service.store, "create", AsyncMock(side_effect=failure))
    await backup_service.update_schedule(BackupScheduleUpdate(enabled=True))
    if scheduled:
        await backup_service.scheduler.trigger_job("auto_backup")
    else:
        with pytest.raises(PublicServiceError) as raised:
            await backup_service.backup_now()
        assert raised.value.status_code == 500
        assert raised.value.__cause__ is failure
    assert publisher.names() == ["backup.started", "backup.failed"]
    event = publisher.payloads("backup.failed")[0]
    assert event["scheduled"] is scheduled
    assert event["job"]["error"]["message"] == str(failure)
    assert backup_service.events.job.last_event == "backup.failed"


async def test_pre_upgrade_backup_never_applies_retention(
    backup_service: BackupService, monkeypatch: pytest.MonkeyPatch
) -> None:
    create = AsyncMock(return_value="before-upgrade.db")
    monkeypatch.setattr(backup_service.store, "create", create)
    await backup_service.backup_before_upgrade()
    create.assert_awaited_once_with(retention=None)
    assert backup_service.events.job.last_event is None


async def test_start_restores_schedule_and_registers_independent_retention(
    backup_service: BackupService,
    image_cache: ImageCache,
    monkeypatch: pytest.MonkeyPatch,
    database: Database,
    app_config: Settings,
) -> None:
    retention = BackupRetention(latest=3, daily=2, weekly=1, monthly=0)
    await backup_service.update_schedule(
        BackupScheduleUpdate(
            enabled=True, cron_expression="0 4 * * *", retention=retention
        )
    )
    backup_service.scheduler = SchedulerService(app_config=app_config)
    prune = AsyncMock()
    close = AsyncMock()
    monkeypatch.setattr(backup_module, "run_retention_pass", prune)
    monkeypatch.setattr(backup_service.store, "close", close)

    await backup_service.start()
    saved = await backup_service.get_schedule()
    assert saved.enabled is True
    assert saved.cron_expression == "0 4 * * *"
    assert saved.retention == retention
    assert saved.next_run is not None
    await backup_service.scheduler.trigger_job("retention")
    prune.assert_awaited_once_with(database=database, image_cache=image_cache)

    disabled = await backup_service.update_schedule(BackupScheduleUpdate(enabled=False))
    assert disabled.enabled is False
    assert disabled.next_run is None
    assert disabled.retention == retention
    assert not backup_service.get_schedule_info().enabled
    await backup_service.stop()
    close.assert_awaited_once_with()


async def test_backup_update_schedule_validates_and_applies_saved_values(
    tmp_path: Path,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    applied: list[tuple[bool, str]] = []

    @asynccontextmanager
    async def session_factory():
        async with isolated_session_factory() as session:
            yield session

    def record_schedule(
        _job_id: str, *, enabled: bool, cron_expression: str, **_kwargs: Any
    ) -> bool:
        applied.append((enabled, cron_expression))
        return enabled

    events = BackupEvents(NullEventPublisher())
    store = BackupStore(tmp_path / "overture.db", tmp_path / "backups")
    database = database_for(session_factory)
    scheduler = SchedulerService(app_config=app_config)
    backup_service = BackupService(
        scheduler=scheduler,
        events=events,
        store=store,
        image_cache=make_image_cache(app_config),
        app_config=app_config,
        database=database,
    )
    monkeypatch.setattr(scheduler, "set_cron_job", record_schedule)
    monkeypatch.setattr(
        backup_service,
        "get_schedule_info",
        lambda: ScheduledJobInfo(enabled=True, next_run="2026-01-01T03:00:00+00:00"),
    )

    updated = await backup_service.update_schedule(
        BackupScheduleUpdate(
            enabled=True,
            cron_expression="0 3 * * *",
            retention=BackupRetention(latest=5, monthly=0),
        ),
    )

    assert updated.enabled is True
    assert updated.retention == BackupRetention(latest=5, monthly=0)
    assert updated.next_run == "2026-01-01T03:00:00+00:00"
    assert applied == [(True, "0 3 * * *")]
