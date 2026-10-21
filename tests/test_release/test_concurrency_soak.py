"""Sustained concurrency checks for shared runtime resources."""

lazy import asyncio
lazy import os
lazy import sqlite3
lazy import time
lazy from collections.abc import Mapping
lazy from pathlib import Path
lazy from typing import Any, cast

lazy import pytest
lazy from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
lazy from sqlmodel import func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture import protocols
lazy from overture.db import metadata
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import as_writer, configure_sqlite
lazy from overture.domain import MediaType
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import JobContext, run_managed_job
lazy from overture.jobs.slot import ManagedBackgroundJob
lazy from overture.jobs.tally import SyncTally
lazy from overture.schemas.backup import BackupRetention
lazy from overture.services.backup.files import BackupStore
lazy from overture.utils.types import JsonValue
lazy from overture.ws.connection_manager import ConnectionManager
lazy from tests.runtime_helpers import RecordingPublisher, database_for


def _rounds(default: int) -> int:
    rounds = int(os.environ.get("OVERTURE_SOAK_ROUNDS", default))
    if rounds < 1:
        raise ValueError("OVERTURE_SOAK_ROUNDS must be positive")
    return rounds


async def test_concurrent_writes_reads_and_live_backups_remain_consistent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rounds = _rounds(25)
    workers = 8
    db_path = tmp_path / "overture.db"
    engine = configure_sqlite(create_async_engine(f"sqlite+aiosqlite:///{db_path}"))
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    writers = async_sessionmaker(
        as_writer(engine), class_=AsyncSession, expire_on_commit=False
    )
    database = database_for(writers)
    readers = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    backup_dir = tmp_path / "backups"
    backup_store = BackupStore(db_path, backup_dir)
    stop_reading = asyncio.Event()
    observed_counts: list[int] = []

    async def write(worker: int) -> None:
        for iteration in range(rounds):
            async with database.write_session() as session:
                session.add(
                    MediaItem(
                        media_type=MediaType.MOVIE,
                        title=f"Movie {worker}-{iteration}",
                        server_item_id=f"{worker}-{iteration}",
                    )
                )
            await asyncio.sleep(0)

    async def read() -> None:
        while not stop_reading.is_set():
            async with readers() as session:
                observed_counts.append(
                    (
                        await session.exec(select(func.count()).select_from(MediaItem))
                    ).one()
                )
            await asyncio.sleep(0)

    async def backup() -> None:
        for _ in range(3):
            await backup_store.create(retention=BackupRetention())
            await asyncio.sleep(0)

    reader = asyncio.create_task(read())
    started = time.perf_counter()
    try:
        await asyncio.gather(
            *(write(worker) for worker in range(workers)),
            backup(),
        )
        final_backup = await backup_store.create(retention=BackupRetention())
    finally:
        stop_reading.set()
        await reader

    try:
        async with readers() as session:
            final_count = (
                await session.exec(select(func.count()).select_from(MediaItem))
            ).one()
        assert final_count == workers * rounds
        assert observed_counts == sorted(observed_counts)
        assert time.perf_counter() - started <= 20

        restored = sqlite3.connect(backup_dir / final_backup)
        try:
            assert restored.execute("PRAGMA quick_check").fetchone() == ("ok",)
            assert restored.execute("SELECT count(*) FROM media_items").fetchone() == (
                final_count,
            )
        finally:
            restored.close()
    finally:
        await engine.dispose()


async def test_managed_jobs_release_their_slots_through_repeated_cancellation() -> None:
    for _ in range(_rounds(50)):
        publisher = RecordingPublisher()
        slot = ManagedBackgroundJob(
            ManagedJobLifecycle(JobKind.SYNC),
            publisher=publisher,
        )
        running = asyncio.Event()

        assert slot.start_with_context(_cooperative_job(running))
        await running.wait()
        assert slot.request_stop()
        async with asyncio.timeout(2):
            await slot.wait_idle()

        terminal = [
            name
            for name, _payload in publisher.events
            if name in {"sync.completed", "sync.failed", "sync.stopped"}
        ]
        assert terminal == ["sync.stopped"]
        assert not slot.running


class _Client:
    def __init__(self, fail_after: int | None = None) -> None:
        self.fail_after = fail_after
        self.accepted = False
        self.messages: list[str] = []

    async def close(self, code: int = 1000) -> None:
        pass

    async def accept(self) -> None:
        self.accepted = True

    async def send_text(self, data: str) -> None:
        if self.fail_after is not None and len(self.messages) >= self.fail_after:
            raise RuntimeError("connection closed")
        self.messages.append(data)

    async def send_json(self, data: Any) -> None:
        await self.send_text(str(data))


class _Snapshot:
    def capture(self) -> Mapping[str, Any]:
        return {}

    async def gather(self) -> Mapping[str, Any]:
        return {}

    def finish(
        self,
        captured: Mapping[str, Any],
        gathered: Mapping[str, Any],
        epoch: str,
        sequence: int,
    ) -> dict[str, JsonValue]:
        _ = captured, gathered
        return cast(
            "dict[str, JsonValue]",
            {"epoch": epoch, "sequence": sequence, "jobs": []},
        )


async def test_broadcast_and_reconnect_soak_drops_only_failed_clients() -> None:
    manager = ConnectionManager()
    clients = [_Client(fail_after=5 if index % 7 == 0 else None) for index in range(24)]
    for client in clients:
        await manager.connect(cast("protocols.ClientConnection", client))

    broadcasts = _rounds(100)
    for sequence in range(broadcasts):
        await manager.broadcast("sync.progress", {"done": sequence})
        await asyncio.sleep(0)

    healthy = [client for client in clients if client.fail_after is None]
    assert manager.sequence == broadcasts
    assert manager.active_connections == len(healthy)
    assert all(len(client.messages) == broadcasts for client in healthy)

    reconnected = _Client()
    await manager.connect(cast("protocols.ClientConnection", reconnected))
    await manager.send_realtime_snapshot(
        cast("protocols.ClientConnection", reconnected), _Snapshot()
    )
    await asyncio.sleep(0)
    assert '"event": "realtime.snapshot"' in reconnected.messages[-1]

    for client in [*clients, reconnected]:
        manager.disconnect(cast("protocols.ClientConnection", client))
    await manager.close()
    assert manager.active_connections == 0


def _cooperative_job(running: asyncio.Event):
    async def body(context: JobContext) -> None:
        async with run_managed_job(context, SyncTally()) as job:
            await job.started(total=1)
            running.set()
            await context.stop_event.wait()

    return body
