"""Sync router - sync status, runs and saved schedules."""

lazy from fastapi import APIRouter, Depends, status

lazy from ..dependencies import SyncDep
lazy from ..schemas.common import StatusResponse
lazy from ..schemas.sync import (
    SyncRunRequest,
    SyncScheduleResponse,
    SyncScheduleWrite,
    SyncStatusResponse,
)
lazy from .auth import require_auth
lazy from .parameters import ScheduleIdPath

router = APIRouter(prefix="/sync", tags=["sync"], dependencies=[Depends(require_auth)])


@router.get("/status")
async def get_sync_status(sync: SyncDep) -> SyncStatusResponse:
    """Get whether a sync is running."""
    return SyncStatusResponse(running=sync.job.running)


@router.post("/run")
async def run_sync(body: SyncRunRequest, sync: SyncDep) -> StatusResponse:
    """Trigger a full sync run."""
    return sync.run_sync(body)


@router.post("/stop")
async def stop_sync(sync: SyncDep) -> StatusResponse:
    """Request the running sync to stop gracefully."""
    return StatusResponse.stop(sync.job.request_stop())


@router.get("/schedules")
async def list_sync_schedules(sync: SyncDep) -> list[SyncScheduleResponse]:
    """List saved sync schedules."""
    return await sync.schedules.all()


@router.post("/schedules", status_code=status.HTTP_201_CREATED)
async def create_sync_schedule(
    body: SyncScheduleWrite, sync: SyncDep
) -> SyncScheduleResponse:
    """Create a saved sync schedule."""
    return await sync.schedules.create(body)


@router.put("/schedules/{schedule_id}")
async def update_sync_schedule(
    schedule_id: ScheduleIdPath, body: SyncScheduleWrite, sync: SyncDep
) -> SyncScheduleResponse:
    """Update a saved sync schedule."""
    return await sync.schedules.update(schedule_id, body)


@router.delete("/schedules/{schedule_id}")
async def delete_sync_schedule(
    schedule_id: ScheduleIdPath, sync: SyncDep
) -> StatusResponse:
    """Delete a saved sync schedule."""
    return await sync.schedules.delete(schedule_id)


@router.post("/schedules/{schedule_id}/run")
async def run_sync_schedule(
    schedule_id: ScheduleIdPath, sync: SyncDep
) -> StatusResponse:
    """Queue a saved sync schedule for immediate execution."""
    return await sync.schedules.run_now(schedule_id)
