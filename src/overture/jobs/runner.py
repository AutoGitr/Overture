"""Running one managed job body: its context, progress and terminal event."""

lazy import asyncio
lazy import time
lazy from collections import Counter
lazy from collections.abc import AsyncGenerator, Callable, Mapping
lazy from contextlib import asynccontextmanager
lazy from dataclasses import dataclass, field, replace
lazy from typing import Any
lazy from uuid import uuid4

lazy from sqlalchemy.exc import SQLAlchemyError

lazy from .. import protocols
lazy from ..db.session import CHUNK_SIZE, Database
lazy from ..services import job_results
lazy from ..utils.errors import public_error_message
lazy from ..utils.time import utc_now_iso
lazy from .kinds import INTERRUPTED_MESSAGE, JOB_STREAMED_KEYS
lazy from .lifecycle import ManagedJobLifecycle, label, publish_job_lifecycle
lazy from .progress_log import JobLogEntry, JobOutcome, log_entry
lazy from .tally import JobTally

#: Seconds between persisted summaries of progress that brings no new results.
#: Results are written as they arrive, so only the counters and log lines a
#: restart would report can lag by this much; a write per visited target would
#: cost more than the visit itself.
_PROGRESS_SUMMARY_INTERVAL = 1.0

#: Exceptions a background job body is expected to survive. Runners that also
#: perform HTTP work extend this with their client's error type.
DEFAULT_JOB_ERRORS: tuple[type[BaseException], ...] = (
    SQLAlchemyError,
    OSError,
    ValueError,
    RuntimeError,
)


class JobPersistence:
    """One run's durable summary, its progress log and its result batches.

    Log lines are numbered and counted per outcome as they are published, so a
    client knows where each live line sits in the log it pages and how many
    lines each outcome filter holds, and are written in batches with the
    summary rather than one transaction per line.
    """

    def __init__(
        self, database: Database, lifecycle: ManagedJobLifecycle, started_at: str
    ) -> None:
        self.database = database
        self.lifecycle = lifecycle
        self.started_at = started_at
        self.run_id = uuid4().hex
        self.log_total = 0
        self.log_outcomes: Counter[JobOutcome] = Counter()
        self._log: list[dict[str, Any]] = []
        self._summarised_at: float | None = None

    def add_log(self, entry: JobLogEntry) -> None:
        """Number one log line and keep it for the next write."""
        self._log.append(entry.model_dump(mode="json"))
        self.log_total += 1
        self.log_outcomes[entry.outcome] += 1

    async def record(
        self,
        event: str,
        canonical: dict[str, Any],
        results: list[Any],
        *,
        is_progress: bool,
    ) -> None:
        now = time.monotonic()
        if (
            is_progress
            and not results
            and len(self._log) < CHUNK_SIZE
            and self._summarised_at is not None
            and now - self._summarised_at < _PROGRESS_SUMMARY_INTERVAL
        ):
            return
        await job_results.persist(
            self.database,
            run_id=self.run_id,
            kind=self.lifecycle.kind,
            started_at=self.started_at,
            event=event,
            summary={
                key: value
                for key, value in canonical.items()
                if key not in JOB_STREAMED_KEYS
            },
            results=results,
            log=self._log,
        )
        self._log = []
        self._summarised_at = now


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
    persistence: JobPersistence | None = None
    shutdown_event: asyncio.Event = field(default_factory=asyncio.Event)

    def stop_requested(self) -> bool:
        """Return whether the run has been asked to stop."""
        return self.stop_event.is_set()

    async def publish_lifecycle(
        self,
        status: str,
        *,
        snapshot: bool = False,
        exc: BaseException | None = None,
        result_batch: list[Any] | None = None,
        quiet: bool = False,
        **payload: Any,
    ) -> None:
        """Publish a standard job lifecycle event with a stable job envelope."""
        payload.setdefault("started_at", self.started_at)
        name = self.lifecycle.kind.label
        if status == "stopped" and self.shutdown_event.is_set():
            if payload.get("error") is None:
                payload["error"] = INTERRUPTED_MESSAGE
            payload.setdefault(
                "log", log_entry(JobOutcome.SKIPPED, name, INTERRUPTED_MESSAGE)
            )
        if status == "failed" and not quiet and (error := payload.get("error")):
            # The error ends the run's log as well as its terminal event.
            payload.setdefault("log", log_entry(JobOutcome.ERROR, label(name), error))
        if self.persistence is not None:
            payload["run_id"] = self.persistence.run_id
            if (entry := payload.get("log")) is not None:
                self.persistence.add_log(JobLogEntry.model_validate(entry))
            payload["log_total"] = self.persistence.log_total
            payload["log_outcomes"] = dict(self.persistence.log_outcomes)
        canonical = await publish_job_lifecycle(
            self.lifecycle.kind,
            status,
            event_job_id=self.lifecycle.event_job_id,
            target=self.lifecycle.target,
            name=None if quiet else name,
            exc=exc,
            save_snapshot=self.save_snapshot if snapshot else None,
            save_resume_snapshot=self.save_resume_snapshot,
            publisher=self.publisher,
            **payload,
        )
        if self.persistence is not None:
            await self.persistence.record(
                f"{self.lifecycle.kind.event_prefix}.{status}",
                canonical,
                result_batch or [],
                is_progress=status == "progress",
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

    async def _publish(
        self,
        status: str,
        payload: dict[str, Any],
        *,
        snapshot: bool = False,
        exc: BaseException | None = None,
    ) -> None:
        persistence = self.context.persistence
        if persistence is not None and self.tally.collect_key is not None:
            payload["results_total"] = self.tally.result_count
        batch = self.tally.drain_results() if persistence is not None else []
        try:
            await self.context.publish_lifecycle(
                status, snapshot=snapshot, exc=exc, result_batch=batch, **payload
            )
        except BaseException:
            self.tally.restore_results(batch)
            raise

    def stop_requested(self) -> bool:
        """Return whether cancellation has been requested."""
        return self.context.stop_requested()

    async def started(self, **payload: Any) -> None:
        """Publish the ``started`` lifecycle event; the run is now planning."""
        await self._publish("started", payload)

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
        await self._publish("progress", payload)

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
            include_collected=self.context.persistence is None,
            finished_at=utc_now_iso(),
            **extras,
        )
        await self._publish(status, payload, snapshot=True, exc=exc)


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
    if database is not None and context.persistence is None:
        context = replace(
            context,
            persistence=JobPersistence(database, context.lifecycle, context.started_at),
        )
    job = ManagedJob(
        context,
        tally,
        terminal_extras=terminal_extras,
    )
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
