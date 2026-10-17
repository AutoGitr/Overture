"""Progress reporting for work that runs in stages."""

lazy import time
lazy from collections.abc import Awaitable, Callable

lazy from .. import protocols

#: Reports how much of a download has arrived, and how much was expected.
type BytesProgress = Callable[[int, int | None], Awaitable[None]]

#: How often one stage may publish, in seconds.
_MIN_INTERVAL = 0.25


class StageProgress:
    """Maps one stage's own progress onto a slice of a job's overall bar.

    A stage reports the fraction of itself that is finished and this turns
    that into the job's percentage. Updates that repeat a percentage, or that
    arrive faster than :data:`_MIN_INTERVAL`, are dropped: a downloader that
    reports every chunk should not publish an event per chunk.
    """

    def __init__(
        self,
        callback: protocols.ProgressCallback,
        *,
        stage: str,
        start: int,
        end: int,
    ) -> None:
        """Report *callback* percentages between *start* and *end*."""
        self._callback = callback
        self._stage = stage
        self._start = start
        self._span = end - start
        self._percent = -1
        self._published_at = 0.0

    async def report(self, fraction: float) -> None:
        """Report the fraction of this stage that is finished, from 0 to 1."""
        percent = self._start + round(self._span * min(max(fraction, 0.0), 1.0))
        now = time.monotonic()
        if percent == self._percent or now - self._published_at < _MIN_INTERVAL:
            return
        self._percent = percent
        self._published_at = now
        await self._callback(percent, self._stage)

    async def report_bytes(self, received: int, total: int | None) -> None:
        """Report progress by byte count, when the total length is known."""
        if total:
            await self.report(received / total)
