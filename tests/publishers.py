"""Event publishers for tests that run services without a WebSocket hub."""

lazy from collections.abc import Callable
lazy from typing import Any


class NullEventPublisher:
    """Apply projection updates the way the hub does, and send nothing."""

    async def broadcast(
        self,
        event: str,
        payload: Any = None,
        *,
        before_publish: Callable[[str, Any], None] | None = None,
    ) -> None:
        """Apply projection updates without sending a WebSocket event."""
        if before_publish is not None:
            before_publish(event, payload)

    async def broadcast_built(
        self,
        builder: Callable[[], tuple[str, Any] | None],
    ) -> bool:
        """Run the projection builder without sending a WebSocket event."""
        return builder() is not None
