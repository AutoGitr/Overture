"""Persistence and pagination for the existing collecting job views."""

lazy from datetime import datetime
lazy from typing import Any

lazy from sqlmodel import col, func, select

lazy from ..db.models.job_result import JobResult, JobRun
lazy from ..db.session import PAGE_SIZE, Database
lazy from ..schemas.job_snapshots import JobResultsPage
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
) -> None:
    """Append one bounded batch and update its run summary atomically."""
    async with database.write_session() as session:
        run = await session.get(JobRun, run_id)
        if run is None:
            run = JobRun(
                id=run_id,
                kind=kind,
                started_at=datetime.fromisoformat(started_at),
                event=event,
            )
            session.add(run)
            await session.flush()
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


async def page(
    database: Database, run_id: str, offset: int, limit: int
) -> JobResultsPage:
    """Read a stable ordinal page without retaining a session during delivery."""
    async with database.read_session() as session:
        run = await session.get(JobRun, run_id)
        if run is None or run.cleared:
            raise PublicServiceError(404, "Job results are no longer available")
        rows = (
            await session.exec(
                select(JobResult)
                .where(JobResult.run_id == run_id, JobResult.ordinal >= offset)
                .order_by(col(JobResult.ordinal))
                .limit(limit)
            )
        ).all()
        return JobResultsPage(
            run_id=run_id,
            total=run.total,
            offset=offset,
            items=[row.payload for row in rows],
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
    """Preserve available findings and report interruption after a restart."""
    while True:
        async with database.write_session() as session:
            runs = (
                await session.exec(
                    select(JobRun)
                    .where(col(JobRun.finished_at).is_(None))
                    .limit(PAGE_SIZE)
                )
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
                    "error": {
                        "code": "interrupted",
                        "message": "Interrupted by application restart",
                    },
                }
                run.summary = summary
                session.add(run)
        if len(runs) < PAGE_SIZE:
            return
