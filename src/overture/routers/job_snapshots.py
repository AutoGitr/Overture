"""Terminal popup snapshot lifecycle routes."""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Path, Query

lazy from ..dependencies import DatabaseDep, RuntimeDep
lazy from ..jobs.kinds import JobKind
lazy from ..jobs.progress_log import JobOutcome
lazy from ..schemas.job_snapshots import (
    JobLogPage,
    JobResults,
    JobSnapshotClearResponse,
)
lazy from ..services import job_results, job_snapshots
lazy from .auth import require_auth

router = APIRouter(
    prefix="/job-snapshots",
    tags=["job-snapshots"],
    dependencies=[Depends(require_auth)],
)


@router.delete("/{kind}")
async def clear_job_snapshot(
    kind: Annotated[JobKind, Path(description="Job kind")],
    runtime: RuntimeDep,
    finished_at: Annotated[str, Query(min_length=1)],
) -> JobSnapshotClearResponse:
    """Clear a terminal popup result only when the client token still matches."""
    return await job_snapshots.clear_snapshot(kind, finished_at, runtime)


@router.get("/results/{run_id}")
async def get_job_results(run_id: str, database: DatabaseDep) -> JobResults:
    """Return every retained finding of a run, in the order found."""
    return await job_results.results(database, run_id)


@router.get("/log/{run_id}")
async def get_job_log(
    run_id: str,
    database: DatabaseDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=500)] = 200,
    outcome: Annotated[
        list[JobOutcome] | None, Query(description="Only lines of these outcomes.")
    ] = None,
) -> JobLogPage:
    """Return an ordered, bounded page of a retained run's progress log."""
    return await job_results.log_page(
        database, run_id, offset, limit, frozenset(outcome or ())
    )
