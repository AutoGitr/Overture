"""Keeps a full sync apart from the jobs that plan their work from the library."""

lazy import asyncio
lazy from collections.abc import Callable, Coroutine
lazy from dataclasses import dataclass
lazy from typing import Any, Literal

lazy from ..utils.errors import PublicServiceError
lazy from .runner import JobContext
lazy from .slot import ManagedBackgroundJob

#: ``sync`` is a full sync; ``items`` is Assets, Renamer or Server Audit.
type GateSide = Literal["sync", "items"]

#: Receives what a waiting run waits for, then ``None`` once it runs.
type WaitReporter = Callable[[str | None], None]


@dataclass(slots=True, frozen=True, eq=False)
class _Lease:
    side: GateSide
    label: str


class LibraryGate:
    """Admit any number of item jobs together, or one full sync, never both.

    Assets, Renamer and Audit plan their work from which items exist and
    where their folders are. A full sync rewrites exactly that, so a plan made
    while it runs can name hidden items, miss imported ones, or point at a
    moved folder. New-media polling only adds items and stays outside.
    """

    def __init__(self) -> None:
        self._leases: list[_Lease] = []
        self._released = asyncio.Event()

    def blocker(self, side: GateSide) -> str | None:
        """Return what keeps *side* out right now, or ``None``."""
        labels = dict.fromkeys(
            lease.label for lease in self._leases if lease.side != side
        )
        return ", ".join(labels) or None

    def start(
        self,
        side: GateSide,
        job: ManagedBackgroundJob,
        job_factory: Callable[[JobContext], Coroutine[Any, Any, None]],
    ) -> bool:
        """Start a run in *job* now, returning ``False`` when the slot is busy.

        Raises:
            PublicServiceError: When the other side holds the gate.
        """
        if (blocker := self.blocker(side)) is not None:
            raise PublicServiceError(409, f"Wait for {blocker} to finish")
        if not job.start_with_context(job_factory):
            return False
        task = job.task
        if task is not None:
            self._hold_until_done(self._enter(side, job), task)
        return True

    async def run(
        self,
        side: GateSide,
        job: ManagedBackgroundJob,
        job_factory: Callable[[JobContext], Coroutine[Any, Any, None]],
        *,
        report: WaitReporter,
    ) -> None:
        """Wait for the gate and the slot, run in *job*, and wait for the end.

        The gate is held from the moment it is free, so the other side cannot
        slip in while this run waits for its slot.
        """
        while (blocker := self.blocker(side)) is not None:
            report(blocker)
            await self._released.wait()
        lease = self._enter(side, job)
        started = False

        def on_start(task: asyncio.Task[None]) -> None:
            nonlocal started
            started = True
            self._hold_until_done(lease, task)
            report(None)

        try:
            if job.running:
                report(job.name)
            await job.run_when_idle(job_factory, on_start=on_start)
        finally:
            if not started:
                self._leave(lease)

    def _enter(self, side: GateSide, job: ManagedBackgroundJob) -> _Lease:
        lease = _Lease(side, "full sync" if side == "sync" else job.name)
        self._leases.append(lease)
        return lease

    def _hold_until_done(self, lease: _Lease, task: asyncio.Task[None]) -> None:
        task.add_done_callback(lambda _task: self._leave(lease))

    def _leave(self, lease: _Lease) -> None:
        if lease in self._leases:
            self._leases.remove(lease)
            self._released.set()
            self._released = asyncio.Event()
