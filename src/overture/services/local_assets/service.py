"""The one way Overture learns what is on disk for a library item.

Sync, asset scans, renames, audits, matching and Assets runs all refresh an
item's recorded file facts through :class:`LocalAssets` before they rely on
them, so every decision is made against the database's view of the disk and
that view is updated whenever the disk is read.
"""

lazy from collections import defaultdict
lazy from collections.abc import Collection, Mapping
lazy from contextlib import aclosing
lazy from pathlib import Path

lazy from ... import protocols
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import PAGE_SIZE, Database
lazy from ...domain import MediaType
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...utils.concurrency import in_order
lazy from ...utils.path import is_within_roots, real_path
lazy from ...utils.threads import owned_thread
lazy from ..art.phash import PhashService
lazy from ..library.items import emit_library_item_upserted, emit_library_items_upserted
lazy from ..storage.assets import AssetStorage, FolderListing
lazy from .art import LocalArtInspector
lazy from .theme import refresh_theme

#: Items refreshed at once. A refresh mostly waits on the filesystem (a
#: listing and a stat per file), which overlaps well; database writes happen
#: only for changes and queue on the writer lock.
_REFRESH_CONCURRENCY = 8


def _in_scope(
    items: list[MediaItem],
    *,
    real_roots_by_media_type: Mapping[MediaType, tuple[str, ...]] | None,
    folder_paths: set[str] | None,
) -> list[MediaItem]:
    """Keep the items whose folders are in scope, in one worker-thread call."""
    return [
        item
        for item in items
        if item.folder_path
        and (folder_paths is None or real_path(item.folder_path) in folder_paths)
        and (
            real_roots_by_media_type is None
            or is_within_roots(
                item.folder_path, real_roots_by_media_type.get(item.media_type, ())
            )
        )
    ]


def _real_paths(paths: Collection[str | Path]) -> set[str]:
    return {real_path(path) for path in paths}


def _real_roots(
    roots_by_media_type: Mapping[MediaType, Collection[str | Path]],
) -> dict[MediaType, tuple[str, ...]]:
    return {
        media_type: tuple(_real_paths(roots))
        for media_type, roots in roots_by_media_type.items()
    }


class LocalAssets:
    """Refresh the recorded facts of items' local artwork and theme files."""

    def __init__(
        self,
        *,
        asset_storage: AssetStorage,
        phash: PhashService,
        database: Database,
        publisher: protocols.EventPublisher,
    ) -> None:
        self.asset_storage = asset_storage
        self._art = LocalArtInspector(asset_storage, phash)
        self._database = database
        self._publisher = publisher

    @property
    def inspector(self) -> LocalArtInspector:
        """Return the artwork inspector, for comparing one file on demand."""
        return self._art

    async def refresh(
        self, item_id: int, *, art: bool = True, themes: bool = True
    ) -> bool:
        """Refresh one item while the caller holds its asset lock.

        Returns:
            Whether anything the library shows for the item changed.
        """
        async with self._database.read_session() as session:
            item = await session.get(MediaItem, item_id)
        if item is None:
            return False
        return await self.refresh_row(item, art=art, themes=themes)

    async def refresh_row(
        self, item: MediaItem, *, art: bool = True, themes: bool = True
    ) -> bool:
        """Refresh one item from its row, while the caller holds its asset lock.

        For a caller that has just read or written the row, so it is not read
        again; only a show's seasons are.

        Returns:
            Whether anything the library shows for the item changed.
        """
        if item.id is None:
            return False
        seasons_by_item = await self._seasons_by_item([item] if art else [])
        return await self._refresh_rows(
            item, seasons_by_item[item.id], art=art, themes=themes
        )

    async def _refresh_rows(
        self, item: MediaItem, seasons: list[Season], *, art: bool, themes: bool
    ) -> bool:
        """Refresh one item from rows read before its files.

        The rows may be older than the caller's asset lock: every write first
        checks that the row still holds what was inspected, so a download or
        refresh that finished in between is never overwritten.
        """
        # One listing serves the item's artwork, theme and season lookups.
        listing = FolderListing()
        art_changed = art and await self._art.refresh_item(
            item, seasons, self._database, listing=listing
        )
        theme_changed = themes and await refresh_theme(
            item, self.asset_storage, self._database, listing=listing
        )
        return art_changed or theme_changed

    async def refresh_locked(
        self,
        item_id: int,
        *,
        source: str,
        art: bool = True,
        themes: bool = True,
    ) -> bool:
        """Refresh one item under its asset lock and publish a visible change."""
        async with self.asset_storage.asset_locks.acquire(item_id):
            changed = await self.refresh(item_id, art=art, themes=themes)
        if changed:
            await emit_library_item_upserted(
                item_id, source, self._publisher, database=self._database
            )
        return changed

    async def reconcile(
        self,
        *,
        source: str,
        art: bool = True,
        themes: bool = True,
        media_type: MediaType | None = None,
        library_id: str | None = None,
        library_ids: list[str] | None = None,
        item_ids: Collection[int] | None = None,
        roots_by_media_type: Mapping[MediaType, Collection[str | Path]] | None = None,
        folder_paths: Collection[str | Path] | None = None,
    ) -> None:
        """Refresh every visible item in scope and publish each changed record."""
        selected_ids = list(dict.fromkeys(item_ids)) if item_ids is not None else None
        selected_paths = (
            await owned_thread(_real_paths, folder_paths)
            if folder_paths is not None
            else None
        )
        real_roots = (
            await owned_thread(_real_roots, roots_by_media_type)
            if roots_by_media_type is not None
            else None
        )
        after_id = 0
        while True:
            async with self._database.read_session() as session:
                candidates = await MediaItemRepository(
                    session
                ).list_visible_with_folder_paths(
                    after_id=after_id,
                    limit=PAGE_SIZE,
                    media_type=media_type,
                    library_id=library_id,
                    library_ids=library_ids,
                    item_ids=selected_ids,
                )
            items = await owned_thread(
                _in_scope,
                candidates,
                real_roots_by_media_type=real_roots,
                folder_paths=selected_paths,
            )
            seasons_by_item = await self._seasons_by_item(items if art else [])
            work = [
                (item, item.id, seasons_by_item[item.id])
                for item in items
                if item.id is not None
            ]
            async with aclosing(
                in_order(
                    work,
                    lambda row: self._refresh_batch_item(*row, art=art, themes=themes),
                    limit=_REFRESH_CONCURRENCY,
                )
            ) as refreshed:
                changed = [item_id async for item_id in refreshed if item_id]
            await emit_library_items_upserted(
                changed, source, self._publisher, database=self._database
            )
            if len(candidates) < PAGE_SIZE:
                return
            after_id = max(item.id or 0 for item in candidates)

    async def _refresh_batch_item(
        self,
        item: MediaItem,
        item_id: int,
        seasons: list[Season],
        *,
        art: bool,
        themes: bool,
    ) -> int | None:
        """Refresh one batch item under its asset lock; return its ID if it changed."""
        async with self.asset_storage.asset_locks.acquire(item_id):
            changed = await self._refresh_rows(item, seasons, art=art, themes=themes)
        return item_id if changed else None

    async def _seasons_by_item(
        self, items: list[MediaItem]
    ) -> defaultdict[int, list[Season]]:
        """Read the seasons of a batch's shows in one query."""
        seasons_by_item: defaultdict[int, list[Season]] = defaultdict(list)
        show_ids = [
            item.id
            for item in items
            if item.id is not None and item.media_type == MediaType.SHOW
        ]
        if show_ids:
            async with self._database.read_session() as session:
                for season in await SeasonRepository(session).list_for_items(show_ids):
                    seasons_by_item[season.media_item_id].append(season)
        return seasons_by_item
