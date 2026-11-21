"""Application-owned media-server reconciliation."""

lazy import logging
lazy from collections import Counter
lazy from collections.abc import (
    AsyncGenerator,
    Awaitable,
    Callable,
    Collection,
    Sequence,
)
lazy from contextlib import asynccontextmanager
lazy from dataclasses import dataclass, field
lazy from typing import Any

lazy from sqlmodel import col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.ledger import read_asset
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import PAGE_SIZE, Database
lazy from ...domain import AutoUnmonitor, MediaType, ServerAsset, media_sort_key
lazy from ...jobs.progress_log import JobOutcome, Report
lazy from ...media_servers.adapters import (
    ServerItem,
    ServerSection,
    SyncItemResult,
    SyncStopCheck,
)
lazy from ...media_servers.base import BaseMediaServerProvider
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.copies import CopyRepository
lazy from ...repositories.libraries import LibraryRepository
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.saved_schedules import SavedScheduleRepository
lazy from ...services.library.items import (
    emit_library_item_removed,
    emit_library_items_upserted,
)
lazy from ...utils.time import utc_now
lazy from ..downloads.selections import queue_saved_selection_downloads
lazy from ..downloads.service import DownloadService
lazy from ..local_assets.service import LocalAssets
lazy from ..needs import apply_needs
lazy from ..storage.assets import AssetStorage
lazy from .art_urls import resolve_provider_art_urls
lazy from .item_sync import CopyPlace, ItemReconciler
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
    return str(exc)


def _sync_outcome(result: SyncItemResult) -> tuple[JobOutcome, str]:
    """Say what the sync did with one server item, and why."""
    if result.created:
        return JobOutcome.ADDED, "new library item"
    if result.changes:
        return JobOutcome.UPDATED, f"changed: {', '.join(result.changes)}"
    return JobOutcome.UNCHANGED, "matches the media server and the local files"


@dataclass(slots=True, frozen=True)
class ServerTurn:
    """The server a sync reconciles, and the servers that lead before it."""

    server_id: int
    #: The configured servers before it in MEDIA_SERVERS, whose copies lead.
    earlier: frozenset[int] = frozenset()

    async def place(self, session: AsyncSession, item_id: int | None) -> CopyPlace:
        """Where this server holds a title; it leads unless an earlier one lists it."""
        if item_id is None or not self.earlier:
            return CopyPlace(self.server_id, lead=True)
        copies = await CopyRepository(session).of_item(item_id)
        return CopyPlace(
            self.server_id,
            lead=not any(
                copy.server_id in self.earlier and copy.removed_at is None
                for copy in copies
            ),
        )


@dataclass(slots=True, frozen=True)
class SyncResult:
    """The items reconciliation created and the libraries titles moved between."""

    created_item_ids: list[int] = field(default_factory=list[int])
    #: How many titles moved from one library to another, by
    #: ``(library, media type, new library)``.
    library_moves: Counter[tuple[str, MediaType, str]] = field(
        default_factory=Counter[tuple[str, MediaType, str]]
    )


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

    async def record_libraries(
        self, server_id: int, sections: Sequence[ServerSection]
    ) -> None:
        """Store the libraries a server lists, which its items are filed under."""
        async with self._database.write_session() as session:
            await LibraryRepository(session).record(server_id, sections, utc_now())

    async def follow_moved_libraries(
        self, moves: Counter[tuple[str, MediaType, str]]
    ) -> list[tuple[str, str]]:
        """Point what named a library no server lists any more at its successor.

        A library's successor is the listed library most of its titles moved
        to, on its own server or, after a server left MEDIA_SERVERS, on
        another. Returns each ``(library, successor)`` followed.
        """
        if not moves:
            return []
        followed: list[tuple[str, str]] = []
        async with self._database.write_session() as session:
            listed = {
                (library.id, library.media_type)
                for library in await LibraryRepository(session).listed()
            }
            successors: dict[tuple[str, MediaType], Counter[str]] = {}
            for (library_id, media_type, moved_to), count in moves.items():
                successors.setdefault((library_id, media_type), Counter())[
                    moved_to
                ] += count
            for (library_id, media_type), counts in successors.items():
                if (library_id, media_type) in listed:
                    continue
                [(successor, _)] = counts.most_common(1)
                if (successor, media_type) not in listed:
                    continue
                await CollectionRepository(session).move_library(
                    library_id, media_type, successor
                )
                await SavedScheduleRepository(session).move_library(
                    library_id, successor
                )
                followed.append((library_id, successor))
        return followed

    async def fill_deferred_directors(
        self, provider: BaseMediaServerProvider[Any], server_items: list[ServerItem]
    ) -> None:
        """Fill directors a listing omitted, asking the server only on change.

        A movie whose ``director_etag`` matches a stored row keeps that row's
        directors; the rest are fetched in one batch. A movie the server no
        longer returns loses its Etag, so the next sync asks again.
        """
        deferred = [item for item in server_items if item.director_etag is not None]
        if not deferred:
            return
        async with self._database.read_session() as session:
            stored = await CopyRepository(session).directors_by_version(
                provider.server_id, {item.id for item in deferred}
            )
        changed: list[ServerItem] = []
        for item in deferred:
            key = (item.id, item.director_etag or "")
            if key in stored:
                item.directors = stored[key]
            else:
                changed.append(item)
        if not changed:
            return
        directors = await provider.get_directors([item.id for item in changed])
        for item in changed:
            if item.id in directors:
                item.directors = directors[item.id]
            else:
                item.director_etag = None

    async def sync_staged(
        self,
        listing: StagedListing,
        turn: ServerTurn,
        *,
        library_ids: list[str] | None,
        report: Report,
        stop_check: SyncStopCheck | None,
    ) -> SyncResult:
        """Reconcile a complete disk snapshot in bounded item batches.

        The caller has already counted the listing into the run's total.
        """
        stats = SyncResult()
        after_rowid = 0
        while rows := await listing.batch(after_rowid):
            after_rowid = rows[-1][0]

            async def mapped(item: ServerItem, item_id: int) -> None:
                await listing.mark_mapped(item.media_type, item.id, item_id)

            if await self._reconcile_batch(
                [item for _, item in rows],
                turn,
                claimed=listing.is_mapped,
                on_reconciled=mapped,
                stats=stats,
                event_source="sync",
                report=report,
                stop_check=stop_check,
            ):
                return stats
        await self._mark_missing_staged(listing, turn.server_id, library_ids, report)
        return stats

    async def _reconcile_batch(
        self,
        server_items: list[ServerItem],
        turn: ServerTurn,
        *,
        claimed: Callable[[int], Awaitable[bool]],
        on_reconciled: Callable[[ServerItem, int], Awaitable[None]],
        stats: SyncResult,
        event_source: str,
        report: Report,
        stop_check: SyncStopCheck | None,
    ) -> bool:
        """Reconcile provider items in order, one transaction each.

        Returns:
            Whether the run was asked to stop before the batch was done.
        """
        auto_unmonitor = await self._auto_unmonitor()
        changed: list[int] = []
        reconciled: list[int] = []
        stopped = False
        async with self._stamping() as synced:
            for server_item in server_items:
                if stop_check and stop_check():
                    stopped = True
                    break
                outcome = await self._reconcile_one(
                    server_item,
                    turn,
                    claimed,
                    stats=stats,
                    auto_unmonitor=auto_unmonitor,
                )
                if isinstance(outcome, SyncItemResult) and outcome.item_id is not None:
                    synced.add(outcome.item_id)
                    reconciled.append(outcome.item_id)
                    await on_reconciled(server_item, outcome.item_id)
                    if outcome.visible_changed:
                        changed.append(outcome.item_id)
                await self._report(server_item, outcome, stats, report)
        await self._apply_needs(reconciled)
        # Told after the stamp, since an upsert versions server artwork by it.
        await emit_library_items_upserted(
            changed, event_source, self.publisher, database=self._database
        )
        return stopped

    async def _apply_needs(self, item_ids: Sequence[int]) -> None:
        """Record what is wanted for the batch's titles, as the catalog says."""
        if not item_ids:
            return
        async with self._database.write_session() as session:
            items = await MediaItemRepository(session).get_many(item_ids)
            await apply_needs(session, items=items, app_config=self._app_config)

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
        a re-sync writes once per batch instead of once per item.
        """
        if item_ids:
            async with self._database.write_session() as session:
                await MediaItemRepository(session).mark_synced(item_ids, utc_now())

    async def _match(
        self,
        server_item: ServerItem,
        server_id: int,
        claimed: Callable[[int], Awaitable[bool]],
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
                    session,
                    server_id,
                    server_item,
                    exclude_item_ids=excluded,
                    for_update=False,
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
        server_id: int,
        library_ids: list[str] | None,
        report: Report,
    ) -> None:
        """Mark the server's copies its complete listing left out as removed.

        A title is hidden once no server lists it any more.
        """
        after_id = 0
        while True:
            async with self._database.read_session() as session:
                current = await CopyRepository(session).identities(
                    server_id, library_ids, after_id=after_id, limit=PAGE_SIZE
                )
            if not current:
                return
            after_id = current[-1][0]
            listed = await listing.mappings(
                [
                    (media_type, server_item_id)
                    for _, _, media_type, server_item_id in current
                ]
            )
            missing = [
                copy_id
                for copy_id, item_id, media_type, server_item_id in current
                if (media_type, server_item_id) not in listed
                or listed[media_type, server_item_id] not in {None, item_id}
            ]
            async with self._database.write_session() as session:
                gone = await CopyRepository(session).mark_removed(missing, utc_now())
                removed = (
                    await session.exec(
                        select(MediaItem).where(col(MediaItem.id).in_(gone))
                    )
                ).all()
            for item in removed:
                await report(
                    JobOutcome.REMOVED,
                    item.title,
                    "no longer on the media server; hidden from the library",
                    # Not one of the listed items the run counts through.
                    finished=False,
                )
                if item.id is not None:
                    await emit_library_item_removed(
                        item.id, item.media_type, "sync", self.publisher
                    )
            if len(current) < PAGE_SIZE:
                return

    async def sync_recent(
        self,
        server_items: list[ServerItem],
        turn: ServerTurn,
        *,
        report: Report,
        stop_check: SyncStopCheck | None = None,
    ) -> SyncResult:
        """Reconcile a partial provider snapshot without removing missing items.

        Movies come before shows, each by title, as a full sync lists them.
        """
        stats = SyncResult()
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
            turn,
            claimed=claimed,
            on_reconciled=mark,
            stats=stats,
            event_source="incremental_sync",
            report=report,
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
        turn: ServerTurn,
        claimed: Callable[[int], Awaitable[bool]],
        *,
        stats: SyncResult,
        auto_unmonitor: AutoUnmonitor,
    ) -> SyncItemResult | str:
        """Find the row one provider item matches, then reconcile it."""
        try:
            excluded, expected = await self._match(server_item, turn.server_id, claimed)
        except Exception as exc:  # noqa: BLE001 -- one item's failure is reported; the rest go on
            return _item_failure(server_item, exc)
        outcome = await self._reconcile_matched(
            server_item, turn, excluded, expected, auto_unmonitor=auto_unmonitor
        )
        if isinstance(outcome, SyncItemResult):
            for left in outcome.left_libraries:
                stats.library_moves[
                    left, server_item.media_type, server_item.library_id
                ] += 1
        return outcome

    async def _reconcile_matched(
        self,
        server_item: ServerItem,
        turn: ServerTurn,
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
            lock_key = expected_id or (
                f"sync:{turn.server_id}:{server_item.media_type}:{server_item.id}"
            )
            async with self.asset_storage.asset_locks.acquire(lock_key):
                async with self._database.write_session() as session:
                    current = await self._items.find_existing_item(
                        session, turn.server_id, server_item, exclude_item_ids=excluded
                    )
                    if (current.id if current is not None else None) != expected_id:
                        raise RuntimeError("Media item changed during reconciliation")
                    # The choice saved before this sync, not one the local
                    # refresh below adopts from the file it finds.
                    saved_theme = (
                        read_asset(current, ServerAsset.THEME).youtube_id
                        if current is not None
                        else None
                    )
                    result = await self._items.sync_item(
                        session,
                        await turn.place(session, expected_id),
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
                        # Refreshed directly under the active item lock.
                        changed = await self.local_assets.refresh_row(current)
                    if changed:
                        result.visible_changed = True
                        if not result.created:
                            result.changes = (*result.changes, "local files")
                # A title with a newly discovered folder downloads its saved selections.
                if (
                    expected_id is not None
                    and expected is not None
                    and expected.folder_path is None
                    and server_item.folder_path
                    and await queue_saved_selection_downloads(
                        expected_id,
                        youtube_id=saved_theme,
                        downloads=self._downloads,
                        database=self._database,
                    )
                ):
                    result.changes = (*result.changes, "saved selections downloading")
            return result
        except Exception as exc:  # noqa: BLE001 -- one item's failure is reported; the rest go on
            return _item_failure(server_item, exc)

    @staticmethod
    async def _report(
        server_item: ServerItem,
        outcome: SyncItemResult | str,
        stats: SyncResult,
        report: Report,
    ) -> None:
        """Record the outcome and report its line."""
        if isinstance(outcome, str):
            status, reason = JobOutcome.ERROR, outcome
        else:
            if outcome.created and outcome.item_id is not None:
                stats.created_item_ids.append(outcome.item_id)
            status, reason = _sync_outcome(outcome)
        await report(status, server_item.title, reason)
