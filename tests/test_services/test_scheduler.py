"""Execution and lifecycle regressions for the application scheduler."""

lazy import asyncio
lazy from collections.abc import Callable, Coroutine
lazy from dataclasses import dataclass
lazy from datetime import UTC, datetime, timedelta
lazy from typing import Any

lazy import pytest

lazy from overture.config import Settings
lazy from overture.services.scheduler import SchedulerService


@dataclass(slots=True)
class Clock:
    current: datetime

    def now(self, _tz: object) -> datetime:
        return self.current


def setter(event: asyncio.Event) -> Callable[[], Coroutine[Any, Any, None]]:
    async def run() -> None:
        event.set()

    return run


async def noop() -> None:
    return None


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    value = Clock(datetime(2026, 3, 29, 0, 30, tzinfo=UTC))
    monkeypatch.setattr("overture.services.scheduler.datetime", value)
    return value


async def test_interval_dispatch_coalesces_and_preserves_phase(
    app_config: Settings, clock: Clock
) -> None:
    app_config.TZ = "Europe/Stockholm"
    scheduler = SchedulerService(app_config=app_config)
    called = asyncio.Event()
    scheduler.set_interval_job("job", enabled=True, func=setter(called), minutes=60)
    info = scheduler.job_info("job")
    assert info.next_run == "2026-03-29T03:30:00+02:00"
    clock.current += timedelta(hours=3, seconds=20)
    scheduler.start()
    try:
        await asyncio.wait_for(called.wait(), timeout=1)
        assert scheduler.job_info("job").next_run == "2026-03-29T06:30:00+02:00"
        called.clear()
        await asyncio.sleep(0)
        assert not called.is_set()
    finally:
        await scheduler.stop()


async def test_registration_wakes_idle_loop_and_dispatches_cron(
    app_config: Settings, clock: Clock
) -> None:
    app_config.TZ = "Europe/Stockholm"
    scheduler = SchedulerService(app_config=app_config)
    called = asyncio.Event()
    scheduler.start()
    await asyncio.sleep(0)
    try:
        scheduler.set_cron_job(
            "job", enabled=True, func=setter(called), cron_expression="0 4 * * *"
        )
        assert scheduler.job_info("job").next_run == "2026-03-29T04:00:00+02:00"
        clock.current = datetime(2026, 3, 29, 2, tzinfo=UTC)
        await asyncio.wait_for(called.wait(), timeout=1)
        assert scheduler.job_info("job").next_run == "2026-03-30T04:00:00+02:00"
        scheduler.remove_job("job")
        assert not scheduler.job_info("job").enabled
    finally:
        await scheduler.stop()


@pytest.mark.parametrize("remove_first", [False, True])
async def test_replaced_job_does_not_overlap_active_callback(
    app_config: Settings, clock: Clock, *, remove_first: bool
) -> None:
    scheduler = SchedulerService(app_config=app_config)
    entered = asyncio.Event()
    replacement = asyncio.Event()

    async def callback() -> None:
        entered.set()
        await asyncio.Event().wait()

    scheduler.set_interval_job("job", enabled=True, func=callback, minutes=1)
    active = scheduler.trigger_job("job")
    assert scheduler.trigger_job("job") is active
    await asyncio.wait_for(entered.wait(), timeout=1)
    if remove_first:
        scheduler.remove_job("job")
    scheduler.set_interval_job("job", enabled=True, func=setter(replacement), minutes=1)
    clock.current += timedelta(minutes=1)
    scheduler.start()
    try:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert not replacement.is_set()
        assert scheduler.trigger_job("job") is active
        active.cancel()
        with pytest.raises(asyncio.CancelledError):
            await active
        await scheduler.trigger_job("job")
        assert replacement.is_set()
    finally:
        await scheduler.stop()


async def test_stop_cancels_callbacks_before_they_enter(app_config: Settings) -> None:
    scheduler = SchedulerService(app_config=app_config)
    entered = asyncio.Event()
    scheduler.set_interval_job("job", enabled=True, func=setter(entered), minutes=1)
    pending = scheduler.trigger_job("job")
    await scheduler.stop()
    assert pending.cancelled()
    assert not entered.is_set()
    await scheduler.stop()


async def test_failed_callback_does_not_block_next_execution(
    app_config: Settings, caplog: pytest.LogCaptureFixture
) -> None:
    scheduler = SchedulerService(app_config=app_config)

    async def fail() -> None:
        raise RuntimeError("scheduled failure")

    scheduler.set_interval_job("job", enabled=True, func=fail, minutes=1)
    try:
        for _ in range(2):
            with pytest.raises(RuntimeError, match="scheduled failure"):
                await scheduler.trigger_job("job")
        assert "Scheduled task job failed" in caplog.text
    finally:
        await scheduler.stop()


def test_invalid_replacement_preserves_registered_job(app_config: Settings) -> None:
    scheduler = SchedulerService(app_config=app_config)
    scheduler.set_cron_job("job", enabled=True, func=noop, cron_expression="0 3 * * *")
    previous = scheduler.job_info("job", include_trigger=True)
    with pytest.raises(ValueError, match="valid 5-field crontab"):
        scheduler.set_cron_job(
            "job", enabled=True, func=noop, cron_expression="0 0 31 2 *"
        )
    assert scheduler.job_info("job", include_trigger=True) == previous


@pytest.mark.parametrize("cron", [None, "0 * * * *", "* * * * *"])
@pytest.mark.parametrize("delay_minutes", [5, 6])
async def test_misfire_grace_applies_to_latest_due_occurrence(
    app_config: Settings, clock: Clock, cron: str | None, delay_minutes: int
) -> None:
    app_config.TZ = "UTC"
    clock.current = datetime(2026, 1, 1, tzinfo=UTC)
    scheduler = SchedulerService(app_config=app_config)
    called = asyncio.Event()
    if cron is None:
        scheduler.set_interval_job("job", enabled=True, func=setter(called), minutes=60)
    else:
        scheduler.set_cron_job(
            "job", enabled=True, func=setter(called), cron_expression=cron
        )
    clock.current += timedelta(hours=2, minutes=delay_minutes)
    scheduler.start()
    try:
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        assert called.is_set() == (delay_minutes == 5 or cron == "* * * * *")
    finally:
        await scheduler.stop()
