"""Server-owned terminal snapshot lifecycle operations."""

lazy import copy
lazy from collections.abc import Callable, Hashable, Iterable, Mapping
lazy from typing import Any, cast

lazy from sqlmodel import col, select

lazy from .. import protocols
lazy from ..db.models.job_result import JobResult
lazy from ..db.session import PAGE_SIZE, Database
lazy from ..jobs import results as job_results
lazy from ..jobs.kinds import JobKind
lazy from ..jobs.lifecycle import label
lazy from ..jobs.slot import ManagedBackgroundJob
lazy from ..schemas.job_snapshots import JobSnapshotClearResponse
lazy from ..utils.errors import PublicServiceError


async def require_snapshot_keys(
    job: ManagedBackgroundJob,
    finished_at: str,
    *,
    collection: str,
    database: Database,
    requested: Iterable[Hashable],
    row_key: Callable[[dict[str, Any]], Hashable],
    stale_message: str,
) -> None:
    """Require every requested action to belong to the named result snapshot."""
    payload = job.final_payload_for(finished_at)
    if payload is None:
        raise PublicServiceError(409, stale_message)
    missing = set(requested)
    if run_id := payload.get("run_id"):
        stored = await job_results.results(database, str(run_id))
        missing.difference_update(row_key(row) for row in stored.items)
    else:
        rows = payload.get(collection)
        if isinstance(rows, list):
            missing.difference_update(
                row_key(cast("dict[str, Any]", row))
                for row in cast("list[object]", rows)
                if isinstance(row, dict)
            )
    if missing or not job.has_final_snapshot(finished_at):
        raise PublicServiceError(409, stale_message)


async def patch_snapshot(
    job: ManagedBackgroundJob,
    finished_at: str,
    *,
    collection: str,
    patcher: Callable[[dict[str, Any]], dict[str, Any]],
    database: Database,
    publisher: protocols.EventPublisher,
) -> None:
    """Patch findings in bounded transactions, then notify the current view."""
    payload = job.final_payload_for(finished_at)
    if payload is None:
        return
    if run_id := payload.get("run_id"):
        offset = 0
        while True:
            async with database.write_session() as session:
                rows = (
                    await session.exec(
                        select(JobResult)
                        .where(JobResult.run_id == run_id, JobResult.ordinal >= offset)
                        .order_by(col(JobResult.ordinal))
                        .limit(PAGE_SIZE)
                    )
                ).all()
                for row in rows:
                    updated = patcher({collection: [copy.deepcopy(row.payload)]})[
                        collection
                    ][0]
                    if updated != row.payload:
                        row.payload = updated
                        session.add(row)
            if len(rows) < PAGE_SIZE:
                break
            offset = rows[-1].ordinal + 1
        await publisher.broadcast_built(
            lambda: job.patch_final_snapshot(finished_at, lambda summary: summary)
        )
    else:
        await publisher.broadcast_built(
            lambda: job.patch_final_snapshot(finished_at, patcher)
        )


async def clear_snapshot(
    kind: JobKind,
    finished_at: str,
    job_slots: Mapping[JobKind, ManagedBackgroundJob],
) -> JobSnapshotClearResponse:
    """Clear one matching terminal result snapshot and notify active clients.

    Raises:
        PublicServiceError: When results of this kind cannot be cleared.
    """
    if not kind.clearable:
        raise PublicServiceError(400, f"{label(kind.label)} results cannot be cleared")
    status = await job_slots[kind].clear_result(finished_at)
    return JobSnapshotClearResponse(
        status=status,
        kind=kind,
        finished_at=finished_at,
    )
