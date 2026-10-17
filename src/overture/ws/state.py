"""Runtime-owned background jobs shared by services and realtime snapshots."""

lazy import asyncio

lazy from .. import protocols
lazy from ..jobs.gate import LibraryGate
lazy from ..jobs.kinds import JobKind
lazy from ..jobs.lifecycle import ManagedJobLifecycle
lazy from ..jobs.slot import ManagedBackgroundJob


class BackgroundJobRegistry:
    """Named slots for long-running router-owned jobs."""

    def __init__(self, publisher: protocols.EventPublisher) -> None:
        def slot(kind: JobKind) -> ManagedBackgroundJob:
            return ManagedBackgroundJob(ManagedJobLifecycle(kind), publisher)

        self.art_match = slot(JobKind.BULK_ART)
        self.theme_match = slot(JobKind.BULK_THEME)
        self.asset_scan = slot(JobKind.ASSET_SCAN)
        self.server_audit = slot(JobKind.SERVER_AUDIT)
        #: Fixes audit findings apart from the audit, whose results it marks.
        self.server_audit_fix = slot(JobKind.SERVER_AUDIT_FIX)
        #: Shared with the sync engine, whose full syncs these jobs exclude.
        self.library_gate = LibraryGate()

    def values(self) -> tuple[ManagedBackgroundJob, ...]:
        return (
            self.art_match,
            self.theme_match,
            self.asset_scan,
            self.server_audit,
            self.server_audit_fix,
        )

    async def stop(self) -> None:
        """Stop every router-owned job before its runtime dependencies close."""
        await asyncio.gather(*(job.shutdown() for job in self.values()))
