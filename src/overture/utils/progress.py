"""Progress reporting for work that runs in named steps."""

lazy import time
lazy from collections.abc import Awaitable, Callable
lazy from typing import NamedTuple


class ProgressUpdate(NamedTuple):
    """How far a job has come: its overall percentage and the step it is on."""

    percent: int
    stage: str
    #: The step's position, counted from 1.
    step: int
    steps: int


#: Receives each progress update while long work runs.
type ProgressCallback = Callable[[ProgressUpdate], Awaitable[None]]

#: Reports how much of a download has arrived, and how much was expected.
type BytesProgress = Callable[[int, int | None], Awaitable[None]]

#: How often a step may publish its own progress, in seconds.
_MIN_INTERVAL = 0.25


class StepProgress:
    """Reports a job's way through a fixed list of steps, each an equal share.

    Entering a step always publishes. Within a step, updates that repeat a
    percentage, or that arrive faster than :data:`_MIN_INTERVAL`, are
    dropped: a downloader that reports every chunk should not publish an
    event per chunk.
    """

    def __init__(self, callback: ProgressCallback, steps: tuple[str, ...]) -> None:
        """Report *callback* progress through *steps*, in order."""
        self._callback = callback
        self._steps = steps
        self._index = -1
        self._percent = -1
        self._published_at = 0.0

    async def enter(self, stage: str) -> None:
        """Start *stage*, which must come later in the list than the current one."""
        self._index = self._steps.index(stage, self._index + 1)
        self._percent = -1
        self._published_at = 0.0
        await self.report(0)

    async def report(self, fraction: float) -> None:
        """Report the fraction of the current step that is finished, from 0 to 1."""
        done = self._index + min(max(fraction, 0.0), 1.0)
        percent = round(100 * done / len(self._steps))
        now = time.monotonic()
        if percent == self._percent or now - self._published_at < _MIN_INTERVAL:
            return
        self._percent = percent
        self._published_at = now
        await self._callback(
            ProgressUpdate(
                percent, self._steps[self._index], self._index + 1, len(self._steps)
            )
        )

    async def report_bytes(self, received: int, total: int | None) -> None:
        """Report progress by byte count, when the total length is known."""
        if total:
            await self.report(received / total)
