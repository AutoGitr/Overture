"""Runs one library operation at a time."""

lazy import asyncio
lazy from collections.abc import Callable, Coroutine
lazy from dataclasses import dataclass
lazy from typing import Any, Literal

lazy from ..utils.errors import PublicServiceError
lazy from .runner import JobContext
lazy from .slot import ManagedBackgroundJob

#: The operation a run belongs to; ``sync`` is a full sync.
type GateSide = Literal["sync", "assets", "renamer", "audit"]

#: Receives what a waiting run waits for, then ``None`` once it runs.
type WaitReporter = Callable[[str | None], None]


@dataclass(slots=True, frozen=True, eq=False)
class _Lease:
    side: GateSide
    label: str


def _conflicts(side: GateSide, other: GateSide) -> bool:
    """Return whether runs of *side* and *other* must not overlap.

    Runs of one operation share it, such as Assets' art and theme jobs.
    Downloads stay outside: each writes under its item's asset lock, which a
    sync takes too, into the folder the item has once the lock is held.
    """
    return side != other


class LibraryGate:
    """Admit one operation at a time: a full sync, Assets, Renamer or Audit.

    New-media polling only adds items and stays outside.
    """

    def __init__(self) -> None:
        self._leases: list[_Lease] = []
        self._released = asyncio.Event()

    def blocker(self, side: GateSide) -> str | None:
        """Return what keeps *side* out right now, or ``None``."""
        labels = dict.fromkeys(
            lease.label for lease in self._leases if _conflicts(side, lease.side)
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
            PublicServiceError: When a conflicting operation holds the gate.
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

        The gate is held from the moment it is free, so another operation
        cannot slip in while this run waits for its slot.
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
