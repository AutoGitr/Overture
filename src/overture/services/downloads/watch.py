"""Following the download jobs one caller queued."""

lazy import asyncio
lazy from collections.abc import AsyncIterator, Callable
lazy from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DownloadOutcome:
    """How one watched download job ended."""

    target: str
    error: str | None = None
    #: The download matched the local file, so nothing was written.
    unchanged: bool = False
    #: The download was cancelled before it finished.
    cancelled: bool = False


class DownloadWatch:
    """The download jobs one run queued, and how each of them ended.

    A bulk run queues far more downloads than it could wait for one at a time.
    The live stream reports them concurrently while matching continues, then
    keeps the run alive until the final file has landed.
    """

    def __init__(self) -> None:
        self._targets: dict[str, str] = {}
        self._outcomes: asyncio.Queue[DownloadOutcome | None] = asyncio.Queue()
        self._closed = False

    @property
    def active_job_ids(self) -> list[str]:
        """Return the IDs of download jobs currently tracked by this watch."""
        return list(self._targets)

    def tracking(self, target: str) -> Callable[[str], None]:
        """Return the hook that puts one job, named *target*, under this watch.

        The queue takes the hook rather than the job id, so a job is watched
        before it can run: a download that finished between being queued and
        being registered would otherwise never be reported.
        """

        def track(job_id: str) -> None:
            if self._closed:
                raise RuntimeError("Download watch is closed")
            self._targets[job_id] = target

        return track

    def settle(
        self,
        job_id: str,
        error: str | None,
        *,
        unchanged: bool = False,
        cancelled: bool = False,
    ) -> None:
        """Record how one job ended, if it is one this watch queued."""
        target = self._targets.pop(job_id, None)
        if target is not None:
            self._outcomes.put_nowait(
                DownloadOutcome(target, error, unchanged, cancelled)
            )

    async def stream(self) -> AsyncIterator[DownloadOutcome]:
        """Yield outcomes while new downloads may still join the watch."""
        while not self._closed or self._targets or not self._outcomes.empty():
            outcome = await self._outcomes.get()
            if outcome is not None:
                yield outcome

    def close(self) -> None:
        """Declare that no more downloads will join, waking the stream."""
        if not self._closed:
            self._closed = True
            self._outcomes.put_nowait(None)
