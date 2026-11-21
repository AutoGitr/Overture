"""The rules and effects every Assets run shares: planning, queueing, reporting.

A run plans every target before the first decision: each is decided from
the database alone, by :func:`planned_outcome`, or kept as a visit.
:func:`refresh_scope` first brings the recorded files of saved selections up
to date, so planning keeps only those still on disk.
"""

lazy import asyncio
lazy import logging
lazy from collections.abc import AsyncGenerator, Awaitable, Callable
lazy from contextlib import asynccontextmanager
lazy from datetime import datetime, timedelta
lazy from typing import Protocol

lazy from sqlalchemy.exc import SQLAlchemyError
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.ledger import (
    Selection,
    delivery,
    file_facts,
    read_asset,
    record_file,
    selection,
)
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.session import CHUNK_SIZE, Database
lazy from ...domain import (
    PERFECT_MATCH_ONLY,
    RecentUnit,
    ServerAsset,
)
lazy from ...jobs.progress_log import JobOutcome
lazy from ...jobs.runner import ManagedJob
lazy from ...jobs.tally import BulkAssetTally
lazy from ...media_servers.adapters import FolderThemes
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.art import ArtMatchResponse
lazy from ...schemas.bulk import BulkMatchArtRequest, BulkThemeRequest
lazy from ...utils.text import count_label
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..catalog.index import CatalogPick
lazy from ..collections.theme_files import inspect_theme_file
lazy from ..downloads.collection_theme import theme_folders
lazy from ..downloads.queue import JobTarget
lazy from ..downloads.service import DownloadService
lazy from ..downloads.watch import DownloadWatch
lazy from ..local_assets.service import LocalAssets
lazy from ..themes.youtube_resolver import DownloadError

logger = logging.getLogger(__name__)

#: Targets whose sources are asked at once. Asking mostly waits on image
#: downloads or a yt-dlp search, so a few overlap without flooding providers.
DECIDE_CONCURRENCY = 4

#: Why targets whose saved selection is on disk were not visited.
SAVED_SELECTION = "saved selection already set; Replace existing searches again"

#: Why planned targets could not be visited: their row left the library.
LEFT_LIBRARY = "no longer in the library"
#: Why matching artwork was not saved: its link is private or carries credentials.
NOT_PUBLIC_ART_URL = (
    "the matching artwork's link is not a public link Overture can save"
)

#: Why artwork candidates were not compared.
REJECTED_CANDIDATES = "rejected on size or aspect ratio"


def no_match_reason(match_result: ArtMatchResponse, threshold: int) -> str:
    """Say why local art matching found nothing for one slot."""
    if reason := match_result.reason:
        return reason
    rejected = match_result.prefiltered
    if not match_result.total_compared:
        if rejected == 1:
            return f"1 candidate {REJECTED_CANDIDATES}"
        return (
            f"all {rejected} candidates {REJECTED_CANDIDATES}"
            if rejected
            else "no candidates returned by enabled artwork providers"
        )
    within = (
        "no perfect match"
        if threshold == PERFECT_MATCH_ONLY
        else f"nothing within distance {threshold}"
    )
    return f"{within}, {rejected} {REJECTED_CANDIDATES}" if rejected else within


#: What one target came to without being visited: its outcome and the reason.
type PlannedOutcome = tuple[JobOutcome, str]


class AssetRunParams(Protocol):
    """The options of a bulk request that decide targets while planning."""

    overwrite_existing: bool
    library_ids: list[str]
    item_ids: list[int] | None
    include_unmonitored: bool
    skip_recent_val: int
    skip_recent_unit: RecentUnit


def planned_outcome(
    params: AssetRunParams,
    *,
    saved: Selection | None,
    selection_missing: bool,
    last_checked: datetime | None,
    catalog: CatalogPick | None,
) -> PlannedOutcome | None:
    """Decide one target from the database, or return ``None`` to visit it.

    This is the planning half of an Assets decision; a visit makes the half
    that needs the files on disk or a source. *saved* is the slot's saved
    selection, and *selection_missing* says the file on disk is not it: the
    file is missing, or was replaced outside Overture. *catalog* is ``None``
    unless the run's sole sources are catalogs, and then is what they offer
    the target.
    The rules apply in order:

    1. A saved selection missing from disk is visited, whenever last
       checked, since the visit downloads the saved choice rather than asking
       a source.
    2. On a catalog-only run, a target no catalog serves is no match, or
       skipped when OvertureDB is disabled: no option would find it anything.
    3. A saved selection on disk that already is the catalog's offer is
       skipped, Overwrite or not: replacing it would fetch the same art.
    4. A saved selection is skipped unless Overwrite is on.
    5. A target checked within the Skip recently checked window is skipped.
    6. Everything else is visited.
    """
    kept = bool(saved) and not params.overwrite_existing
    if kept and selection_missing:
        return None
    if catalog is not None and catalog.value is None:
        outcome = JobOutcome.NO_MATCH if catalog.enabled else JobOutcome.SKIPPED
        return outcome, catalog.reason
    saved_url = saved and (saved.url or saved.youtube_id)
    if catalog is not None and not selection_missing and saved_url == catalog.value:
        return JobOutcome.SKIPPED, f"saved selection is already the {catalog.label}"
    if kept:
        return JobOutcome.SKIPPED, _saved_reason(catalog)
    if checked_recently(last_checked, params):
        return (
            JobOutcome.SKIPPED,
            f"checked within the last {recent_window_label(params)}",
        )
    return None


def _saved_reason(catalog: CatalogPick | None) -> str:
    """Say why a saved selection that is not the catalog's offer is kept."""
    if catalog is None:
        return SAVED_SELECTION
    return (
        f"saved selection differs from the {catalog.label}; "
        "Replace existing would replace it"
    )


async def refresh_folder_themes(
    row: MediaCollection,
    *,
    downloads: DownloadService,
    database: Database,
) -> MediaCollection:
    """Record the theme file each Jellyfin server's folder holds for *row*."""
    changed = False
    async with downloads.asset_locks.acquire(f"collection:{row.id}"):
        async with database.read_session() as session:
            current = await CollectionRepository(session).get(row.id or 0)
        if current is None:
            raise ValueError("Collection no longer exists")
        folders = await theme_folders(current, downloads.provider_registry)
        if not folders:
            return current
        theme = read_asset(current, ServerAsset.THEME)
        found = [
            (
                destination,
                await owned_thread(
                    inspect_theme_file,
                    folder,
                    file_facts(delivery(theme, destination)),
                ),
            )
            for destination, _, _, folder in folders
        ]
        if all(
            file_facts(delivery(theme, destination)) == facts
            for destination, facts in found
        ):
            return current
        async with database.write_session() as session:
            current = await CollectionRepository(session).get(row.id or 0)
            if current is None:
                raise ValueError("Collection no longer exists")
            now = utc_now()
            latest_theme = read_asset(current, ServerAsset.THEME)
            for destination, facts in found:
                if file_facts(delivery(latest_theme, destination)) != facts:
                    record_file(
                        current,
                        ServerAsset.THEME,
                        facts,
                        destination=destination,
                        at=now,
                    )
                    changed = True
            if changed:
                session.add(current)
    if changed:
        await downloads.publisher.broadcast(
            "collection.updated", {"collection_id": current.id}
        )
    return current


async def _refresh_collection_theme_folders(
    params: BulkThemeRequest,
    *,
    downloads: DownloadService,
    database: Database,
) -> None:
    """Refresh recorded Jellyfin theme files for collections in scope."""
    registry = downloads.provider_registry
    if not any(
        isinstance(provider.collections, FolderThemes)
        and provider.server.collections_path is not None
        for provider in registry.collection_providers()
    ):
        return
    after = 0
    while True:
        async with database.read_session() as session:
            rows = await CollectionRepository(session).bulk_targets(
                after=after,
                collection_ids=params.collection_ids,
                collection_groups=params.collection_groups,
                include_unmonitored=params.include_unmonitored,
            )
        if not rows:
            return
        for row in rows:
            if (
                not params.overwrite_existing
                or selection(read_asset(row, ServerAsset.THEME)) is not None
            ):
                try:
                    await refresh_folder_themes(
                        row, downloads=downloads, database=database
                    )
                except (DownloadError, OSError, ValueError) as exc:
                    logger.debug(
                        "Skipping pre-plan folder refresh for collection %s: %s",
                        row.id,
                        exc,
                    )
        after = rows[-1].id or after


async def refresh_scope(
    params: BulkMatchArtRequest | BulkThemeRequest,
    *,
    local_assets: LocalAssets,
    downloads: DownloadService,
    art: bool,
    source: str,
    database: Database,
) -> None:
    """Record the files of saved selections as they are, before planning.

    Planning keeps a saved selection on the strength of its recorded file, so
    a file deleted or replaced since the last refresh has to be seen first.
    Only titles and collection theme folders keeping one are refreshed, and an
    unchanged file costs one stat without being read. Every other target is
    visited, or decided without its files, and a visit refreshes the files it
    decides on.
    """
    if params.overwrite_existing:
        return
    if not art and params.collection_scope and isinstance(params, BulkThemeRequest):
        await _refresh_collection_theme_folders(
            params, downloads=downloads, database=database
        )
    if params.collection_scope and not params.library_ids:
        return
    after_id = 0
    while True:
        async with database.read_session() as session:
            item_ids = await MediaItemRepository(session).bulk_target_ids_keeping_files(
                params.library_ids,
                art=art,
                item_ids=params.item_ids,
                include_unmonitored=params.include_unmonitored,
                after_id=after_id,
                limit=CHUNK_SIZE,
            )
        if item_ids:
            await local_assets.reconcile(
                item_ids=item_ids, art=art, themes=not art, source=source
            )
        if len(item_ids) < CHUNK_SIZE:
            return
        after_id = item_ids[-1]


async def queue_and_report[TallyT: BulkAssetTally](
    job: ManagedJob[TallyT],
    target: str,
    reason: str,
    queue: Callable[[], Awaitable[bool]],
) -> bool:
    """Queue one download and log what happened to it.

    Returns:
        Whether the target ended with a download queued, by this run or an
        identical earlier request.
    """
    try:
        created = await queue()
    except SelectionChangedError:
        await job.report(
            JobOutcome.SKIPPED,
            target,
            f"{reason}; not queued: the selection changed during the run",
        )
        return False
    except (SQLAlchemyError, OSError, ValueError) as exc:
        await job.report(
            JobOutcome.ERROR,
            target,
            f"could not queue the download ({reason}): {exc!s}",
        )
        return False
    if created:
        await job.report(JobOutcome.QUEUED, target, reason)
    else:
        await job.report(
            JobOutcome.SKIPPED,
            target,
            f"{reason}; an identical download is already queued or running",
        )
    return True


def recent_window_label(params: AssetRunParams) -> str:
    """Name the skip-recent window the way the user set it."""
    return count_label(
        params.skip_recent_val, params.skip_recent_unit.value.removesuffix("s")
    )


def checked_recently(last_checked: datetime | None, params: AssetRunParams) -> bool:
    """Return whether *last_checked* falls inside the skip-recent window."""
    if params.skip_recent_val <= 0 or last_checked is None:
        return False
    window = timedelta(seconds=params.skip_recent_val * params.skip_recent_unit.seconds)
    return utc_now() - last_checked < window


class SelectionChangedError(Exception):
    """The slot no longer holds the selection a run planned its download with."""


async def _holds_selection(
    session: AsyncSession, target: JobTarget, planned: Selection | None
) -> bool:
    """Return whether *target*'s asset still holds the *planned* selection."""
    kind = target.art_type.server_asset if target.art_type else ServerAsset.THEME
    if target.collection_id is not None:
        collection = await session.get(MediaCollection, target.collection_id)
        if collection is None or collection.last_synced_at is None:
            return False
        return selection(read_asset(collection, kind)) == planned
    item = await session.get(MediaItem, target.media_item_id)
    if item is None:
        return False
    owner = (
        item
        if target.art_type is None
        else await SeasonRepository(session).art_owner(
            item, target.art_type, target.season_id
        )
    )
    return owner is not None and selection(read_asset(owner, kind)) == planned


async def queue_download(
    target: JobTarget,
    *,
    planned: Selection | None,
    downloads: DownloadService,
    on_queued: Callable[[str], None],
    database: Database,
) -> bool:
    """Queue one download in a transaction of its own; return whether it is new.

    *planned* is the asset's selection when the run decided on *target*.

    Raises:
        SelectionChangedError: When the slot's selection changed since, or its item
            left the library: a newer choice is not superseded by the run's.
    """
    async with (
        downloads.asset_locks.acquire(target.slot.lock_key),
        database.write_session() as session,
    ):
        if not await _holds_selection(session, target, planned):
            raise SelectionChangedError
        job_id, created = await downloads.queue_job(session, target)
    if created:
        on_queued(job_id)
    await downloads.committed(session)
    return created


@asynccontextmanager
async def report_downloads[TallyT: BulkAssetTally](
    job: ManagedJob[TallyT],
    watch: DownloadWatch,
    *,
    downloads: DownloadService,
) -> AsyncGenerator[None]:
    """Report downloads concurrently while the caller queues more work.

    Closing the context says matching is over. The reporter then stays alive
    until the last queued download settles, so completion means every file
    is on disk, identical already, or reported as failed.
    """

    async def publish() -> None:
        async for outcome in watch.stream():
            job.tally.settled += 1
            if outcome.cancelled:
                await job.report(
                    JobOutcome.SKIPPED,
                    outcome.target,
                    "download cancelled before it finished",
                    finished=False,
                )
            elif outcome.error:
                await job.report(
                    JobOutcome.ERROR,
                    outcome.target,
                    f"download failed: {outcome.error}",
                    finished=False,
                )
            elif outcome.unchanged:
                await job.report(
                    JobOutcome.DOWNLOADED,
                    outcome.target,
                    "download is identical to the local file; kept on disk",
                    finished=False,
                )
            else:
                await job.report(
                    JobOutcome.DOWNLOADED,
                    outcome.target,
                    outcome.destination,
                    finished=False,
                )
            if job.stop_requested():
                return

    async def monitor_stop() -> None:
        await job.context.stop_event.wait()
        await downloads.cancel_watch(watch)

    reporter = asyncio.create_task(publish())
    stopper = asyncio.create_task(monitor_stop())
    try:
        try:
            yield
        finally:
            watch.close()
            if job.stop_requested():
                job.context.stop_event.set()
            done, _ = await asyncio.wait(
                (reporter, stopper), return_when=asyncio.FIRST_COMPLETED
            )
            if stopper in done or job.stop_requested():
                job.context.stop_event.set()
                await stopper
                # A match already in flight may queue a job after the first
                # cancellation. Matching is over, so this is the final set.
                await downloads.cancel_watch(watch)
            await reporter
    finally:
        reporter.cancel()
        stopper.cancel()
        await asyncio.gather(reporter, stopper, return_exceptions=True)


class CheckedStamper:
    """Buffers ``last_matched_at`` stamps and writes them a batch at a time.

    Owners accumulate here and leave as one statement per table, rather than
    opening a write transaction per target.
    """

    def __init__(self, *, database: Database) -> None:
        """Start empty, flushing once a batch of targets is buffered."""
        self._database = database
        self._flush_lock = asyncio.Lock()
        self._item_ids: set[int] = set()
        self._season_ids: set[int] = set()
        self._collection_ids: set[int] = set()

    async def add(
        self,
        *,
        item_id: int | None = None,
        season_id: int | None = None,
        collection_id: int | None = None,
    ) -> None:
        """Buffer one checked owner, flushing when the batch is full."""
        for ids, value in (
            (self._item_ids, item_id),
            (self._season_ids, season_id),
            (self._collection_ids, collection_id),
        ):
            if value is not None:
                ids.add(value)
        buffered = (
            len(self._item_ids) + len(self._season_ids) + len(self._collection_ids)
        )
        if buffered >= CHUNK_SIZE:
            await self.flush()

    async def flush(self) -> None:
        """Write every buffered stamp and start the next batch."""
        async with self._flush_lock:
            if not (self._item_ids or self._season_ids or self._collection_ids):
                return
            item_ids, self._item_ids = self._item_ids, set()
            season_ids, self._season_ids = self._season_ids, set()
            collection_ids, self._collection_ids = self._collection_ids, set()
            now = utc_now()
            try:
                async with self._database.write_session() as session:
                    await MediaItemRepository(session).mark_matched(item_ids, now)
                    await SeasonRepository(session).mark_matched(season_ids, now)
                    await CollectionRepository(session).mark_matched(
                        collection_ids, now
                    )
            except BaseException:
                self._item_ids.update(item_ids)
                self._season_ids.update(season_ids)
                self._collection_ids.update(collection_ids)
                raise
