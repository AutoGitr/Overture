"""Run a full library sync over an in-memory listing, as the sync runner does."""

lazy import tempfile
lazy from dataclasses import dataclass, field
lazy from pathlib import Path

lazy from overture.jobs.progress_log import (
    JobOutcome,
    LogServer,
    OutcomeCounts,
    log_entry,
)
lazy from overture.media_servers.adapters import ServerItem, SyncStopCheck
lazy from overture.services.sync.reconciler import (
    LibraryReconciler,
    ServerTurn,
    SyncResult,
)
lazy from overture.services.sync.staging import StagedListing
lazy from tests.media_servers import TEST_SERVER_ID
lazy from tests.runtime_helpers import server_sections


@dataclass(slots=True)
class RecordedReport:
    """A :class:`~overture.jobs.progress_log.Report` keeping what a run would log."""

    lines: list[str] = field(default_factory=list[str])
    counts: OutcomeCounts = field(default_factory=OutcomeCounts)
    #: Targets reported as finished, as a run's ``done``.
    done: int = 0

    async def __call__(
        self,
        outcome: JobOutcome,
        target: str,
        reason: str,
        /,
        *,
        count: int = 1,
        finished: bool = True,
        server: LogServer | None = None,
    ) -> None:
        entry = log_entry(outcome, target, reason, server=server, count=count)
        self.counts.add(entry)
        self.lines.append(entry.format())
        self.done += count if finished else 0

    def __getitem__(self, outcome: JobOutcome) -> int:
        """Return the targets reported with *outcome*."""
        return self.counts.targets[outcome]


async def sync_full(
    reconciler: LibraryReconciler,
    server_items: list[ServerItem],
    *,
    library_ids: list[str] | None = None,
    report: RecordedReport | None = None,
    stop_check: SyncStopCheck | None = None,
) -> tuple[SyncResult, RecordedReport]:
    """Stage *server_items* as one complete listing and reconcile it.

    The server lists the libraries its items are filed under. Items missing
    from the listing are marked removed, within *library_ids* when given,
    exactly as after a full sync. Returns what it did and what it reported.
    """
    report = report if report is not None else RecordedReport()
    await reconciler.record_libraries(TEST_SERVER_ID, server_sections(server_items))
    with tempfile.TemporaryDirectory() as directory:
        async with StagedListing(Path(directory) / "provider.sqlite") as listing:
            await listing.append(server_items)
            result = await reconciler.sync_staged(
                listing,
                ServerTurn(TEST_SERVER_ID),
                library_ids=library_ids,
                report=report,
                stop_check=stop_check,
            )
    return result, report
