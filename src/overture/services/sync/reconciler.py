"""Application-owned media-server reconciliation."""

lazy import logging
lazy from collections.abc import AsyncGenerator, Awaitable, Callable, Collection
lazy from contextlib import asynccontextmanager
lazy from dataclasses import dataclass, field
lazy from typing import Any

lazy from sqlmodel import col, select

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import PAGE_SIZE, Database
lazy from ...domain import AutoUnmonitor, media_sort_key
lazy from ...jobs.progress_log import JobOutcome, log_entry
lazy from ...jobs.tally import SyncTally
lazy from ...media_servers.adapters import (
    ServerItem,
    SyncItemResult,
    SyncProgressCallback,
    SyncStopCheck,
)
lazy from ...media_servers.base import BaseMediaServerProvider
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...services.library.items import (
    emit_library_item_removed,
    emit_library_item_upserted,
)
lazy from ...utils.errors import public_error_message
lazy from ...utils.time import utc_now
lazy from ..downloads.selections import queue_saved_selection_downloads
lazy from ..downloads.service import DownloadService
lazy from ..local_assets.service import LocalAssets
lazy from ..storage.assets import AssetStorage
lazy from .art_urls import resolve_provider_art_urls
lazy from .item_sync import ItemReconciler
lazy from .season_sync import SeasonSynchronizer
lazy from .staging import StagedListing

logger = logging.getLogger(__name__)


def _item_failure(server_item: ServerItem, exc: Exception) -> str:
    """Return the reason the run reports for one item's failure.

    The run's Error entry logs that reason; the traceback is debug detail.
    """
    logger.debug(
        "Reconciling %s (%s) failed", server_item.title, server_item.id, exc_info=exc
    )
    return public_error_message(exc)


def _sync_outcome(result: SyncItemResult) -> tuple[JobOutcome, str]:
    """Say what the sync did with one server item, and why."""
    if result.created:
        return JobOutcome.ADDED, "new library item"
    if result.changes:
        return JobOutcome.UPDATED, f"changed: {', '.join(result.changes)}"
    return JobOutcome.UNCHANGED, "matches the media server and the local files"


@dataclass(slots=True, frozen=True)
class SyncResult:
    """One shared tally and the items reconciliation created."""

    tally: SyncTally = field(default_factory=SyncTally)
    created_item_ids: list[int] = field(default_factory=list[int])


class LibraryReconciler:
    """Reconcile normalized provider DTOs into Overture application state."""

    def __init__(
        self,
        *,
        publisher: protocols.EventPublisher,
        local_assets: LocalAssets,
        downloads: DownloadService,
        app_config: Settings,
        database: Database,
    ) -> None:
        self._app_config = app_config
        self._database = database
        self.publisher = publisher
        self.local_assets = local_assets
        self._downloads = downloads
        self._items = ItemReconciler(SeasonSynchronizer())

    @property
    def asset_storage(self) -> AssetStorage:
        """Return the storage whose locks guard each item's files."""
        return self.local_assets.asset_storage

    async def fill_deferred_directors(
        self, provider: BaseMediaServerProvider[Any], server_items: list[ServerItem]
    ) -> None:
        """Fill directors a listing omitted, asking the server only on change.

        A movie whose ``director_etag`` matches a stored row keeps that row's
        director; the rest are fetched in one batch. A movie the server no
        longer returns loses its Etag, so the next sync asks again.
        """
        deferred = [item for item in server_items if item.director_etag is not None]
        if not deferred:
            return
        async with self._database.read_session() as session:
            stored = await MediaItemRepository(session).directors_by_version(
                {item.id for item in deferred}
            )
        changed: list[ServerItem] = []
        for item in deferred:
            key = (item.id, item.director_etag or "")
            if key in stored:
                item.director = stored[key]
            else:
                changed.append(item)
        if not changed:
            return
        directors = await provider.get_directors([item.id for item in changed])
        for item in changed:
            if item.id in directors:
                item.director = directors[item.id]
            else:
                item.director_etag = None

    async def sync_staged(
        self,
        listing: StagedListing,
        *,
        library_ids: list[str] | None,
        tally: SyncTally,
        progress_cb: SyncProgressCallback | None,
        stop_check: SyncStopCheck | None,
    ) -> SyncResult:
        """Reconcile a complete disk snapshot in bounded item batches.

        The caller has already counted the listing into the tally's total.
        """
        stats = SyncResult(tally)
        after_rowid = 0
        while rows := await listing.batch(after_rowid):
            after_rowid = rows[-1][0]

            async def mapped(item: ServerItem, item_id: int) -> None:
                await listing.mark_mapped(item.media_type, item.id, item_id)

            if await self._reconcile_batch(
                [item for _, item in rows],
                claimed=listing.is_mapped,
                on_reconciled=mapped,
                stats=stats,
                event_source="sync",
                progress_cb=progress_cb,
                stop_check=stop_check,
            ):
                return stats
        await self._mark_missing_staged(listing, library_ids, stats, progress_cb)
        return stats

    async def _reconcile_batch(
        self,
        server_items: list[ServerItem],
        *,
        claimed: Callable[[int], Awaitable[bool]],
        on_reconciled: Callable[[ServerItem, int], Awaitable[None]],
        stats: SyncResult,
        event_source: str,
        progress_cb: SyncProgressCallback | None,
        stop_check: SyncStopCheck | None,
    ) -> bool:
        """Reconcile provider items in order, one transaction each.

        Returns:
            Whether the run was asked to stop before the batch was done.
        """
        auto_unmonitor = await self._auto_unmonitor()
        async with self._stamping() as synced:
            for server_item in server_items:
                if stop_check and stop_check():
                    return True
                outcome = await self._reconcile_one(
                    server_item, claimed, auto_unmonitor=auto_unmonitor
                )
                if isinstance(outcome, SyncItemResult) and outcome.item_id is not None:
                    synced.add(outcome.item_id)
                    await on_reconciled(server_item, outcome.item_id)
                await self._report(
                    server_item,
                    outcome,
                    stats,
                    event_source=event_source,
                    progress_cb=progress_cb,
                )
        return False

    @asynccontextmanager
    async def _stamping(self) -> AsyncGenerator[set[int]]:
        """Collect reconciled item IDs and stamp them as synced on the way out.

        A run that fails still stamps what it reconciled, but a stamp that
        fails then is only logged, so it never replaces the run's own error.
        """
        item_ids: set[int] = set()
        try:
            yield item_ids
        except BaseException:
            try:
                await self._mark_synced(item_ids)
            except Exception:
                logger.exception("Failed to stamp reconciled items as synced")
            raise
        await self._mark_synced(item_ids)

    async def _mark_synced(self, item_ids: Collection[int]) -> None:
        """Stamp reconciled items as synced in one write.

        Doing it per batch keeps an unchanged item's own transaction empty, so
        a re-sync writes once per batch instead of once per item. A changed
        item is stamped again here, harmlessly, after its own stamp.
        """
        if item_ids:
            async with self._database.write_session() as session:
                await MediaItemRepository(session).mark_synced(item_ids, utc_now())

    async def _match(
        self, server_item: ServerItem, claimed: Callable[[int], Awaitable[bool]]
    ) -> tuple[set[int], MediaItem | None]:
        """Return the claimed rows the item matched and the row it reconciles into.

        Only matching rows this run already *claimed* are excluded, so each
        lookup excludes a handful of rows rather than every row reconciled so
        far; the first unclaimed match is the same row either way.
        """
        excluded: set[int] = set()
        for _ in range(500):
            async with self._database.read_session() as session:
                candidate = await self._items.find_existing_item(
                    session, server_item, exclude_item_ids=excluded, load_art=False
                )
            if candidate is None or candidate.id is None:
                return excluded, None
            if not await claimed(candidate.id):
                return excluded, candidate
            excluded.add(candidate.id)
        raise RuntimeError("Provider returned too many items matching one local asset")

    async def _mark_missing_staged(
        self,
        listing: StagedListing,
        library_ids: list[str] | None,
        stats: SyncResult,
        progress_cb: SyncProgressCallback | None,
    ) -> None:
        """Hide missing rows only after the provider snapshot is complete."""
        after_id = 0
        while True:
            async with self._database.read_session() as session:
                candidates = await MediaItemRepository(
                    session
                ).list_visible_with_server_ids(
                    library_ids, after_id=after_id, limit=PAGE_SIZE
                )
                current = [
                    (item.id, item.media_type, item.server_item_id)
                    for item in candidates
                    if item.id is not None and item.server_item_id is not None
                ]
            if not candidates:
                return
            after_id = max(item.id or 0 for item in candidates)
            listed = await listing.mappings(
                [(media_type, server_id) for _, media_type, server_id in current]
            )
            missing = {
                item_id: (media_type, server_id)
                for item_id, media_type, server_id in current
                if (media_type, server_id) not in listed
                or listed[media_type, server_id] not in {None, item_id}
            }
            removed: list[MediaItem] = []
            async with self._database.write_session() as session:
                rows = await session.exec(
                    select(MediaItem).where(col(MediaItem.id).in_(missing))
                )
                for item in rows.all():
                    media_type, server_id = missing[item.id or 0]
                    if (
                        item.server_removed_at is not None
                        or item.media_type != media_type
                        or item.server_item_id != server_id
                        or (
                            library_ids is not None
                            and item.library_id not in library_ids
                        )
                    ):
                        continue
                    item.server_removed_at = utc_now()
                    item.last_synced_at = item.server_removed_at
                    session.add(item)
                    removed.append(item)
            for item in removed:
                await self._log_removed(stats, item.title, progress_cb)
                if item.id is not None:
                    await emit_library_item_removed(
                        item.id, item.media_type, "sync", self.publisher
                    )
            if len(candidates) < PAGE_SIZE:
                return

    async def sync_recent(
        self,
        server_items: list[ServerItem],
        *,
        tally: SyncTally | None = None,
        progress_cb: SyncProgressCallback | None = None,
        stop_check: SyncStopCheck | None = None,
    ) -> SyncResult:
        """Reconcile a partial provider snapshot without removing missing items.

        Movies come before shows, each by title, as a full sync lists them.
        """
        stats = SyncResult(tally if tally is not None else SyncTally())
        reconciled: set[int] = set()

        async def claimed(item_id: int) -> bool:
            return item_id in reconciled

        async def mark(_item: ServerItem, item_id: int) -> None:
            reconciled.add(item_id)

        await self._reconcile_batch(
            sorted(
                server_items,
                key=lambda item: media_sort_key(item.media_type, item.title, item.id),
            ),
            claimed=claimed,
            on_reconciled=mark,
            stats=stats,
            event_source="incremental_sync",
            progress_cb=progress_cb,
            stop_check=stop_check,
        )
        return stats

    async def _auto_unmonitor(self) -> AutoUnmonitor:
        """Read the completion policy once for the items about to be synced."""
        async with self._database.read_session() as session:
            return (await get_app_settings(session)).auto_unmonitor

    async def _reconcile_one(
        self,
        server_item: ServerItem,
        claimed: Callable[[int], Awaitable[bool]],
        *,
        auto_unmonitor: AutoUnmonitor,
    ) -> SyncItemResult | str:
        """Find the row one provider item matches, then reconcile it."""
        try:
            excluded, expected = await self._match(server_item, claimed)
        except Exception as exc:
            return _item_failure(server_item, exc)
        return await self._reconcile_matched(
            server_item, excluded, expected, auto_unmonitor=auto_unmonitor
        )

    async def _reconcile_matched(
        self,
        server_item: ServerItem,
        excluded: set[int],
        expected: MediaItem | None,
        *,
        auto_unmonitor: AutoUnmonitor,
    ) -> SyncItemResult | str:
        """Reconcile one provider item, matched to *expected*, on its own.

        One item is the unit of work, so it is also the unit of transaction:
        an item that fails rolls back only itself, and the write lock is held
        for the rows it touches rather than for its neighbours as well. The
        match is checked again under the lock before anything is written.

        *excluded* holds the claimed rows the match skipped; *expected* identifies
        the row only, and its artwork is read under the lock.
        *auto_unmonitor* is the completion policy the caller read for its batch.
        """
        try:
            resolved = await resolve_provider_art_urls(
                server_item, app_config=self._app_config
            )
            expected_id = expected.id if expected is not None else None
            lock_key = expected_id or f"sync:{server_item.media_type}:{server_item.id}"
            async with self.asset_storage.asset_locks.acquire(lock_key):
                async with self._database.write_session() as session:
                    current = await self._items.find_existing_item(
                        session, server_item, exclude_item_ids=excluded
                    )
                    if (current.id if current is not None else None) != expected_id:
                        raise RuntimeError("Media item changed during reconciliation")
                    result = await self._items.sync_item(
                        session,
                        server_item,
                        resolved,
                        current,
                        auto_unmonitor=auto_unmonitor,
                    )
                if result.item_id is not None and (
                    server_item.folder_path
                    or (expected is not None and expected.folder_path)
                ):
                    if current is None:
                        async with self.asset_storage.asset_locks.acquire(
                            result.item_id
                        ):
                            changed = await self.local_assets.refresh(result.item_id)
                    else:
                        # The row was just written under this item's lock.
                        changed = await self.local_assets.refresh_row(current)
                    if changed:
                        result.visible_changed = True
                        if not result.created:
                            result.changes = (*result.changes, "local files")
                # An item chosen from TMDB that now has a folder downloads
                # what was chosen for it.
                if (
                    expected_id is not None
                    and expected is not None
                    and expected.folder_path is None
                    and server_item.folder_path
                    and await queue_saved_selection_downloads(
                        expected_id,
                        youtube_id=expected.youtube_id,
                        downloads=self._downloads,
                        database=self._database,
                    )
                ):
                    result.changes = (*result.changes, "saved selections downloading")
            # The upsert a change emits versions server artwork by the sync
            # time, so a changed item is stamped before it is reported.
            if (
                result.visible_changed
                and not result.created
                and result.item_id is not None
            ):
                await self._mark_synced([result.item_id])
            return result
        except Exception as exc:
            return _item_failure(server_item, exc)

    async def _log_removed(
        self,
        stats: SyncResult,
        title: str,
        progress_cb: SyncProgressCallback | None,
    ) -> None:
        """Report a library item the media server no longer lists.

        It is not one of the server items the run counts through, so it does
        not advance ``done``.
        """
        await self._log(
            stats,
            JobOutcome.REMOVED,
            title,
            "no longer on the media server; hidden from the library",
            progress_cb,
            finished=False,
        )

    @staticmethod
    async def _log(
        stats: SyncResult,
        outcome: JobOutcome,
        target: str,
        reason: str,
        progress_cb: SyncProgressCallback | None,
        *,
        finished: bool = True,
    ) -> None:
        """Count one item's outcome and send its line to the run's log."""
        stats.tally.count(outcome)
        if finished:
            stats.tally.done += 1
        if progress_cb:
            await progress_cb(log_entry(outcome, target, reason))

    async def _report(
        self,
        server_item: ServerItem,
        outcome: SyncItemResult | str,
        stats: SyncResult,
        *,
        event_source: str,
        progress_cb: SyncProgressCallback | None,
    ) -> None:
        """Record outcome, append log message, and notify subscribers."""
        changed_item_id: int | None = None
        if isinstance(outcome, str):
            status, reason = JobOutcome.ERROR, outcome
        else:
            if outcome.created and outcome.item_id is not None:
                stats.created_item_ids.append(outcome.item_id)
            status, reason = _sync_outcome(outcome)
            changed_item_id = outcome.item_id if outcome.visible_changed else None
        await self._log(stats, status, server_item.title, reason, progress_cb)
        if changed_item_id is not None:
            await emit_library_item_upserted(
                changed_item_id,
                event_source,
                self.publisher,
                database=self._database,
            )
