"""Sync execution isolated from the scheduler and job lifecycle manager."""

lazy import asyncio
lazy from pathlib import Path
lazy from typing import Any

lazy from ... import protocols
lazy from ...jobs.progress_log import JobLogEntry, JobOutcome, log_entry
lazy from ...jobs.runner import JobContext, ManagedJob, run_managed_job
lazy from ...jobs.tally import SyncTally
lazy from ...media_servers.base import BaseMediaServerProvider
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...utils.temporary import operation_directory
lazy from .collection_sync import CollectionSync
lazy from .reconciler import LibraryReconciler
lazy from .staging import StagedListing
lazy from .tmdb_enrichment import TmdbEnrichment
lazy from .tmdb_seasons import TmdbSeasonSync


async def run_sync(
    context: JobContext,
    *,
    library_ids: list[str] | None = None,
    items: bool = True,
    include_collections: bool = True,
    collection_groups: list[str] | None = None,
    provider_registry: ProviderRegistry,
    reconciler: LibraryReconciler,
    config_dir: Path,
    tmdb_seasons: TmdbSeasonSync,
    enrichment: TmdbEnrichment,
    collections: CollectionSync,
    groups: protocols.CollectionGroups,
) -> None:
    """Run a full sync: reconcile the server, then TMDB seasons, facts and collections.

    Collections are every one the server lists, or only *collection_groups*;
    without *items* only they are synced, from what earlier syncs stored.

    Publishes lifecycle events (started -> progress* -> completed | stopped |
    failed) through the managed job context, which also owns snapshot
    persistence for reconnect restore.
    """
    tally = SyncTally()
    async with run_managed_job(context, tally) as job:
        await job.started()
        if job.stop_requested():
            return
        await provider_registry.require_reachable()

        async def sync() -> None:
            if items:
                tmdb_items = await tmdb_seasons.targets()
                await _sync_with_provider(
                    job,
                    provider_registry.provider,
                    reconciler,
                    library_ids=library_ids,
                    config_dir=config_dir,
                    tmdb_count=len(tmdb_items),
                )
                await tmdb_seasons.run(tmdb_items, job)
            # Criteria test TMDB facts, whatever the run then syncs.
            await enrichment.run(job, library_ids=library_ids)
            if include_collections:
                await collections.run(job, library_ids=library_ids)
            # Having read what the server holds, make it match what Overture
            # manages: every group, or only the chosen ones.
            if provider_registry.collections is not None and (
                include_collections or collection_groups
            ):
                await _sync_groups(
                    job,
                    groups,
                    None if include_collections else collection_groups,
                    library_ids,
                )

        # A stop must interrupt provider calls and rate-limit waits as well
        # as the loops between them. Each writer rolls back on cancellation.
        worker = asyncio.create_task(sync())
        stopper = asyncio.create_task(context.stop_event.wait())
        try:
            await asyncio.wait((worker, stopper), return_when=asyncio.FIRST_COMPLETED)
            if job.stop_requested():
                worker.cancel()
            await worker
        except asyncio.CancelledError:
            if not job.stop_requested():
                raise
        finally:
            worker.cancel()
            stopper.cancel()
            await asyncio.gather(worker, stopper, return_exceptions=True)


async def _sync_groups(
    job: ManagedJob[SyncTally],
    groups: protocols.CollectionGroups,
    names: list[str] | None,
    library_ids: list[str] | None,
) -> None:
    """Run each group's set and sync its collections.

    Without *names* every group is synced; *library_ids* limits each group
    to its collections in those libraries.
    """
    existing = await groups.names()
    for name in existing if names is None else names:
        if job.stop_requested():
            return
        if name not in existing:
            continue
        try:
            result = await groups.sync(name, library_ids=library_ids)
        except Exception as exc:
            await job.report(
                JobOutcome.ERROR, f"Group {name}", str(exc), finished=False
            )
            continue
        for title, error in result.errors.items():
            await job.report(JobOutcome.ERROR, title, error, finished=False)
        await job.progress(
            log=log_entry(
                JobOutcome.STARTED,
                f"Group {name}",
                f"{result.synced} synced, {len(result.created)} created, "
                f"{len(result.withheld)} taken off the server",
            )
        )


async def _sync_with_provider(
    job: ManagedJob[SyncTally],
    provider: BaseMediaServerProvider[Any],
    reconciler: LibraryReconciler,
    *,
    library_ids: list[str] | None,
    config_dir: Path,
    tmdb_count: int,
) -> None:
    """Stage the provider's complete listing, then reconcile it.

    The run counts the staged server items and planned TMDB shows, with its
    total fixed before the first item is reconciled.
    """
    await job.progress(
        log=log_entry(
            JobOutcome.STARTED,
            "Sync",
            f"reading libraries from {provider.server_type.display_name}",
        ),
    )

    async def on_progress(entry: JobLogEntry) -> None:
        await job.progress(log=entry)

    await reconciler.record_libraries(await provider.get_sections())
    with operation_directory(config_dir) as directory:
        async with StagedListing(directory / "provider.sqlite") as listing:
            async for batch in provider.iter_items(library_ids=library_ids):
                if job.stop_requested():
                    return
                await reconciler.fill_deferred_directors(provider, batch)
                await listing.append(batch)
            await job.planned(await listing.count() + tmdb_count)
            await reconciler.sync_staged(
                listing,
                library_ids=library_ids,
                tally=job.tally,
                progress_cb=on_progress,
                stop_check=job.stop_requested,
            )
