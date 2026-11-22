"""Realtime snapshot route."""

lazy from ..dependencies import RealtimeSnapshotDep, WebSocketsDep
lazy from ..schemas.realtime import RealtimeSnapshot
lazy from .auth import authenticated_router

router = authenticated_router(prefix="/realtime", tags=["realtime"])


@router.get("/snapshot")
async def get_realtime_snapshot(
    websockets: WebSocketsDep, snapshot: RealtimeSnapshotDep
) -> RealtimeSnapshot:
    """Return the current process-local realtime state."""
    payload = await websockets.build_snapshot(snapshot)
    return RealtimeSnapshot.model_validate(payload)
