"""
WebSocket ConnectionManager - broadcasts events to all connected clients.

This is the transport. Payloads arrive already redacted and validated: typed
events pass through :class:`~overture.ws.emitter.WebSocketEventEmitter`, and
realtime snapshots through :func:`~overture.services.realtime.build_realtime_snapshot`.
Nothing here inspects a payload, so redaction happens once rather than on every
hop it takes.
"""

lazy import asyncio
lazy import json
lazy import logging
lazy from collections.abc import Callable, Mapping
lazy from dataclasses import dataclass, field
lazy from typing import Any, Protocol
lazy from uuid import uuid4

lazy from fastapi import WebSocketDisconnect

lazy from ..protocols import ClientConnection
lazy from ..utils.types import JsonValue

logger = logging.getLogger(__name__)
_SEND_TIMEOUT_SECONDS = 5.0
_PING_INTERVAL_SECONDS = 30.0
_MAX_MESSAGES = 128
_MAX_BYTES = 2 * 1024 * 1024


@dataclass(slots=True)
class _Connection:
    session_hash: str | None = None
    close_code: int = 1013
    #: Frames waiting for the writer, each with its UTF-8 size.
    queue: asyncio.Queue[tuple[str, int]] = field(
        default_factory=lambda: asyncio.Queue(_MAX_MESSAGES)
    )
    queued_bytes: int = 0
    writer: asyncio.Task[None] | None = None


type ProjectionUpdater = Callable[[str, Any], None]
type EventBuilder = Callable[[], tuple[str, JsonValue] | None]


class SnapshotBuilder(Protocol):
    """Builds one realtime snapshot in three phases.

    Process-local state and its watermark are captured under the event lock,
    I/O is gathered after releasing it, and the two are assembled before the
    response is sent. Events published during I/O therefore remain newer than
    the snapshot and can be replayed by the client instead of being stamped as
    already included.
    """

    def capture(self) -> Mapping[str, Any]:
        """Read process-local state while the event stream is paused."""
        ...

    async def gather(self) -> Mapping[str, Any]:
        """Read the parts of the snapshot that need I/O."""
        ...

    def finish(
        self,
        captured: Mapping[str, Any],
        gathered: Mapping[str, Any],
        epoch: str,
        sequence: int,
    ) -> dict[str, JsonValue]:
        """Return the snapshot at one event-stream watermark."""
        ...


class ConnectionManager:
    """Manages WebSocket connections and broadcasts events."""

    def __init__(
        self,
        *,
        send_timeout: float = _SEND_TIMEOUT_SECONDS,
        ping_interval: float = _PING_INTERVAL_SECONDS,
    ) -> None:
        """Initialize instance state."""
        self._connections: dict[ClientConnection, _Connection] = {}
        self._writers: set[asyncio.Task[None]] = set()
        self._closed = False
        self._send_timeout = send_timeout
        self._ping_interval = ping_interval
        self._event_lock = asyncio.Lock()
        self._epoch = uuid4().hex
        self._sequence = 0

    async def connect(
        self, websocket: ClientConnection, *, session_hash: str | None = None
    ) -> None:
        """Accept connect."""
        if self._closed:
            raise RuntimeError("WebSocket service is stopping")
        await websocket.accept()
        state = _Connection(session_hash=session_hash)
        self._connections[websocket] = state
        state.writer = asyncio.create_task(self._write(websocket, state))
        self._writers.add(state.writer)
        state.writer.add_done_callback(self._writer_done)
        logger.debug("WebSocket connected (%d open)", len(self._connections))

    def disconnect(self, websocket: ClientConnection) -> None:
        """Remove disconnect."""
        state = self._connections.pop(websocket, None)
        if state is not None and state.writer is not None:
            state.writer.cancel()
        logger.debug("WebSocket disconnected (%d open)", len(self._connections))

    def revoke_session(self, session_hash: str) -> None:
        """Stop delivery to every socket authenticated by a revoked session."""
        for websocket, state in tuple(self._connections.items()):
            if state.session_hash == session_hash:
                state.close_code = 4001
                self.disconnect(websocket)

    async def broadcast(
        self,
        event: str,
        data: JsonValue = None,
        *,
        before_publish: ProjectionUpdater | None = None,
    ) -> None:
        """Send an event to all connected clients."""
        async with self._event_lock:
            if before_publish is not None:
                before_publish(event, data)
            self._broadcast_unlocked(event, data)

    async def broadcast_built(self, builder: EventBuilder) -> bool:
        """Mutate a projection and broadcast its resulting event under one lock."""
        async with self._event_lock:
            built = builder()
            if built is None:
                return False
            event, data = built
            self._broadcast_unlocked(event, data)
            return True

    async def build_snapshot(self, builder: SnapshotBuilder) -> dict[str, JsonValue]:
        """Build a snapshot without covering events published during its I/O."""
        async with self._event_lock:
            captured = builder.capture()
            epoch = self._epoch
            sequence = self._sequence
        gathered = await builder.gather()
        return builder.finish(captured, gathered, epoch, sequence)

    async def send_realtime_snapshot(
        self,
        websocket: ClientConnection,
        builder: SnapshotBuilder,
    ) -> None:
        """Send one coherent realtime snapshot to a reconnecting browser."""
        async with self._event_lock:
            captured = builder.capture()
            epoch = self._epoch
            sequence = self._sequence
        gathered = await builder.gather()
        async with self._event_lock:
            payload = builder.finish(captured, gathered, epoch, sequence)
            self._enqueue(
                websocket,
                self._event_message("realtime.snapshot", payload, sequence),
            )

    def _enqueue(
        self, websocket: ClientConnection, message: str, size: int | None = None
    ) -> None:
        """Queue one frame without waiting on a network operation."""
        state = self._connections.get(websocket)
        if state is None:
            return
        if size is None:
            size = len(message.encode("utf-8"))
        if state.queue.full() or state.queued_bytes + size > _MAX_BYTES:
            self.disconnect(websocket)
            return
        state.queued_bytes += size
        state.queue.put_nowait((message, size))

    async def _write(self, websocket: ClientConnection, state: _Connection) -> None:
        try:
            while True:
                message, size = await state.queue.get()
                try:
                    async with asyncio.timeout(self._send_timeout):
                        await websocket.send_text(message)
                finally:
                    state.queued_bytes -= size
                    state.queue.task_done()
        except TimeoutError, WebSocketDisconnect, RuntimeError:
            logger.debug("WebSocket writer disconnected")
        except Exception:
            logger.exception("WebSocket writer failed")
        finally:
            self._connections.pop(websocket, None)
            try:
                async with asyncio.timeout(self._send_timeout):
                    await websocket.close(code=state.close_code)
            except TimeoutError, WebSocketDisconnect, RuntimeError:
                logger.debug("WebSocket already closed")

    def _writer_done(self, task: asyncio.Task[None]) -> None:
        self._writers.discard(task)
        if not task.cancelled() and (failure := task.exception()) is not None:
            logger.error("WebSocket cleanup failed", exc_info=failure)

    async def close(self) -> None:
        """Cancel and await all connection writers."""
        self._closed = True
        tasks = tuple(self._writers)
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("WebSocket shutdown failed")
        self._connections.clear()

    def _event_message(self, event: str, data: JsonValue, sequence: int) -> str:
        """Serialize one sequenced server event envelope."""
        return json.dumps(
            {
                "epoch": self._epoch,
                "sequence": sequence,
                "event": event,
                "data": data,
            }
        )

    def _broadcast_unlocked(self, event: str, data: JsonValue) -> None:
        """Broadcast one event while the caller holds the event-stream lock."""
        self._sequence += 1
        message = self._event_message(event, data, self._sequence)
        size = len(message.encode("utf-8"))
        for websocket in tuple(self._connections):
            self._enqueue(websocket, message, size)

    async def start_ping_loop(self) -> None:
        """Send keepalives through each connection's sole writer."""
        while True:
            await asyncio.sleep(self._ping_interval)
            for websocket in tuple(self._connections):
                self._enqueue(websocket, '{"event": "ping"}')

    @property
    def active_connections(self) -> int:
        """Return the number of active WebSocket connections."""
        return len(self._connections)

    @property
    def epoch(self) -> str:
        """Return the process-local event stream epoch."""
        return self._epoch

    @property
    def sequence(self) -> int:
        """Return the latest event stream watermark."""
        return self._sequence
