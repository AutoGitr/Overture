"""Realtime snapshot route."""

lazy from fastapi import APIRouter, Depends

lazy from ..dependencies import RealtimeSnapshotDep, WebSocketsDep
lazy from ..schemas.realtime import RealtimeSnapshot
lazy from .auth import require_auth

router = APIRouter(
    prefix="/realtime",
    tags=["realtime"],
    dependencies=[Depends(require_auth)],
)


@router.get("/snapshot")
async def get_realtime_snapshot(
    websockets: WebSocketsDep, snapshot: RealtimeSnapshotDep
) -> RealtimeSnapshot:
    """Return the current process-local realtime state."""
    payload = await websockets.build_snapshot(snapshot)
    return RealtimeSnapshot.model_validate(payload)
