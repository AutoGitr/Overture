"""Whether the media server answered Overture's last request."""

lazy from collections.abc import Callable
lazy from dataclasses import dataclass

lazy from ..domain import MediaServerState


@dataclass(slots=True, frozen=True)
class MediaServerHealth:
    """The media server's state, as its last request found it."""

    state: MediaServerState = MediaServerState.UNKNOWN
    #: What the person running Overture can do about it, when it is down.
    message: str = ""


class MediaServerHealthTracker:
    """Track request outcomes and tell a listener when the state changes."""

    def __init__(self) -> None:
        self.current = MediaServerHealth()
        self._listener: Callable[[MediaServerHealth], None] | None = None

    def listen(self, listener: Callable[[MediaServerHealth], None]) -> None:
        """Call *listener* with the new health whenever the state changes."""
        self._listener = listener

    def record(self, state: MediaServerState, message: str = "") -> None:
        """Note what one request found."""
        health = MediaServerHealth(state, message)
        if health == self.current:
            return
        self.current = health
        if self._listener is not None:
            self._listener(health)
