"""Realtime snapshot route."""

lazy from fastapi import APIRouter, Depends

lazy from ..dependencies import RuntimeDep
lazy from ..schemas.realtime import RealtimeSnapshot
lazy from ..services.realtime import RealtimeSnapshotBuilder
lazy from .auth import require_auth

router = APIRouter(
    prefix="/realtime",
    tags=["realtime"],
    dependencies=[Depends(require_auth)],
)


@router.get("/snapshot")
async def get_realtime_snapshot(
    runtime: RuntimeDep,
) -> RealtimeSnapshot:
    """Return the current process-local realtime state."""
    payload = await runtime.websockets.build_snapshot(RealtimeSnapshotBuilder(runtime))
    return RealtimeSnapshot.model_validate(payload)
