"""The application-owned scheduler and its job registration API."""

lazy import asyncio
lazy import logging
lazy from collections.abc import Callable, Coroutine
lazy from dataclasses import dataclass
lazy from datetime import UTC, datetime, timedelta
lazy from typing import Any

lazy from ..config import Settings
lazy from ..utils.cron import next_run_after, validate_cron_expression

logger = logging.getLogger(__name__)


@dataclass(slots=True, frozen=True)
class ScheduledJobInfo:
    """Stable runtime information exposed for one scheduled job."""

    enabled: bool
    next_run: str | None = None
    cron_expression: str | None = None


@dataclass(slots=True)
class ScheduledJob:
    """An in-memory registered job."""

    job_id: str
    func: Callable[[], Coroutine[Any, Any, None]]
    next_run_time: datetime
    cron_expression: str | None = None
    interval_minutes: int | None = None


class SchedulerService:
    """Application-owned background task scheduler.

    Manages and executes cron-based and interval-based background jobs
    using native asyncio without external scheduler dependencies.
    """

    def __init__(self, *, app_config: Settings) -> None:
        """Create the scheduler without starting it."""
        self._app_config = app_config
        self._jobs: dict[str, ScheduledJob] = {}
        self._closed = False
        self._callbacks: dict[str, asyncio.Task[None]] = {}
        self._wake_event = asyncio.Event()
        self._runner_task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        """Return whether the scheduler is accepting and running jobs."""
        return (
            not self._closed
            and self._runner_task is not None
            and not self._runner_task.done()
        )

    def start(self) -> None:
        """Start the scheduler once every feature has registered its jobs."""
        if self._closed:
            raise RuntimeError("Scheduler is closed")
        if self._runner_task is None or self._runner_task.done():
            self._runner_task = asyncio.create_task(
                self._run_loop(), name="overture-scheduler-loop"
            )
            logger.debug("Scheduler started")

    async def stop(self) -> None:
        """Reject new callbacks and drain every callback already entered."""
        self._closed = True
        callbacks = list(self._callbacks.values())
        if self._runner_task is not None:
            callbacks.append(self._runner_task)
        self._runner_task = None
        for task in callbacks:
            task.cancel()
        failures: list[Exception] = []
        for outcome in await asyncio.gather(*callbacks, return_exceptions=True):
            if isinstance(outcome, Exception):
                failures.append(outcome)
                logger.error(
                    "A scheduled task failed during shutdown", exc_info=outcome
                )
        if failures:
            raise RuntimeError("Scheduled callback failed during shutdown") from (
                failures[0]
            )
        logger.debug("Scheduler stopped")

    def set_cron_job(
        self,
        job_id: str,
        *,
        enabled: bool,
        func: Callable[[], Coroutine[Any, Any, None]],
        cron_expression: str,
    ) -> bool:
        """Register or disable one cron job."""
        if self._closed:
            raise RuntimeError("Scheduler is closed")
        if not enabled:
            self.remove_job(job_id)
            return False

        normalized = validate_cron_expression(cron_expression)
        next_run = next_run_after(
            normalized, datetime.now(UTC), tz=self._app_config.tzinfo
        ).astimezone(UTC)

        self._jobs[job_id] = ScheduledJob(
            job_id=job_id,
            func=func,
            cron_expression=normalized,
            next_run_time=next_run,
        )
        self._wake_event.set()
        return True

    def set_interval_job(
        self,
        job_id: str,
        *,
        enabled: bool,
        func: Callable[[], Coroutine[Any, Any, None]],
        minutes: int,
    ) -> bool:
        """Register or disable one minute-based interval job."""
        if self._closed:
            raise RuntimeError("Scheduler is closed")
        if enabled and minutes <= 0:
            raise ValueError("Scheduled interval must be positive")
        if not enabled:
            self.remove_job(job_id)
            return False

        now = datetime.now(UTC)
        next_run = now + timedelta(minutes=minutes)

        self._jobs[job_id] = ScheduledJob(
            job_id=job_id,
            func=func,
            interval_minutes=minutes,
            next_run_time=next_run,
        )
        self._wake_event.set()
        return True

    def remove_job(self, job_id: str) -> bool:
        """Remove a scheduled job if present."""
        if job_id not in self._jobs:
            return False
        del self._jobs[job_id]
        self._wake_event.set()
        return True

    def trigger_job(self, job_id: str) -> asyncio.Task[None]:
        """Trigger a registered job immediately and return its running task."""
        if self._closed:
            raise RuntimeError("Scheduler is closed")
        job = self._jobs.get(job_id)
        if job is None:
            raise KeyError(f"Job '{job_id}' not found")
        return self._dispatch(job)

    def job_info(
        self,
        job_id: str,
        *,
        include_trigger: bool = False,
    ) -> ScheduledJobInfo:
        """Return stable runtime information for one scheduled job."""
        job = self._jobs.get(job_id)
        if job is None:
            return ScheduledJobInfo(
                enabled=False,
                next_run=None,
                cron_expression=None,
            )
        return ScheduledJobInfo(
            enabled=True,
            next_run=job.next_run_time.astimezone(self._app_config.tzinfo).isoformat(),
            cron_expression=job.cron_expression if include_trigger else None,
        )

    def _dispatch(self, job: ScheduledJob) -> asyncio.Task[None]:
        if (
            active := self._callbacks.get(job.job_id)
        ) is not None and not active.done():
            return active

        task = asyncio.create_task(job.func(), name=f"scheduler-job-{job.job_id}")
        self._callbacks[job.job_id] = task

        def on_done(t: asyncio.Task[None]) -> None:
            if self._callbacks.get(job.job_id) is t:
                del self._callbacks[job.job_id]
            if not t.cancelled():
                exc = t.exception()
                if exc is not None and not self._closed:
                    logger.error(
                        "Scheduled task %s failed",
                        job.job_id,
                        exc_info=exc,
                    )

        task.add_done_callback(on_done)
        return task

    async def _run_loop(self) -> None:
        while not self._closed:
            self._wake_event.clear()
            now = datetime.now(UTC)
            for job in self._jobs.values():
                if job.next_run_time > now:
                    continue
                due = job.next_run_time
                if job.interval_minutes is not None:
                    interval = timedelta(minutes=job.interval_minutes)
                    # Coalesce missed runs without shifting the interval's phase.
                    job.next_run_time += (
                        (now - job.next_run_time) // interval + 1
                    ) * interval
                    due = job.next_run_time - interval
                elif job.cron_expression is not None:
                    if now - due > timedelta(minutes=5):
                        due = next_run_after(
                            job.cron_expression,
                            now - timedelta(minutes=5, microseconds=1),
                            tz=self._app_config.tzinfo,
                        ).astimezone(UTC)
                    job.next_run_time = next_run_after(
                        job.cron_expression, now, tz=self._app_config.tzinfo
                    ).astimezone(UTC)
                # Preserve the five-minute grace period for delayed executions.
                if timedelta(0) <= now - due <= timedelta(minutes=5):
                    self._dispatch(job)

            earliest = min(
                (job.next_run_time for job in self._jobs.values()), default=None
            )
            # Recheck wall-clock time after clock corrections or system suspend.
            timeout = (
                min(60.0, max(0.0, (earliest - datetime.now(UTC)).total_seconds()))
                if earliest is not None
                else None
            )
            try:
                async with asyncio.timeout(timeout):
                    await self._wake_event.wait()
            except TimeoutError:
                pass
