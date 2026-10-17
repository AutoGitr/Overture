"""Stopping a run: exactly one terminal event, and a slot that always frees.

Five features share one job slot, and the browser leaves its "running" view
only when a terminal event arrives. Both halves of that promise are tested
here rather than through each runner: the body publishes its own terminal
event when it cooperates, and the slot publishes one when it does not.
"""

lazy import asyncio
lazy from typing import Any

lazy import pytest

lazy from overture.jobs import slot as slot_module
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import JobContext, run_managed_job
lazy from overture.jobs.slot import ManagedBackgroundJob
lazy from overture.jobs.tally import SyncTally
lazy from tests.runtime_helpers import RecordingPublisher

SYNC = ManagedJobLifecycle(JobKind.SYNC)


def _slot(publisher: RecordingPublisher) -> ManagedBackgroundJob:
    return ManagedBackgroundJob(SYNC, publisher)


def _terminal(publisher: RecordingPublisher, event: str) -> dict[str, Any]:
    """Return the single payload published for one terminal event name."""
    payloads = publisher.payloads(event)
    assert len(payloads) == 1, publisher.names()
    return payloads[0]


async def test_a_cooperative_body_publishes_one_stopped_event() -> None:
    running = asyncio.Event()
    publisher = RecordingPublisher()
    slot = _slot(publisher)

    async def body(context: JobContext) -> None:
        async with run_managed_job(context, SyncTally()) as job:
            await job.started(total=2)
            running.set()
            await context.stop_event.wait()

    assert slot.start_with_context(body) is True
    task = slot.task
    assert task is not None
    await running.wait()

    assert slot.request_stop() is True
    await slot.wait_idle()

    assert publisher.names() == ["sync.started", "sync.stopped"]
    assert slot.running is False


async def test_a_body_that_ignores_the_stop_flag_is_cancelled_and_still_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A run parked in a call that never returns must not keep the slot.

    The flag alone cannot end that run, and without the terminal event the
    view stays on "running" with a timer counting up forever.
    """
    running = asyncio.Event()
    publisher = RecordingPublisher()
    monkeypatch.setattr(slot_module, "STOP_GRACE_SECONDS", 0.01)
    slot = _slot(publisher)

    async def body(context: JobContext) -> None:
        async with run_managed_job(context, SyncTally()) as job:
            await job.started()
            await job.planned(4)
            job.tally.done = 1
            await job.progress()
            running.set()
            await asyncio.Event().wait()

    assert slot.start_with_context(body) is True
    task = slot.task
    assert task is not None
    await running.wait()

    assert slot.request_stop() is True
    async with asyncio.timeout(1):
        await slot.wait_idle()

    assert slot.running is False
    assert task.cancelled() is True
    payload = _terminal(publisher, "sync.stopped")
    assert payload["job"]["status"] == "stopped"
    # The counters the user was watching survive the cancellation.
    assert payload["done"] == 1
    assert payload["total"] == 4
    assert payload["finished_at"]


async def test_a_body_that_raises_past_its_guard_reports_failed_once() -> None:
    publisher = RecordingPublisher()
    slot = _slot(publisher)

    async def body(_context: JobContext) -> None:
        raise TypeError("bad wiring")

    assert slot.start_with_context(body) is True
    task = slot.task
    assert task is not None
    await slot.wait_idle()

    assert publisher.names() == ["sync.failed"]
    assert _terminal(publisher, "sync.failed")["job"]["error"]["message"]
    assert slot.running is False


async def test_a_run_that_ended_on_its_own_is_not_reported_twice() -> None:
    """The slot publishes only for a run that never reached a terminal event."""
    publisher = RecordingPublisher()
    slot = _slot(publisher)

    async def body(context: JobContext) -> None:
        async with run_managed_job(context, SyncTally()) as job:
            await job.started(total=0)

    assert slot.start_with_context(body) is True
    task = slot.task
    assert task is not None
    await slot.wait_idle()

    assert publisher.names() == ["sync.started", "sync.completed"]


def test_stopping_an_idle_slot_reports_that_nothing_was_running() -> None:
    slot = _slot(RecordingPublisher())

    assert slot.request_stop() is False
    assert slot.stop_requested is False


async def test_shutdown_returns_once_a_cancelled_run_has_reported() -> None:
    """Shutdown waits for the run's teardown without spinning on finished work."""
    publisher = RecordingPublisher()
    slot = _slot(publisher)

    async def forever(_context: JobContext) -> None:
        await asyncio.Event().wait()

    assert slot.start_with_context(forever)

    async with asyncio.timeout(5):
        await slot.shutdown()

    assert slot.running is False
    assert publisher.names() == ["sync.stopped"]
