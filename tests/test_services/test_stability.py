"""Ownership regressions for cancellation, bounded work and process failure."""

lazy import asyncio
lazy import os
lazy import sys
lazy import threading
lazy import time
lazy from concurrent.futures import ThreadPoolExecutor
lazy from pathlib import Path
lazy from typing import override

lazy import pytest

lazy from overture.config import Settings
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import JobContext
lazy from overture.jobs.slot import ManagedBackgroundJob
lazy from overture.services.art import phash as phash_module
lazy from overture.services.art.phash import PhashService
lazy from overture.utils.cache import AsyncMemoizer
lazy from overture.utils.process import run_process
lazy from overture.utils.threads import owned_thread
lazy from overture.ws.connection_manager import ConnectionManager
lazy from tests.conftest import FakeWebSocket
lazy from tests.runtime_helpers import RecordingPublisher


def _dead_worker(_data: bytes) -> str:
    os._exit(7)


def _worker_pid(_data: bytes) -> str:
    return str(os.getpid())


def _slow_worker(data: bytes) -> str:
    Path(os.fsdecode(data)).touch()
    time.sleep(30)
    return "0" * 16


async def test_cancelled_thread_keeps_ownership_until_work_finishes() -> None:
    entered = threading.Event()
    release = threading.Event()

    def work() -> int:
        entered.set()
        release.wait(5)
        return 42

    task = asyncio.create_task(owned_thread(work))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        release.set()


async def test_cancelled_hash_retains_admission_until_executor_finishes(
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
) -> None:
    app_config.PHASH_WORKERS = 1
    release = threading.Event()
    started = threading.Event()
    calls: list[bytes] = []

    def compute(data: bytes) -> str:
        calls.append(data)
        started.set()
        release.wait(5)
        return "0" * 16

    monkeypatch.setattr(phash_module, "compute_phash_from_bytes", compute)
    service = PhashService(app_config=app_config, executor=ThreadPoolExecutor(1))
    first = asyncio.create_task(service.compute_from_bytes(b"image"))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        second = asyncio.create_task(service.compute_from_bytes(b"second"))
        await asyncio.sleep(0.05)
        # The cancelled hash still runs on the only worker; nothing else starts.
        assert calls == [b"image"]
        release.set()
        assert await second == "0" * 16
        assert calls == [b"image", b"second"]
    finally:
        release.set()
        await service.close()


@pytest.mark.parametrize("failure", ["death", "timeout"])
async def test_phash_pool_failure_retires_pool_and_allows_subsequent_work(
    failure: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
) -> None:
    original = phash_module.compute_phash_from_bytes
    service = PhashService(app_config=app_config)
    try:
        # Warm the spawned worker before measuring execution timeout.
        monkeypatch.setattr(phash_module, "compute_phash_from_bytes", _worker_pid)
        assert int(await service.compute_from_bytes(b"image")) != os.getpid()
        monkeypatch.setattr(
            phash_module,
            "compute_phash_from_bytes",
            _dead_worker if failure == "death" else _slow_worker,
        )
        monkeypatch.setattr(phash_module, "PHASH_TIMEOUT_SECONDS", 1)
        started = tmp_path / "started"
        start = time.monotonic()
        with pytest.raises(OSError, match="pHash worker failed"):
            await service.compute_from_bytes(os.fsencode(started))
        assert time.monotonic() - start < 10
        if failure == "timeout":
            assert started.exists()
        monkeypatch.setattr(phash_module, "compute_phash_from_bytes", original)
        monkeypatch.setattr(phash_module, "PHASH_TIMEOUT_SECONDS", 30)
        # An invalid image is an operation failure, not another broken pool.
        with pytest.raises(OSError, match="cannot identify image"):
            await service.compute_from_bytes(b"not an image")
        assert service.healthy
    finally:
        await service.close()


@pytest.mark.parametrize("tasks_per_worker", [None, 2])
async def test_phash_pool_recycles_workers(
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    tasks_per_worker: int | None,
) -> None:
    app_config.PHASH_WORKERS = 1
    if tasks_per_worker is not None:
        monkeypatch.setattr(phash_module, "PHASH_TASKS_PER_WORKER", tasks_per_worker)
    monkeypatch.setattr(phash_module, "compute_phash_from_bytes", _worker_pid)
    service = PhashService(app_config=app_config)
    try:
        first = await service.compute_from_bytes(b"image")
        for _ in range(phash_module.PHASH_TASKS_PER_WORKER - 1):
            assert await service.compute_from_bytes(b"image") == first
        assert await service.compute_from_bytes(b"image") != first
    finally:
        await service.close()


async def test_finalization_holds_slot_until_terminal_projection_is_saved() -> None:
    entering = asyncio.Event()
    release = asyncio.Event()

    class Publisher(RecordingPublisher):
        @override
        async def broadcast(self, event, payload=None, *, before_publish=None) -> None:
            entering.set()
            await release.wait()
            await super().broadcast(event, payload, before_publish=before_publish)

    slot = ManagedBackgroundJob(ManagedJobLifecycle(JobKind.BULK_ART), Publisher())

    async def run(_context: JobContext) -> None:
        raise LookupError("unexpected")

    assert slot.start_with_context(run)
    await entering.wait()
    assert slot.running
    assert not slot.start_with_context(run)
    release.set()
    await slot.wait_idle()
    assert slot.last_event == "match.failed"
    await slot.shutdown()


async def test_memoizer_bounds_distinct_work_and_closes_cancelled_waiters() -> None:
    memoizer: AsyncMemoizer[int] = AsyncMemoizer()
    started = 0
    saturated = asyncio.Event()

    async def compute() -> int:
        nonlocal started
        started += 1
        if started == 32:
            saturated.set()
        await asyncio.Event().wait()
        return 1

    tasks = [
        asyncio.create_task(memoizer.get_or_compute(index, compute))
        for index in range(40)
    ]
    await saturated.wait()
    assert started == 32
    await memoizer.close()
    results = await asyncio.gather(*tasks, return_exceptions=True)
    assert all(
        isinstance(result, (asyncio.CancelledError, RuntimeError)) for result in results
    )


async def test_slow_websocket_cannot_block_publish_and_overflow_disconnects(
    fake_websocket_factory: type[FakeWebSocket],
) -> None:
    closed = asyncio.Event()

    class Socket(fake_websocket_factory):
        @override
        async def send_text(self, payload: str) -> None:
            await asyncio.Event().wait()

        @override
        async def close(
            self, code: int | None = None, reason: str | None = None
        ) -> None:
            closed.set()

    socket = Socket()
    manager = ConnectionManager()
    await manager.connect(socket)
    await asyncio.sleep(0)
    async with asyncio.timeout(1):
        for index in range(130):
            await manager.broadcast("test", index)
        await closed.wait()
    assert manager.active_connections == 0
    await manager.close()


async def test_process_timeout_reaps_child_tree(tmp_path: Path) -> None:
    marker = tmp_path / "child-survived"
    child = (
        "import pathlib,time; time.sleep(1); "
        f"pathlib.Path({str(marker)!r}).touch(); time.sleep(20)"
    )
    parent = (
        "import subprocess,sys,time; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}]); "
        "print('ready',flush=True); time.sleep(20)"
    )
    with pytest.raises(TimeoutError):
        await run_process([sys.executable, "-c", parent], deadline=0.4)
    await asyncio.sleep(1)
    assert not marker.exists()


async def test_process_reaps_descendant_after_parent_exits(tmp_path: Path) -> None:
    marker = tmp_path / "orphan-survived"
    child = f"import pathlib,time; time.sleep(1); pathlib.Path({str(marker)!r}).touch()"
    parent = (
        "import subprocess,sys; "
        f"subprocess.Popen([sys.executable,'-c',{child!r}], "
        "stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"
    )
    result = await run_process([sys.executable, "-c", parent], deadline=3)
    assert result.returncode == 0
    await asyncio.sleep(1.1)
    assert not marker.exists()


async def test_process_drains_pipes_when_progress_delivery_fails() -> None:
    async def fail(_line: str) -> None:
        raise ValueError("transport failed")

    result = await run_process(
        [
            sys.executable,
            "-c",
            "import sys; print('progress'); sys.stderr.write('x'*200000)",
        ],
        deadline=5,
        on_line=fail,
        capture=False,
    )
    assert result.returncode == 0
    assert len(result.error_tail) <= 16 * 1024
