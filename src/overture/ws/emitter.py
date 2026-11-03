"""Typed WebSocket event emitter.

Every event is validated against its registered schema and serialised by it
before the connection layer sends it, so its free text (``PublicText``) is
redacted here and nowhere else. Job runners and the connection manager hand
payloads through untouched.
"""

lazy from collections.abc import Callable
lazy from typing import Any

lazy from .connection_manager import (
    ConnectionManager,
    ProjectionUpdater,
)
lazy from .events import validate_event_payload


class WebSocketEventEmitter:
    """Validate event payloads before sending them through the connection layer."""

    def __init__(self, manager: ConnectionManager) -> None:
        self._manager = manager

    async def broadcast(
        self,
        event: str,
        payload: Any = None,
        *,
        before_publish: ProjectionUpdater | None = None,
    ) -> None:
        """Broadcast a registered event to all clients."""
        data = validate_event_payload(event, payload)
        await self._manager.broadcast(
            event,
            data,
            before_publish=before_publish,
        )

    async def broadcast_built(
        self,
        builder: Callable[[], tuple[str, Any] | None],
    ) -> bool:
        """Build a projection mutation and its validated event under one lock."""

        def validated_builder():
            built = builder()
            if built is None:
                return None
            event, data = built
            return event, validate_event_payload(event, data)

        return await self._manager.broadcast_built(validated_builder)
