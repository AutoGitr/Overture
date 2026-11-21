"""Sync execution isolated from the scheduler and job lifecycle manager."""

lazy import asyncio
lazy from collections import Counter
lazy from collections.abc import Sequence
lazy from contextlib import AsyncExitStack
lazy from functools import partial
lazy from pathlib import Path

lazy from ... import protocols
lazy from ...domain import MediaType, library_parts
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import JobContext, ManagedJob, run_managed_job
lazy from ...jobs.tally import JobTally
lazy from ...media_servers.errors import MediaServerError
lazy from ...media_servers.registry import Provider, ProviderRegistry, log_server
lazy from ...schemas.collections import CollectionGroupSyncResult
lazy from ...utils.temporary import operation_directory
lazy from .collection_sync import CollectionSync
lazy from .reconciler import LibraryReconciler, ServerTurn
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
    collection_ids: list[int] | None = None,
    provider_registry: ProviderRegistry,
    reconciler: LibraryReconciler,
    config_dir: Path,
    tmdb_seasons: TmdbSeasonSync,
    enrichment: TmdbEnrichment,
    collections: CollectionSync,
    groups: protocols.CollectionGroups,
) -> None:
    """Run a full sync: reconcile the servers, then TMDB seasons, facts and collections.

    Every configured server is synced, or those holding *library_ids*. A
    server that cannot be reached is reported and left as it was, so none of
    its titles is taken for removed. Collections are every one the servers
    list, or only *collection_groups* and *collection_ids*; without *items*
    only they are synced, from what earlier syncs stored.

    Publishes lifecycle events (started -> progress* -> completed | stopped |
    failed) through the managed job context, which also owns snapshot
    persistence for reconnect restore.
    """
    async with run_managed_job(context, JobTally()) as job:
        await job.started()
        if job.stop_requested():
            return
        servers = await _reachable(job, provider_registry, library_ids)

        async def sync() -> None:
            if items:
                tmdb_items = await tmdb_seasons.targets()
                await _sync_with_providers(
                    job,
                    servers,
                    provider_registry.server_ids(),
                    reconciler,
                    library_ids=library_ids,
                    config_dir=config_dir,
                    tmdb_count=len(tmdb_items),
                )
                await tmdb_seasons.run(tmdb_items, job)
            # Criteria test TMDB facts, whatever the run then syncs.
            await enrichment.run(job, library_ids=library_ids)
            if include_collections:
                await collections.run(job, servers, library_ids=library_ids)
            # Having read what the servers hold, make them match what Overture
            # manages: every group, or only the chosen groups and collections.
            if not provider_registry.collections_supported:
                return
            if include_collections or collection_groups:
                await _sync_groups(
                    job,
                    groups,
                    None if include_collections else collection_groups,
                    library_ids,
                )
            if collection_ids and not job.stop_requested():
                await _report(
                    job, "Collections", await groups.sync_collections(collection_ids)
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
    job: ManagedJob[JobTally],
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
        except Exception as exc:  # noqa: BLE001 -- one group's failure is reported; the rest go on
            await job.report(
                JobOutcome.ERROR, f"Group {name}", str(exc), finished=False
            )
            continue
        await _report(job, f"Group {name}", result)


async def _report(
    job: ManagedJob[JobTally], subject: str, result: CollectionGroupSyncResult
) -> None:
    """Log what syncing a group or chosen collections did, and each failure."""
    for title, error in result.errors.items():
        await job.report(JobOutcome.ERROR, title, error, finished=False)
    await job.report(
        JobOutcome.STARTED,
        subject,
        f"{result.synced} synced, {len(result.created)} created, "
        f"{len(result.withheld)} taken off the server",
        finished=False,
    )


async def _reachable(
    job: ManagedJob[JobTally],
    provider_registry: ProviderRegistry,
    library_ids: list[str] | None,
) -> list[Provider]:
    """The servers to sync, the lead first, reporting each one that is down.

    Raises:
        MediaServerError: When none of them can be reached.
    """
    wanted = (
        None
        if library_ids is None
        else {
            parts[0]
            for library_id in library_ids
            if (parts := library_parts(library_id))
        }
    )
    reachable: list[Provider] = []
    failure: MediaServerError | None = None
    for provider in provider_registry.providers():
        if wanted is not None and provider.server_id not in wanted:
            continue
        try:
            await provider_registry.require_reachable(provider.server_id)
        except MediaServerError as exc:
            failure = exc
            await job.report(
                JobOutcome.ERROR,
                provider.server.title,
                exc.message,
                finished=False,
                server=log_server(provider),
            )
            continue
        reachable.append(provider)
    if not reachable and failure is not None:
        raise failure
    return reachable


async def _sync_with_providers(
    job: ManagedJob[JobTally],
    providers: Sequence[Provider],
    server_order: Sequence[int],
    reconciler: LibraryReconciler,
    *,
    library_ids: list[str] | None,
    config_dir: Path,
    tmdb_count: int,
) -> None:
    """Stage every server's complete listing, then reconcile them lead first.

    The run counts the staged server items and planned TMDB shows, with its
    total fixed before the first item is reconciled.
    """

    moves: Counter[tuple[str, MediaType, str]] = Counter()
    with operation_directory(config_dir) as directory:
        listings: list[tuple[Provider, StagedListing]] = []
        async with AsyncExitStack() as staged:
            for provider in providers:
                await job.report(
                    JobOutcome.STARTED,
                    "Sync",
                    f"reading libraries from {provider.server.title}",
                    server=log_server(provider),
                    finished=False,
                )
                await reconciler.record_libraries(
                    provider.server_id, await provider.get_sections()
                )
                listing = await staged.enter_async_context(
                    StagedListing(directory / f"server-{provider.server_id}.sqlite")
                )
                async for batch in provider.iter_items(library_ids=library_ids):
                    if job.stop_requested():
                        return
                    await reconciler.fill_deferred_directors(provider, batch)
                    await listing.append(batch)
                listings.append((provider, listing))
            total = sum([await listing.count() for _, listing in listings])
            await job.planned(total + tmdb_count)
            for provider, listing in listings:
                position = server_order.index(provider.server_id)
                result = await reconciler.sync_staged(
                    listing,
                    ServerTurn(provider.server_id, frozenset(server_order[:position])),
                    library_ids=library_ids,
                    report=partial(job.report, server=log_server(provider)),
                    stop_check=job.stop_requested,
                )
                moves += result.library_moves
                if job.stop_requested():
                    # A stopped run saw only some of the moves.
                    return
    for library_id, successor in await reconciler.follow_moved_libraries(moves):
        await job.report(
            JobOutcome.STARTED,
            "Libraries",
            f"collections, sets and schedules of library {library_id} "
            f"now use {successor}, which holds its titles",
            finished=False,
        )
