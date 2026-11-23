"""Durable lifecycle summaries, progress logs and findings for managed jobs."""

lazy from datetime import datetime
lazy from typing import Any
lazy from weakref import WeakValueDictionary

lazy from pydantic_core import to_jsonable_python
lazy from sqlalchemy import ColumnElement
lazy from sqlmodel import col, delete, func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.job_result import JobLogLine, JobResult, JobRun
lazy from ..db.session import Database
lazy from ..schemas.base import StrictBaseModel
lazy from ..schemas.job_snapshots import JobLogPage, JobResults
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.time import utc_now
lazy from .kinds import INTERRUPTED_MESSAGE, JobKind
lazy from .progress_log import JobLogEntry, JobOutcome, log_entry


class UnwrittenLog:
    """The log lines a live run has announced but not yet written.

    A run writes its log in batches, and a batch waits for the run's next
    event, which can come minutes later when the run goes quiet. Its events
    already counted those lines, so :func:`log_page` reads them from here
    meanwhile: every line a browser is told of can be read at once.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        #: Lines already written, which number the first one waiting.
        self.written = 0
        self.lines: list[dict[str, Any]] = []
        _LIVE_LOGS[run_id] = self

    def wrote(self, count: int) -> None:
        """Note that the first *count* waiting lines are written."""
        self.written += count
        self.lines = self.lines[count:]


#: Each live run's unwritten lines, by run ID; a finished run's goes with it.
_LIVE_LOGS: WeakValueDictionary[str, UnwrittenLog] = WeakValueDictionary()


async def persist(
    database: Database,
    *,
    run_id: str,
    kind: str,
    started_at: str,
    event: str,
    summary: dict[str, Any],
    results: list[StrictBaseModel],
    log: list[dict[str, Any]],
) -> None:
    """Append one bounded batch and update its run summary atomically.

    A kind shows only its latest run, so the first write of a run deletes the
    kind's earlier ones with their logs and findings.
    """
    # Serialised through their schemas, which redact, before the write lock.
    payloads = [to_jsonable_python(result) for result in results]
    async with database.write_session() as session:
        run = await session.get(JobRun, run_id)
        if run is None:
            await session.exec(delete(JobRun).where(col(JobRun.kind) == kind))
            run = JobRun(
                id=run_id,
                kind=kind,
                started_at=datetime.fromisoformat(started_at),
                event=event,
            )
            session.add(run)
            await session.flush()
        for entry in log:
            session.add(
                JobLogLine(
                    run_id=run_id,
                    ordinal=run.log_total,
                    outcome=entry["outcome"],
                    server_id=entry.get("server_id"),
                    entry=entry,
                )
            )
            run.log_total += 1
        for result in payloads:
            session.add(
                JobResult(
                    run_id=run_id,
                    ordinal=run.total,
                    payload=result,
                )
            )
            run.total += 1
        run.event = event
        finished_at = summary.get("finished_at")
        run.finished_at = datetime.fromisoformat(finished_at) if finished_at else None
        run.summary = summary
        session.add(run)


async def _visible_run(session: AsyncSession, run_id: str) -> JobRun:
    run = await session.get(JobRun, run_id)
    if run is None or run.cleared:
        raise PublicServiceError(404, "Job results are no longer available")
    return run


async def results(database: Database, run_id: str) -> JobResults:
    """Read every finding of a run, without retaining a session during delivery.

    Findings are acted on as a whole set, by selection or by kind, so they are
    delivered whole; a run holds at most one finding per file it examined.
    """
    async with database.read_session() as session:
        await _visible_run(session, run_id)
        rows = (
            await session.exec(
                select(JobResult)
                .where(JobResult.run_id == run_id)
                .order_by(col(JobResult.ordinal))
            )
        ).all()
        return JobResults(run_id=run_id, items=[row.payload for row in rows])


async def log_page(
    database: Database,
    run_id: str,
    offset: int,
    limit: int,
    outcomes: frozenset[JobOutcome] = frozenset(),
    hidden_servers: frozenset[int] = frozenset(),
) -> JobLogPage:
    """Read a stable page of a run's progress log, filtered when asked.

    Only lines of *outcomes* are listed when given, and none about a media
    server in *hidden_servers*. A filtered page counts *offset* and ``total``
    among the matching lines. A live run's lines not yet written follow the
    written ones.
    """
    # Taken before the read, so a batch written during it is in one or both;
    # those the read already holds are left out by their number.
    live = _LIVE_LOGS.get(run_id)
    first_waiting, waiting = (live.written, list(live.lines)) if live else (0, [])
    async with database.read_session() as session:
        run = await _visible_run(session, run_id)
        query = select(JobLogLine).where(JobLogLine.run_id == run_id)
        filters: list[ColumnElement[bool]] = []
        if outcomes:
            filters.append(col(JobLogLine.outcome).in_(outcomes))
        if hidden_servers:
            server = col(JobLogLine.server_id)
            filters.append(server.is_(None) | server.not_in(hidden_servers))
        if filters:
            query = query.where(*filters).offset(offset)
            written = (
                await session.exec(
                    select(func.count()).where(JobLogLine.run_id == run_id, *filters)
                )
            ).one()
        else:
            query = query.where(JobLogLine.ordinal >= offset)
            written = run.log_total
        rows = (
            await session.exec(query.order_by(col(JobLogLine.ordinal)).limit(limit))
        ).all()
        unwritten = waiting[max(0, run.log_total - first_waiting) :]
    tail = [
        entry
        for entry in map(JobLogEntry.model_validate, unwritten)
        if (not outcomes or entry.outcome in outcomes)
        and (entry.server_id is None or entry.server_id not in hidden_servers)
    ]
    items = [JobLogEntry.model_validate(row.entry) for row in rows]
    if len(items) < limit:
        start = max(0, offset - written)
        items += tail[start : start + limit - len(items)]
    return JobLogPage(
        run_id=run_id, total=written + len(tail), offset=offset, items=items
    )


async def latest_runs(database: Database) -> dict[str, JobRun]:
    """Return each job kind's most recent run that was not cleared."""
    async with database.read_session() as session:
        newest = (
            select(JobRun.kind, func.max(JobRun.started_at).label("started_at"))
            .group_by(col(JobRun.kind))
            .subquery()
        )
        runs = (
            await session.exec(
                select(JobRun).join(
                    newest,
                    (col(JobRun.kind) == newest.c.kind)
                    & (col(JobRun.started_at) == newest.c.started_at),
                )
            )
        ).all()
    return {run.kind: run for run in runs if not run.cleared}


async def interrupt_unfinished(database: Database) -> None:
    """Preserve available findings and report interruption after a restart.

    Each kind keeps only its latest run, so there are at most a few to mark.
    """
    async with database.write_session() as session:
        runs = (
            await session.exec(select(JobRun).where(col(JobRun.finished_at).is_(None)))
        ).all()
        finished_at = utc_now()
        for run in runs:
            run.finished_at = finished_at
            run.event = run.event.rsplit(".", 1)[0] + ".stopped"
            summary = dict(run.summary)
            summary["finished_at"] = finished_at.isoformat()
            summary["job"] = {
                **summary.get("job", {}),
                "status": "stopped",
                "error": {"message": INTERRUPTED_MESSAGE},
            }
            entry = log_entry(
                JobOutcome.SKIPPED, JobKind(run.kind).label, INTERRUPTED_MESSAGE
            ).model_dump(mode="json")
            session.add(
                JobLogLine(
                    run_id=run.id,
                    ordinal=run.log_total,
                    outcome=JobOutcome.SKIPPED,
                    entry=entry,
                )
            )
            run.log_total += 1
            summary["log"] = entry
            summary["log_total"] = run.log_total
            for key in ("log_outcomes", "log_targets"):
                counts: dict[str, int] = summary.get(key) or {}
                summary[key] = {
                    **counts,
                    JobOutcome.SKIPPED: counts.get(JobOutcome.SKIPPED, 0) + 1,
                }
            run.summary = summary
            session.add(run)
