"""ManagedBackgroundJob.start_when_idle: queueing behind a running job."""

lazy import asyncio

lazy import pytest

lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import JobContext
lazy from overture.jobs.slot import ManagedBackgroundJob
lazy from tests.publishers import NullEventPublisher


async def _hold(_context: JobContext, release: asyncio.Event) -> None:
    await release.wait()


async def test_start_when_idle_waits_for_the_running_job_then_starts() -> None:
    slot = ManagedBackgroundJob(
        ManagedJobLifecycle(JobKind.BULK_ART), NullEventPublisher()
    )
    release = asyncio.Event()
    started: list[str] = []

    assert slot.start_with_context(lambda context: _hold(context, release)) is True

    async def second(_context: JobContext) -> None:
        started.append("second")

    queued = asyncio.create_task(slot.start_when_idle(second))
    await asyncio.sleep(0)
    assert not queued.done(), "the second run must wait while the first holds the slot"
    assert started == []

    release.set()
    await queued
    if slot.task is not None:
        await slot.task

    assert started == ["second"]


async def test_start_when_idle_returns_immediately_for_a_free_slot() -> None:
    slot = ManagedBackgroundJob(
        ManagedJobLifecycle(JobKind.ASSET_SCAN), NullEventPublisher()
    )
    started: list[str] = []

    async def only(_context: JobContext) -> None:
        started.append("only")

    await asyncio.wait_for(slot.start_when_idle(only), timeout=1)
    if slot.task is not None:
        await slot.task

    assert started == ["only"]


async def test_run_when_idle_reports_a_cancelled_run_to_its_caller() -> None:
    slot = ManagedBackgroundJob(ManagedJobLifecycle(JobKind.SYNC), NullEventPublisher())
    started = asyncio.Event()

    async def stuck(_context: JobContext) -> None:
        started.set()
        await asyncio.Event().wait()

    waiter = asyncio.create_task(slot.run_when_idle(stuck))
    await started.wait()
    assert slot.task is not None
    slot.task.cancel()

    with pytest.raises(RuntimeError, match="sync was cancelled"):
        await asyncio.wait_for(waiter, timeout=1)
    await slot.shutdown()


async def test_run_when_idle_reports_a_failed_run() -> None:
    slot = ManagedBackgroundJob(ManagedJobLifecycle(JobKind.SYNC), NullEventPublisher())

    async def broken(_context: JobContext) -> None:
        raise OSError("disk gone")

    with pytest.raises(RuntimeError, match="sync failed") as failure:
        await asyncio.wait_for(slot.run_when_idle(broken), timeout=1)
    assert isinstance(failure.value.__cause__, OSError)
    await slot.shutdown()
