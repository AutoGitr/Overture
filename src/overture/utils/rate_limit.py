"""Pausing requests to a service while it rate-limits them."""

lazy from asyncio import sleep
lazy from dataclasses import dataclass
lazy from time import monotonic

lazy import httpx2

#: Seconds the first rate limit pauses requests for; each further one doubles
#: the pause, up to the maximum.
PAUSE_MIN = 60
PAUSE_MAX = 900


def retry_after_seconds(response: httpx2.Response) -> int | None:
    """Return the seconds a response's ``Retry-After`` asks for, if it gives them."""
    retry_after = response.headers.get("Retry-After", "")
    return int(retry_after) if retry_after.isdigit() else None


@dataclass(slots=True)
class _Pause:
    until: float
    next_length: int


class RateLimitPause[K]:
    """Pause every request to a key while it is rate-limited.

    A rate limit pauses the key for :data:`PAUSE_MIN` seconds, or longer when
    the service asks, doubling with each further rate limit up to
    :data:`PAUSE_MAX`. A success resets the next pause to the minimum.
    """

    def __init__(self) -> None:
        # Only keys rate-limited since their last success have an entry.
        self._pauses: dict[K, _Pause] = {}

    def remaining(self, key: K) -> float:
        """Return the seconds left in *key*'s pause, or 0 when it is not paused."""
        pause = self._pauses.get(key)
        return max(0.0, pause.until - monotonic()) if pause else 0.0

    def longest(self) -> tuple[K, float] | None:
        """Return the key paused for longest and its seconds left, if any is."""
        return max(
            (
                (key, remaining)
                for key in self._pauses
                if (remaining := self.remaining(key)) > 0
            ),
            key=lambda paused: paused[1],
            default=None,
        )

    async def wait(self, key: K) -> None:
        """Return once *key* is not paused."""
        # A request already in flight can extend the pause while this one sleeps.
        while True:
            delay = self.remaining(key)
            if delay <= 0:
                return
            await sleep(delay)

    def limited(self, key: K, *, retry_after: int | None = None) -> int:
        """Pause *key* after a rate limit; return the pause's length in seconds."""
        pause = self._pauses.setdefault(key, _Pause(0.0, PAUSE_MIN))
        length = min(max(pause.next_length, retry_after or 0), PAUSE_MAX)
        pause.until = max(pause.until, monotonic() + length)
        pause.next_length = min(length * 2, PAUSE_MAX)
        return length

    def succeeded(self, key: K) -> None:
        """Reset *key*'s next pause after a request it answered."""
        pause = self._pauses.get(key)
        if pause is None:
            return
        if pause.until <= monotonic():
            del self._pauses[key]
        else:
            pause.next_length = PAUSE_MIN
