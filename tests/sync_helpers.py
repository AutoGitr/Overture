"""Run a full library sync over an in-memory listing, as the sync runner does."""

lazy import tempfile
lazy from pathlib import Path

lazy from overture.jobs.tally import SyncTally
lazy from overture.media_servers.adapters import (
    ServerItem,
    SyncProgressCallback,
    SyncStopCheck,
)
lazy from overture.services.sync.reconciler import LibraryReconciler, SyncResult
lazy from overture.services.sync.staging import StagedListing


async def sync_full(
    reconciler: LibraryReconciler,
    server_items: list[ServerItem],
    *,
    library_ids: list[str] | None = None,
    tally: SyncTally | None = None,
    progress_cb: SyncProgressCallback | None = None,
    stop_check: SyncStopCheck | None = None,
) -> SyncResult:
    """Stage *server_items* as one complete listing and reconcile it.

    Items missing from the listing are marked removed, within *library_ids*
    when given, exactly as after a full sync.
    """
    tally = tally if tally is not None else SyncTally()
    tally.total = len(server_items)
    with tempfile.TemporaryDirectory() as directory:
        async with StagedListing(Path(directory) / "provider.sqlite") as listing:
            await listing.append(server_items)
            return await reconciler.sync_staged(
                listing,
                library_ids=library_ids,
                tally=tally,
                progress_cb=progress_cb,
                stop_check=stop_check,
            )
