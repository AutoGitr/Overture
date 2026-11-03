"""Bulk assets router - unified art and theme workflows and their schedules."""

lazy from fastapi import APIRouter, Depends, status

lazy from ..dependencies import AssetsDep
lazy from ..schemas.bulk import (
    BulkAssetsRequest,
    BulkAssetsRunResponse,
    BulkAssetsScheduleResponse,
    BulkAssetsScheduleWrite,
    BulkAssetsStopRequest,
)
lazy from ..schemas.common import StatusResponse
lazy from .auth import require_auth
lazy from .parameters import ScheduleIdPath

router = APIRouter(prefix="/bulk", tags=["bulk"], dependencies=[Depends(require_auth)])


@router.post("/assets")
async def start_bulk_assets(
    body: BulkAssetsRequest, assets: AssetsDep
) -> BulkAssetsRunResponse:
    """Start selected bulk assets jobs."""
    return assets.start_run(body)


@router.post("/assets/stop")
async def stop_bulk_assets(
    assets: AssetsDep, body: BulkAssetsStopRequest | None = None
) -> StatusResponse:
    """Stop running bulk assets jobs."""
    return assets.stop_run(body or BulkAssetsStopRequest())


@router.get("/assets/schedules")
async def list_bulk_assets_schedules(
    assets: AssetsDep,
) -> list[BulkAssetsScheduleResponse]:
    """List saved assets schedules."""
    return await assets.schedules.all()


@router.post("/assets/schedules", status_code=status.HTTP_201_CREATED)
async def create_bulk_assets_schedule(
    body: BulkAssetsScheduleWrite, assets: AssetsDep
) -> BulkAssetsScheduleResponse:
    """Create a saved assets schedule."""
    return await assets.schedules.create(body)


@router.put("/assets/schedules/{schedule_id}")
async def update_bulk_assets_schedule(
    schedule_id: ScheduleIdPath, body: BulkAssetsScheduleWrite, assets: AssetsDep
) -> BulkAssetsScheduleResponse:
    """Update a saved assets schedule."""
    return await assets.schedules.update(schedule_id, body)


@router.delete("/assets/schedules/{schedule_id}")
async def delete_bulk_assets_schedule(
    schedule_id: ScheduleIdPath, assets: AssetsDep
) -> StatusResponse:
    """Delete a saved assets schedule."""
    return await assets.schedules.delete(schedule_id)


@router.post("/assets/schedules/{schedule_id}/run")
async def run_bulk_assets_schedule(
    schedule_id: ScheduleIdPath, assets: AssetsDep
) -> StatusResponse:
    """Queue a saved assets schedule for immediate execution."""
    return await assets.schedules.run_now(schedule_id)
