"""Sync execution isolated from the scheduler and job lifecycle manager."""

lazy from pathlib import Path
lazy from typing import Any

lazy from ...jobs.progress_log import JobLogEntry, JobOutcome, log_entry
lazy from ...jobs.runner import JobContext, ManagedJob, run_managed_job
lazy from ...jobs.tally import SyncTally
lazy from ...media_servers.base import BaseMediaServerProvider
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...utils.temporary import operation_directory
lazy from .collection_sync import CollectionSync
lazy from .reconciler import LibraryReconciler
lazy from .staging import StagedListing
lazy from .tmdb_seasons import TmdbSeasonSync


async def run_sync(
    context: JobContext,
    *,
    library_ids: list[str] | None = None,
    provider_registry: ProviderRegistry,
    reconciler: LibraryReconciler,
    config_dir: Path,
    tmdb_seasons: TmdbSeasonSync,
    collections: CollectionSync,
) -> None:
    """Run a full sync: reconcile the server, then TMDB seasons and collections.

    Publishes lifecycle events (started -> progress* -> completed | stopped |
    failed) through the managed job context, which also owns snapshot
    persistence for reconnect restore.
    """
    tally = SyncTally()
    async with run_managed_job(context, tally) as job:
        await job.started()

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
        await collections.run(job, library_ids=library_ids)


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
