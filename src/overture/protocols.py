"""Minimal structural interfaces for runtime-injected services."""

lazy from collections.abc import Awaitable, Callable
lazy from typing import Any, Protocol

#: Reports percent-complete and a stage label while long work runs.
type ProgressCallback = Callable[[int, str], Awaitable[None]]


class ClientConnection(Protocol):
    """The WebSocket surface the event stream sends through.

    The connection layer only ever accepts a client and writes frames to it,
    so that is what it asks for. Declaring the parameters positionally keeps
    any conforming client - Starlette's ``WebSocket`` included - compatible
    regardless of what it names them.
    """

    async def accept(self) -> None: ...

    async def close(self, code: int = 1000) -> None: ...

    async def send_text(self, data: str, /) -> None: ...

    async def send_json(self, data: Any, /) -> None: ...


class ConnectivityProbe(Protocol):
    """Anything whose reachability the status endpoint reports."""

    async def test_connection(self) -> bool: ...


class EventPublisher(Protocol):
    """Publishes validated events to connected clients."""

    async def broadcast(
        self,
        event: str,
        payload: Any = None,
        *,
        before_publish: Callable[[str, Any], None] | None = None,
    ) -> None: ...

    async def broadcast_built(
        self,
        builder: Callable[[], tuple[str, Any] | None],
    ) -> bool: ...
