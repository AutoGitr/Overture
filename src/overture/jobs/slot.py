"""One background job slot: its task, stop request and snapshots."""

lazy import asyncio
lazy import copy
lazy import logging
lazy from collections.abc import Callable, Coroutine, Mapping
lazy from typing import Any, Literal

lazy from .. import protocols
lazy from ..utils.time import utc_now_iso
lazy from .lifecycle import ManagedJobLifecycle, label, publish_job_lifecycle
lazy from .runner import JobContext

logger = logging.getLogger(__name__)

#: How long a stopped job may keep its slot before the task is cancelled.
#: Long enough that any runner reaches its next stop check first, so a
#: cooperative run is never cut short; short enough that one stuck in a call
#: that never returns still frees the slot while the user is watching.
STOP_GRACE_SECONDS = 60.0


def _counters_only(payload: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return just the integer counters from a progress payload.

    A run that ends without its body publishing anything still has the numbers
    the user was watching in its last progress event. The streamed fields
    around them - the log line, the batch of results - describe one step rather
    than the whole run, and a terminal event carrying a single batch would
    replace the full list the client had already collected.
    """
    return {key: value for key, value in (payload or {}).items() if type(value) is int}


class ManagedBackgroundJob:
    """One background slot: its task, its stop request, and its snapshots.

    The slot - not the job body - guarantees what clients depend on: exactly
    one terminal event per run, and a slot that always frees. A body that
    returns normally publishes its own terminal event through
    :func:`run_managed_job`; one that is cancelled, or that raises past that
    point, has its terminal event published here instead. Neither path can
    publish twice, because this one only fires when no terminal snapshot was
    recorded for the run.
    """

    def __init__(
        self, lifecycle: ManagedJobLifecycle, publisher: protocols.EventPublisher
    ) -> None:
        """Bind one job slot to the lifecycle events its runs publish."""
        self.lifecycle = lifecycle
        self.name = lifecycle.kind.label
        self.publisher = publisher
        self.task: asyncio.Task[None] | None = None
        self.last_event: str | None = None
        self.last_payload: dict[str, Any] | None = None
        self.resume_event: str | None = None
        self.resume_payload: dict[str, Any] | None = None
        self.started_at: str | None = None
        self._stop_event = asyncio.Event()
        self._teardown: set[asyncio.Task[None]] = set()
        self._stop_watchdog: asyncio.Task[None] | None = None
        self._idle = asyncio.Event()
        self._idle.set()
        self._closed = False

    @property
    def stop_requested(self) -> bool:
        """Return whether the current run has been asked to stop."""
        return self._stop_event.is_set()

    @property
    def running(self) -> bool:
        """Return whether a background task is active."""
        return not self._idle.is_set()

    async def wait_idle(self) -> None:
        """Wait until this slot has no running task.

        Callers that need the slot next - a scheduled run queued behind a
        manual one - await this instead of polling ``running`` on a timer.
        """
        await self._idle.wait()

    async def shutdown(self) -> None:
        """Cancel the active run and finish all slot-owned teardown work."""
        self._closed = True
        task = self.task
        if task is not None and not task.done():
            self._stop_event.set()
            task.cancel()
        if task is not None:
            # The task's own done callback, which publishes the fallback
            # terminal event, runs before this gather returns.
            await asyncio.gather(task, return_exceptions=True)
        # A finished teardown task leaves the set only once its callback has
        # run, so wait for the unfinished ones rather than for the set to empty.
        while pending := {task for task in self._teardown if not task.done()}:
            await asyncio.wait(pending)

    async def start_when_idle(
        self,
        job_factory: Callable[[JobContext], Coroutine[Any, Any, None]],
    ) -> asyncio.Task[None]:
        """Wait for the slot, start the job in it, and return its task."""
        while not self.start_with_context(job_factory):
            await self.wait_idle()
        if self.task is None:
            raise RuntimeError(f"{self.name} has no task after starting")
        return self.task

    async def run_when_idle(
        self,
        job_factory: Callable[[JobContext], Coroutine[Any, Any, None]],
        *,
        on_start: Callable[[asyncio.Task[None]], None] | None = None,
    ) -> None:
        """Wait for the slot, run the job in it, and wait for that run to end.

        *on_start* sees the run's task as soon as it is created. Cancelling the
        caller leaves the run going; a run that fails or is stopped by
        cancellation raises :class:`RuntimeError` here instead of cancelling
        the caller.
        """
        task = await self.start_when_idle(job_factory)
        if on_start is not None:
            on_start(task)
        await asyncio.wait([task])
        if task.cancelled():
            raise RuntimeError(f"{self.name} was cancelled")
        if (failure := task.exception()) is not None:
            raise RuntimeError(f"{self.name} failed") from failure

    def start_with_context(
        self,
        job_factory: Callable[[JobContext], Coroutine[Any, Any, None]],
    ) -> bool:
        """Start the job if no task is already running."""
        if self._closed:
            raise RuntimeError(f"{self.name} is stopping")
        if self.running:
            return False

        self._stop_event = asyncio.Event()
        self.last_event = None
        self.last_payload = None
        self.clear_resume_snapshot()
        self._idle.clear()
        self.started_at = utc_now_iso()
        context = JobContext(
            lifecycle=self.lifecycle,
            started_at=self.started_at,
            stop_event=self._stop_event,
            save_snapshot=self.save_snapshot,
            save_resume_snapshot=self.save_resume_snapshot,
            publisher=self.publisher,
        )
        task = asyncio.create_task(job_factory(context))
        self.task = task
        task.add_done_callback(self._on_done)
        return True

    def request_stop(self) -> bool:
        """Ask the running job to stop, and return whether one was running.

        The flag is cooperative, so a body parked in a long call would hold
        the slot indefinitely. A watchdog cancels the task once the grace
        period is up, and :meth:`_on_done` publishes the terminal event either
        way, so the view leaves "running" whether the body cooperated or not.
        """
        if not self.running:
            return False
        self._stop_event.set()
        task = self.task
        if task is not None and self._stop_watchdog is None:
            self._stop_watchdog = self._spawn(self._cancel_unstopped(task))
        return True

    async def _cancel_unstopped(self, task: asyncio.Task[None]) -> None:
        """Cancel a task that did not act on its stop request in time."""
        await asyncio.wait([task], timeout=STOP_GRACE_SECONDS)
        if task.done():
            return
        logger.warning(
            "%s did not stop within %.0fs; cancelling it",
            label(self.name),
            STOP_GRACE_SECONDS,
        )
        task.cancel()

    def save_snapshot(self, event: str, payload: dict[str, Any]) -> None:
        """Remember the latest final payload so clients can restore after reload."""
        self.last_event = event
        self.last_payload = payload
        self.clear_resume_snapshot()

    def save_resume_snapshot(self, event: str, payload: dict[str, Any]) -> None:
        """Remember the latest running payload so clients can resume after reload."""
        self.resume_event = event
        self.resume_payload = payload

    def clear_resume_snapshot(self) -> None:
        """Clear the running snapshot after the job reaches a terminal state."""
        self.resume_event = None
        self.resume_payload = None

    def final_snapshot(self) -> tuple[str | None, dict[str, Any] | None]:
        """Return the latest terminal event snapshot."""
        return self.last_event, self.last_payload

    def has_final_snapshot(self, expected_finished_at: str) -> bool:
        """Return whether the current terminal snapshot matches a client token."""
        return bool(
            self.last_payload
            and self.last_payload.get("finished_at") == expected_finished_at
        )

    def final_payload_for(self, expected_finished_at: str) -> dict[str, Any] | None:
        """Return an isolated copy of the terminal payload named by a client token."""
        if not self.has_final_snapshot(expected_finished_at):
            return None
        return copy.deepcopy(self.last_payload)

    def clear_final_snapshot(
        self,
        expected_finished_at: str,
    ) -> Literal["cleared", "stale", "empty"]:
        """Clear a matching terminal snapshot without discarding a newer result."""
        if not self.last_payload:
            return "empty"
        if not self.has_final_snapshot(expected_finished_at):
            return "stale"
        self.last_event = None
        self.last_payload = None
        return "cleared"

    def patch_final_snapshot(
        self,
        expected_finished_at: str,
        patcher: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> tuple[str, dict[str, Any]] | None:
        """Patch a matching terminal snapshot and return its event and payload."""
        event = self.last_event
        current_payload = self.last_payload
        if (
            not event
            or not current_payload
            or current_payload.get("finished_at") != expected_finished_at
        ):
            return None
        payload = patcher(copy.deepcopy(current_payload))
        self.save_snapshot(event, payload)
        return event, payload

    def running_snapshot(self) -> tuple[str | None, dict[str, Any] | None]:
        """Return the latest running progress snapshot."""
        return self.resume_event, self.resume_payload

    def _on_done(self, task: asyncio.Task[None]) -> None:
        """Observe completion while retaining the slot through finalization."""
        failure = None if task.cancelled() else task.exception()
        if self.task is task:
            self._spawn(self._finalize(task, self.started_at, failure))

    async def _finalize(
        self,
        task: asyncio.Task[None],
        started_at: str | None,
        failure: BaseException | None,
    ) -> None:
        try:
            if self.task is not task or self.started_at != started_at:
                return
            if self.last_payload is None:
                status = (
                    "stopped"
                    if task.cancelled()
                    else "failed"
                    if failure
                    else "completed"
                )
                await self._publish_unfinished(
                    status,
                    error="Background operation failed" if failure else None,
                    exc=failure,
                )
            elif failure is not None:
                logger.error(
                    "%s failed after publishing its result",
                    label(self.name),
                    exc_info=failure,
                )
        finally:
            if self.task is task:
                self.task = None
                if self._stop_watchdog is not None:
                    self._stop_watchdog.cancel()
                self._stop_watchdog = None
                self._idle.set()

    async def _publish_unfinished(
        self,
        status: str,
        *,
        error: str | None = None,
        exc: BaseException | None = None,
    ) -> None:
        """Publish the terminal event for a run whose body never sent one.

        A body that completes without a terminal event of its own reports its
        result itself (an incremental sync poll does), so only a run that was
        stopped or failed is written to the container log here.
        """
        try:
            await publish_job_lifecycle(
                self.lifecycle.kind,
                status,
                event_job_id=self.lifecycle.event_job_id,
                target=self.lifecycle.target,
                name=None if status == "completed" else self.name,
                exc=exc,
                error=error,
                started_at=self.started_at,
                finished_at=utc_now_iso(),
                save_snapshot=self.save_snapshot,
                publisher=self.publisher,
                **_counters_only(self.resume_payload),
            )
        except Exception:
            logger.exception("Could not publish the %s %s event", self.name, status)

    def _spawn(self, coro: Coroutine[Any, Any, None]) -> asyncio.Task[None] | None:
        """Run one teardown coroutine, holding a reference until it finishes."""
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:
            coro.close()
            logger.debug(
                "Could not run %s teardown; the event loop is closed", self.name
            )
            return None
        self._teardown.add(task)
        task.add_done_callback(self._teardown_done)
        return task

    def _teardown_done(self, task: asyncio.Task[None]) -> None:
        self._teardown.discard(task)
        if not task.cancelled() and (failure := task.exception()) is not None:
            logger.error("Finishing the %s run failed", self.name, exc_info=failure)
