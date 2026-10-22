"""Library operations run one at a time; downloads stay apart from a full sync."""

lazy import asyncio
lazy from collections.abc import Callable
lazy from pathlib import Path
lazy from typing import Any

lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.jobs.gate import GateSide, LibraryGate
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import JobContext
lazy from overture.jobs.slot import ManagedBackgroundJob
lazy from overture.schemas.sync import (
    SyncRunRequest,
    SyncScheduleConfig,
    SyncScheduleWrite,
)
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.local_assets.service import LocalAssets
lazy from overture.services.scheduler import SchedulerService
lazy from overture.services.sync.engine import SyncEngine
lazy from overture.utils.errors import PublicServiceError
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    RecordingPublisher,
    unused,
)


def _job(kind: JobKind) -> ManagedBackgroundJob:
    return ManagedBackgroundJob(ManagedJobLifecycle(kind), NullEventPublisher())


def _held(release: asyncio.Event) -> Callable[[JobContext], Any]:
    async def body(_context: JobContext) -> None:
        await release.wait()

    return body


async def _finish(*jobs: ManagedBackgroundJob) -> None:
    for job in jobs:
        await job.wait_idle()


async def test_one_operation_runs_at_a_time_and_shares_the_gate_with_its_jobs() -> None:
    gate = LibraryGate()
    art, themes, scan, audit, sync = (
        _job(JobKind.BULK_ART),
        _job(JobKind.BULK_THEME),
        _job(JobKind.ASSET_SCAN),
        _job(JobKind.SERVER_AUDIT),
        _job(JobKind.SYNC),
    )
    release = asyncio.Event()

    assert gate.start("assets", art, _held(release))
    assert gate.start("assets", themes, _held(release))
    others: tuple[tuple[GateSide, ManagedBackgroundJob], ...] = (
        ("renamer", scan),
        ("audit", audit),
        ("sync", sync),
    )
    for side, job in others:
        with pytest.raises(PublicServiceError) as blocked:
            gate.start(side, job, _held(release))
        assert blocked.value.status_code == 409
        assert blocked.value.message == (
            "Wait for bulk art match, bulk theme match to finish"
        )
        assert job.running is False

    release.set()
    await _finish(art, themes)
    assert gate.start("sync", sync, _held(asyncio.Event()))
    with pytest.raises(PublicServiceError, match="Wait for full sync to finish"):
        gate.start("renamer", scan, _held(release))
    await sync.shutdown()


async def test_a_busy_slot_returns_the_gate_it_never_used() -> None:
    gate = LibraryGate()
    scan = _job(JobKind.ASSET_SCAN)
    release = asyncio.Event()
    assert gate.start("renamer", scan, _held(release))

    assert gate.start("renamer", scan, _held(release)) is False

    release.set()
    await _finish(scan)
    assert gate.blocker("sync") is None


async def test_a_scheduled_run_waits_for_the_other_side_and_reports_it() -> None:
    gate = LibraryGate()
    scan, sync = _job(JobKind.ASSET_SCAN), _job(JobKind.SYNC)
    release_scan = asyncio.Event()
    reports: list[str | None] = []
    ran: list[str] = []

    async def full_sync(_context: JobContext) -> None:
        ran.append("sync")

    assert gate.start("renamer", scan, _held(release_scan))
    waiting = asyncio.create_task(
        gate.run("sync", sync, full_sync, report=reports.append)
    )
    await asyncio.sleep(0)
    assert reports == ["asset scan"]
    assert ran == []

    release_scan.set()
    await asyncio.wait_for(waiting, timeout=1)

    assert ran == ["sync"]
    assert reports == ["asset scan", None]
    await _finish(sync)
    assert gate.blocker("renamer") is None


async def test_a_waiting_run_holds_the_gate_while_its_slot_is_busy() -> None:
    """Once the gate is free, the other side cannot slip in during the wait."""
    gate = LibraryGate()
    art, sync = _job(JobKind.BULK_ART), _job(JobKind.SYNC)
    release_manual = asyncio.Event()
    reports: list[str | None] = []

    async def scheduled(_context: JobContext) -> None:
        return None

    assert art.start_with_context(_held(release_manual))
    waiting = asyncio.create_task(
        gate.run("assets", art, scheduled, report=reports.append)
    )
    await asyncio.sleep(0)

    assert reports == ["bulk art match"]
    with pytest.raises(PublicServiceError, match="bulk art match"):
        gate.start("sync", sync, _held(asyncio.Event()))

    release_manual.set()
    await asyncio.wait_for(waiting, timeout=1)
    await _finish(art)
    assert gate.blocker("sync") is None


async def test_a_cancelled_wait_releases_the_gate() -> None:
    gate = LibraryGate()
    art = _job(JobKind.BULK_ART)
    assert art.start_with_context(_held(asyncio.Event()))
    waiting = asyncio.create_task(
        gate.run("assets", art, _held(asyncio.Event()), report=lambda _reason: None)
    )
    await asyncio.sleep(0)
    assert gate.blocker("sync") == "bulk art match"

    waiting.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiting

    assert gate.blocker("sync") is None
    await art.shutdown()


def _engine(
    gate: LibraryGate,
    publisher: RecordingPublisher,
    *,
    app_config: Settings,
    database: Database,
    config_dir: Path,
) -> SyncEngine:
    return SyncEngine(
        tmdb_client=unused(TMDBClient),
        config_dir=config_dir,
        downloads=unused(DownloadService),
        provider_registry=NoopProviderRegistry(),
        scheduler=SchedulerService(app_config=app_config),
        publisher=publisher,
        library_gate=gate,
        local_assets=unused(LocalAssets),
        app_config=app_config,
        database=database,
    )


async def test_manual_full_sync_is_refused_while_an_item_job_runs(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    gate = LibraryGate()
    engine = _engine(
        gate,
        RecordingPublisher(),
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )
    scan = _job(JobKind.ASSET_SCAN)
    release = asyncio.Event()
    assert gate.start("renamer", scan, _held(release))

    with pytest.raises(PublicServiceError, match="Wait for asset scan to finish"):
        engine.run_sync(SyncRunRequest())

    assert engine.job.running is False
    release.set()
    await _finish(scan)


async def test_queued_and_waiting_schedules_report_why_and_announce_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    gate = LibraryGate()
    publisher = RecordingPublisher()
    engine = _engine(
        gate,
        publisher,
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )
    ran: list[str] = []

    def full_sync(library_ids: list[str] | None) -> Callable[[JobContext], Any]:
        async def body(_context: JobContext) -> None:
            ran.append(",".join(library_ids or []))

        return body

    monkeypatch.setattr(engine, "_full_sync", full_sync)
    first, second = [
        await engine.schedules.create(body)
        for body in (
            SyncScheduleWrite(
                name=name,
                cron_expression="0 3 * * *",
                config=SyncScheduleConfig(library_ids=[name]),
            )
            for name in ("First", "Second")
        )
    ]
    scan = _job(JobKind.ASSET_SCAN)
    release = asyncio.Event()
    assert gate.start("renamer", scan, _held(release))

    await engine.schedules.run_now(first.id)
    await engine.schedules.run_now(second.id)

    async def first_waits_and_second_queues() -> bool:
        statuses = {
            schedule.name: (schedule.run_status, schedule.waiting_for)
            for schedule in await engine.schedules.all()
        }
        return statuses == {
            "First": ("waiting", "asset scan"),
            "Second": ("queued", "First"),
        }

    async with asyncio.timeout(2):
        await publisher.wait_until(first_waits_and_second_queues)

    release.set()
    await asyncio.wait_for(engine.schedules.wait_for_pending_runs(), timeout=2)
    await engine.schedules.stop()

    assert ran == ["First", "Second"]
    assert {schedule.run_status for schedule in await engine.schedules.all()} == {
        "idle"
    }
    assert ("schedules.changed", {"kind": "sync"}) in publisher.events


async def test_library_gate_hold_and_release() -> None:
    gate = LibraryGate()
    assert gate.blocker("sync") is None
    assert gate.blocker("renamer") is None

    release = gate.hold("downloads", "downloads")
    assert gate.blocker("sync") == "downloads"
    assert gate.blocker("renamer") is None
    assert gate.blocker("assets") is None

    sync = _job(JobKind.SYNC)
    with pytest.raises(PublicServiceError, match="Wait for downloads to finish"):
        gate.start("sync", sync, _held(asyncio.Event()))

    release()
    assert gate.blocker("sync") is None
    release()
    assert gate.blocker("sync") is None


async def test_library_gate_wait_for() -> None:
    gate = LibraryGate()
    sync = _job(JobKind.SYNC)
    release_sync = asyncio.Event()

    assert gate.start("sync", sync, _held(release_sync))
    assert gate.blocker("downloads") == "full sync"

    waited = False

    async def waiter() -> None:
        nonlocal waited
        await gate.wait_for("downloads")
        waited = True

    task = asyncio.create_task(waiter())
    await asyncio.sleep(0)
    assert waited is False

    release_sync.set()
    await sync.wait_idle()
    await task
    assert waited is True
