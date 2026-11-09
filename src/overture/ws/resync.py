"""WebSocket client-resync helpers."""

lazy import logging

lazy from ..protocols import ClientConnection
lazy from .connection_manager import ConnectionManager, SnapshotBuilder

logger = logging.getLogger(__name__)


async def send_client_resync(
    websocket: ClientConnection,
    websockets: ConnectionManager,
    snapshot: SnapshotBuilder,
) -> None:
    """Send one coherent realtime snapshot to a reconnecting client.

    A client that never receives its snapshot cannot apply any event, so a
    failure here is what leaves a browser silently stale. It is logged as a
    warning rather than swallowed, and the client retries on its own backoff.
    """
    try:
        await websockets.send_realtime_snapshot(websocket, snapshot)
    except (RuntimeError, ValueError, OSError) as exc:
        logger.warning(
            "Could not send a realtime snapshot to a reconnecting client: %s", exc
        )
