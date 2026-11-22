"""Terminal popup snapshot lifecycle routes."""

lazy from typing import Annotated

lazy from fastapi import Path, Query
lazy from pydantic import AfterValidator

lazy from ..dependencies import DatabaseDep, JobSlotsDep
lazy from ..jobs import results as job_results
lazy from ..jobs.kinds import JobKind
lazy from ..jobs.lifecycle import label
lazy from ..jobs.progress_log import JobOutcome
lazy from ..schemas.job_snapshots import (
    JobLogPage,
    JobResults,
    JobSnapshotClearResponse,
)
lazy from ..services import job_snapshots
lazy from .auth import authenticated_router

router = authenticated_router(prefix="/job-snapshots", tags=["job-snapshots"])


def _clearable(kind: JobKind) -> JobKind:
    if not kind.clearable:
        raise ValueError(f"{label(kind.label)} results cannot be cleared")
    return kind


#: A kind of job whose last result a client may clear from its view.
ClearableJobKindPath = Annotated[
    JobKind,
    AfterValidator(_clearable),
    Path(
        description="Job kind",
        json_schema_extra={"enum": [kind.value for kind in JobKind if kind.clearable]},
    ),
]


@router.delete("/{kind}")
async def clear_job_snapshot(
    kind: ClearableJobKindPath,
    job_slots: JobSlotsDep,
    finished_at: Annotated[str, Query(min_length=1)],
) -> JobSnapshotClearResponse:
    """Clear a terminal popup result only when the client token still matches."""
    return await job_snapshots.clear_snapshot(kind, finished_at, job_slots)


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
    hide_server: Annotated[
        list[int] | None,
        Query(description="No lines about these media servers, by number."),
    ] = None,
) -> JobLogPage:
    """Return an ordered, bounded page of a retained run's progress log."""
    return await job_results.log_page(
        database,
        run_id,
        offset,
        limit,
        frozenset(outcome or ()),
        frozenset(hide_server or ()),
    )
