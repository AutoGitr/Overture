"""Durable lifecycle summaries, progress logs and findings for managed jobs."""

lazy from datetime import datetime
lazy from typing import Any

lazy from sqlmodel import col, delete, func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.job_result import JobLogLine, JobResult, JobRun
lazy from ..db.session import Database
lazy from ..jobs.kinds import INTERRUPTED_MESSAGE, JobKind
lazy from ..jobs.progress_log import JobLogEntry, JobOutcome, log_entry
lazy from ..schemas.job_snapshots import JobLogPage, JobResults
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.security import sanitise_for_output
lazy from ..utils.time import utc_now


async def persist(
    database: Database,
    *,
    run_id: str,
    kind: str,
    started_at: str,
    event: str,
    summary: dict[str, Any],
    results: list[dict[str, Any]],
    log: list[dict[str, Any]],
) -> None:
    """Append one bounded batch and update its run summary atomically.

    A kind shows only its latest run, so the first write of a run deletes the
    kind's earlier ones with their logs and findings.
    """
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
                    entry=sanitise_for_output(entry),
                )
            )
            run.log_total += 1
        for result in results:
            session.add(
                JobResult(
                    run_id=run_id,
                    ordinal=run.total,
                    payload=sanitise_for_output(result),
                )
            )
            run.total += 1
        run.event = event
        finished_at = summary.get("finished_at")
        run.finished_at = datetime.fromisoformat(finished_at) if finished_at else None
        run.summary = sanitise_for_output(summary)
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
) -> JobLogPage:
    """Read a stable page of a run's progress log, of only *outcomes* when given.

    A filtered page counts *offset* and ``total`` among the matching lines.
    """
    async with database.read_session() as session:
        run = await _visible_run(session, run_id)
        query = select(JobLogLine).where(JobLogLine.run_id == run_id)
        if outcomes:
            matching = col(JobLogLine.outcome).in_(outcomes)
            query = query.where(matching).offset(offset)
            total = (
                await session.exec(
                    select(func.count()).where(JobLogLine.run_id == run_id, matching)
                )
            ).one()
        else:
            query = query.where(JobLogLine.ordinal >= offset)
            total = run.log_total
        rows = (
            await session.exec(query.order_by(col(JobLogLine.ordinal)).limit(limit))
        ).all()
        return JobLogPage(
            run_id=run_id,
            total=total,
            offset=offset,
            items=[JobLogEntry.model_validate(row.entry) for row in rows],
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
            outcomes: dict[str, int] = summary.get("log_outcomes") or {}
            summary["log"] = entry
            summary["log_total"] = run.log_total
            summary["log_outcomes"] = {
                **outcomes,
                JobOutcome.SKIPPED: outcomes.get(JobOutcome.SKIPPED, 0) + 1,
            }
            run.summary = summary
            session.add(run)
