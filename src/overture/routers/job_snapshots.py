"""Terminal popup snapshot lifecycle routes."""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Path, Query

lazy from ..dependencies import DatabaseDep, RuntimeDep
lazy from ..jobs.kinds import JobKind
lazy from ..schemas.downloads import DownloadJobsPage
lazy from ..schemas.job_snapshots import JobResultsPage, JobSnapshotClearResponse
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
async def get_job_results(
    run_id: str,
    database: DatabaseDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> JobResultsPage:
    """Return an ordered, bounded page of retained findings."""
    return await job_results.page(database, run_id, offset, limit)


@router.get("/downloads")
async def get_download_backlog(
    runtime: RuntimeDep,
    after: str | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> DownloadJobsPage:
    """Page the active backlog outside realtime snapshots."""
    return await runtime.downloads.backlog_page(after, limit)
