"""Running one managed job body: its context, progress and terminal event."""

lazy import asyncio
lazy import time
lazy from collections.abc import AsyncGenerator, Callable, Mapping
lazy from contextlib import asynccontextmanager
lazy from dataclasses import dataclass, field
lazy from typing import Any
lazy from uuid import uuid4

lazy from sqlalchemy.exc import SQLAlchemyError

lazy from .. import protocols
lazy from ..db.session import Database
lazy from ..services import job_results
lazy from ..utils.errors import public_error_message
lazy from ..utils.job_events import build_job_payload
lazy from ..utils.time import utc_now_iso
lazy from .lifecycle import ManagedJobLifecycle, publish_job_lifecycle
lazy from .progress_log import JobOutcome, log_entry
lazy from .tally import JobTally

#: Seconds between persisted summaries of progress that brings no new results.
#: Results are written as they arrive, so only the counters a restart would
#: report can lag by this much; a write per visited target would cost more
#: than the visit itself.
_PROGRESS_SUMMARY_INTERVAL = 1.0

#: Exceptions a background job body is expected to survive. Runners that also
#: perform HTTP work extend this with their client's error type.
DEFAULT_JOB_ERRORS: tuple[type[BaseException], ...] = (
    SQLAlchemyError,
    OSError,
    ValueError,
    RuntimeError,
)


@dataclass(slots=True, frozen=True)
class JobContext:
    """Runtime helpers passed into a managed background job."""

    lifecycle: ManagedJobLifecycle
    started_at: str
    save_snapshot: Callable[[str, dict[str, Any]], None]
    save_resume_snapshot: Callable[[str, dict[str, Any]], None]
    publisher: protocols.EventPublisher
    #: Set once the run is asked to stop.
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)

    def stop_requested(self) -> bool:
        """Return whether the run has been asked to stop."""
        return self.stop_event.is_set()

    async def publish_lifecycle(
        self,
        status: str,
        *,
        snapshot: bool = False,
        exc: BaseException | None = None,
        **payload: Any,
    ) -> None:
        """Publish a standard job lifecycle event with a stable job envelope."""
        payload.setdefault("started_at", self.started_at)
        await publish_job_lifecycle(
            self.lifecycle.kind,
            status,
            event_job_id=self.lifecycle.event_job_id,
            target=self.lifecycle.target,
            name=self.lifecycle.kind.label,
            exc=exc,
            save_snapshot=self.save_snapshot if snapshot else None,
            save_resume_snapshot=self.save_resume_snapshot,
            publisher=self.publisher,
            **payload,
        )


class ManagedJob[TallyT: JobTally]:
    """Publishing surface handed to a managed job body.

    Owns the tally and the event names, so a runner emits progress with the
    fields it actually adds. Generic over the tally so a runner body reads and
    writes its own counters by name.
    """

    def __init__(
        self,
        context: JobContext,
        tally: TallyT,
        *,
        terminal_extras: Callable[[TallyT], Mapping[str, Any]] | None = None,
    ) -> None:
        """Bind one tally to one lifecycle event prefix."""
        self.context = context
        self.tally = tally
        self._terminal_extras = terminal_extras
        self.database: Database | None = None
        self.run_id = uuid4().hex
        self._summarised_at: float | None = None

    async def _persist(self, status: str, payload: dict[str, Any]) -> None:
        if self.database is None or self.tally.collect_key is None:
            return
        payload["results_run_id"] = self.run_id
        payload["results_total"] = self.tally.result_count
        now = time.monotonic()
        if (
            status == "progress"
            and not self.tally.collected
            and self._summarised_at is not None
            and now - self._summarised_at < _PROGRESS_SUMMARY_INTERVAL
        ):
            return
        self._summarised_at = now
        batch = self.tally.drain_results()
        canonical = build_job_payload(
            self.context.lifecycle.kind,
            status,
            event_job_id=self.context.lifecycle.event_job_id,
            target=self.context.lifecycle.target,
            **payload,
        )
        summary = {
            key: value
            for key, value in canonical.items()
            if key not in {"issues", "results", "result"}
        }
        summary.setdefault("started_at", self.context.started_at)
        try:
            await job_results.persist(
                self.database,
                run_id=self.run_id,
                kind=self.context.lifecycle.kind,
                started_at=self.context.started_at,
                event=f"{self.context.lifecycle.kind.event_prefix}.{status}",
                summary=summary,
                results=batch,
            )
        except BaseException:
            self.tally.restore_results(batch)
            raise

    def stop_requested(self) -> bool:
        """Return whether cancellation has been requested."""
        return self.context.stop_requested()

    async def started(self, **payload: Any) -> None:
        """Publish the ``started`` lifecycle event; the run is now planning."""
        await self._persist("started", payload)
        await self.context.publish_lifecycle(
            "started",
            **payload,
        )

    async def planned(self, total: int, **payload: Any) -> None:
        """Fix the run's total from its complete work list, and publish it.

        Every target the run will report on - visited, or decided while
        planning - is counted here, so the total is right from this event on.
        """
        if self.tally.total is not None:
            raise RuntimeError("A run's total is planned once")
        self.tally.total = total
        await self.progress(**payload)

    async def report(
        self,
        outcome: JobOutcome,
        target: str,
        reason: str,
        *,
        count: int = 1,
        finished: bool = True,
        **payload: Any,
    ) -> None:
        """Write one outcome for *count* targets to the log and count it.

        *finished* says the line is the target's final word in this run, so it
        also advances ``done``; a download's later outcome passes ``False``.
        """
        self.tally.count(outcome, count)
        if finished:
            self.tally.done += count
        await self.progress(log=log_entry(outcome, target, reason), **payload)

    async def progress(self, **payload: Any) -> None:
        """Publish a ``progress`` event carrying the current counters."""
        payload = self.tally.as_payload(**payload)
        await self._persist("progress", payload)
        await self.context.publish_lifecycle("progress", **payload)

    async def publish_terminal(
        self,
        status: str,
        *,
        exc: BaseException | None = None,
        **payload: Any,
    ) -> None:
        """Publish a terminal event with counters, results, and a timestamp.

        *exc* is the failure a ``failed`` run logs with its traceback.
        """
        extras = (
            dict(self._terminal_extras(self.tally)) if self._terminal_extras else {}
        )
        extras.update(payload)
        payload = self.tally.as_payload(
            include_collected=self.database is None,
            finished_at=utc_now_iso(),
            **extras,
        )
        await self._persist(status, payload)
        await self.context.publish_lifecycle(status, snapshot=True, exc=exc, **payload)


@asynccontextmanager
async def run_managed_job[TallyT: JobTally](
    context: JobContext,
    tally: TallyT,
    *,
    terminal_extras: Callable[[TallyT], Mapping[str, Any]] | None = None,
    database: Database | None = None,
    catch: tuple[type[BaseException], ...] = DEFAULT_JOB_ERRORS,
) -> AsyncGenerator[ManagedJob[TallyT]]:
    """Run a background job body and publish its terminal event exactly once.

    The body reports progress; this context owns the single terminal event
    for completion, cancellation, or failure.
    """
    job = ManagedJob(
        context,
        tally,
        terminal_extras=terminal_extras,
    )
    job.database = database
    try:
        yield job
    except asyncio.CancelledError:
        await job.publish_terminal("stopped")
        raise
    except Exception as exc:
        safe_message = (
            public_error_message(exc)
            if isinstance(exc, catch)
            else "Background operation failed"
        )
        tally.errors += 1
        await job.publish_terminal("failed", exc=exc, error=safe_message)
    else:
        await job.publish_terminal(
            "stopped" if job.stop_requested() else "completed",
        )
