"""Per-item matching, creation, and update reconciliation."""

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.art_slots import read_art_slot, record_art_file
lazy from ...db.models.media_item import MediaItem
lazy from ...db.theme_file import record_theme_file
lazy from ...domain import (
    ITEM_ART_TYPES,
    ArtType,
    AutoUnmonitor,
    MediaType,
    guid_int,
    guid_text,
)
lazy from ...media_servers.adapters import ServerItem, SyncItemResult
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...utils.time import utc_now
lazy from ..library.completion import auto_unmonitor_completed
lazy from .art_urls import ResolvedArtUrls, apply_provider_art_urls
lazy from .season_sync import SeasonSynchronizer


class ItemReconciler:
    """Match provider items to local records and create/update them."""

    def __init__(
        self,
        season_sync: SeasonSynchronizer,
    ) -> None:
        self._season_sync = season_sync

    @staticmethod
    def visible_item_fields(item: MediaItem) -> tuple[object, ...]:
        """Return sidebar-relevant media-item fields for change detection."""
        return (
            item.media_type,
            item.title,
            item.year,
            item.tmdb_id,
            item.tvdb_id,
            item.imdb_id,
            item.folder_path,
            item.server_item_id,
            item.server_link,
            item.library_id,
            item.monitored,
            item.director,
            item.studio,
            item.last_matched_at,
            item.created_at,
            item.server_added_at,
            item.server_removed_at,
        )

    async def visible_item_snapshot(
        self,
        session: AsyncSession,
        item: MediaItem,
    ) -> tuple[object, ...]:
        """Return sidebar-relevant item and asset fields for change detection."""
        if item.id is None:
            return (self.visible_item_fields(item), (), (), ())
        return (
            self.visible_item_fields(item),
            *(_art_slot_fingerprint(item, art_type) for art_type in ITEM_ART_TYPES),
            (item.youtube_id, item.theme_file_hash),
        )

    async def find_item_by_guids(
        self,
        session: AsyncSession,
        guids: dict[str, str],
        media_type: str,
        *,
        server_item_id: str | None = None,
        exclude_item_ids: set[int] | None = None,
        load_art: bool = True,
    ) -> MediaItem | None:
        """Look up a MediaItem by external GUID dict."""
        return await MediaItemRepository(session).find_by_external_guids(
            guids,
            media_type,
            server_item_id=server_item_id,
            exclude_item_ids=exclude_item_ids,
            load_art=load_art,
        )

    async def sync_item(
        self,
        session: AsyncSession,
        server_item: ServerItem,
        resolved: ResolvedArtUrls,
        item: MediaItem | None,
        *,
        auto_unmonitor: AutoUnmonitor,
    ) -> SyncItemResult:
        """Reconcile one normalized provider item."""
        if not item:
            return await self.create_item(
                session, server_item, resolved, auto_unmonitor=auto_unmonitor
            )

        before_snapshot = await self.visible_item_snapshot(session, item)
        before_fields = self.visible_item_fields(item)
        art_pulled = await self.update_item(
            session, item, server_item, resolved, auto_unmonitor=auto_unmonitor
        )
        changes = tuple(
            change
            for change, happened in (
                ("metadata", before_fields != self.visible_item_fields(item)),
                ("artwork selection from the server", art_pulled),
            )
            if happened
        )
        return SyncItemResult(
            item_id=item.id,
            media_type=item.media_type,
            visible_changed=bool(changes)
            or before_snapshot != await self.visible_item_snapshot(session, item),
            changes=changes,
        )

    async def find_existing_item(
        self,
        session: AsyncSession,
        server_item: ServerItem,
        *,
        exclude_item_ids: set[int] | None = None,
        load_art: bool = True,
    ) -> MediaItem | None:
        """Find the existing row a provider item would update.

        A lookup that only identifies the row passes ``load_art=False``.
        """
        media_items = MediaItemRepository(session)
        item: MediaItem | None = None

        if server_item.guids:
            item = await self.find_item_by_guids(
                session,
                server_item.guids,
                server_item.media_type,
                server_item_id=server_item.id,
                exclude_item_ids=exclude_item_ids,
                load_art=load_art,
            )

        if not item and server_item.folder_path:
            item = await media_items.find_by_folder_path(
                server_item.folder_path,
                server_item.media_type,
                exclude_item_ids=exclude_item_ids,
                load_art=load_art,
            )

        if not item:
            candidate = await media_items.find_by_server_id(
                server_item.id,
                server_item.media_type,
                exclude_item_ids=exclude_item_ids,
                load_art=load_art,
            )
            if candidate and not _has_metadata_conflict(candidate, server_item):
                item = candidate

        return item

    async def create_item(
        self,
        session: AsyncSession,
        server_item: ServerItem,
        resolved: ResolvedArtUrls,
        *,
        auto_unmonitor: AutoUnmonitor,
    ) -> SyncItemResult:
        """Create a local item from a provider item."""
        item = MediaItem(
            media_type=MediaType(server_item.media_type),
            title=server_item.title,
            year=server_item.year,
            tmdb_id=guid_int(server_item.guids, "tmdb"),
            tvdb_id=guid_int(server_item.guids, "tvdb"),
            imdb_id=guid_text(server_item.guids, "imdb"),
            folder_path=server_item.folder_path,
            server_item_id=server_item.id,
            server_link=server_item.server_link,
            library_id=server_item.library_id or None,
            director=(
                server_item.director
                if server_item.media_type == MediaType.MOVIE
                else None
            ),
            director_etag=(
                server_item.director_etag
                if server_item.media_type == MediaType.MOVIE
                else None
            ),
            studio=server_item.studio,
            genres=list(server_item.genres),
            monitored=True,
            server_added_at=server_item.server_added_at,
            created_at=utc_now(),
        )
        apply_provider_collection(item, server_item)
        session.add(item)
        await session.flush()

        item.server_verified_at = utc_now()
        item.last_synced_at = utc_now()
        apply_provider_art_urls(item, server_item, resolved, only_missing=False)
        if server_item.media_type == MediaType.SHOW:
            await self._season_sync.upsert_seasons(
                session,
                item,
                server_item.seasons,
                resolved,
                only_missing_art=False,
            )
        await auto_unmonitor_completed(session, item, policy=auto_unmonitor)

        session.add(item)
        return SyncItemResult(
            item_id=item.id,
            media_type=item.media_type,
            visible_changed=True,
            created=True,
        )

    async def update_item(
        self,
        session: AsyncSession,
        item: MediaItem,
        server_item: ServerItem,
        resolved: ResolvedArtUrls,
        *,
        auto_unmonitor: AutoUnmonitor,
    ) -> bool:
        """Update an existing local item from a provider item.

        Only values that differ are written, so an unchanged item commits an
        empty transaction; the caller stamps the item as synced.

        An item chosen from TMDB has never been linked to a server item: its
        selections are the user's, so the server only fills empty slots. On
        the sync that first gives it a folder the server fills none, so every
        selection it holds then is one to download.

        Returns:
            Whether the server's artwork selection was saved.
        """
        if item.folder_path is None and server_item.folder_path is not None:
            resolved = {}
        if item.folder_path != server_item.folder_path:
            # Files recorded at the old path are not the files at the new one;
            # the refresh that follows records what the new folder holds.
            item.folder_path = server_item.folder_path
            record_theme_file(item, None)
            for art_type in ITEM_ART_TYPES:
                record_art_file(item, art_type, None)

        server_changed = (
            item.server_item_id is not None and item.server_item_id != server_item.id
        )

        if server_item.title:
            item.title = server_item.title

        item.server_item_id = server_item.id
        item.server_removed_at = None
        item.server_link = server_item.server_link
        item.library_id = server_item.library_id or None
        if server_item.year is not None and (item.year is None or server_changed):
            item.year = server_item.year
        item.server_added_at = server_item.server_added_at
        if server_item.media_type == MediaType.MOVIE:
            item.director = server_item.director
            item.director_etag = server_item.director_etag
        else:
            item.director = None
            item.director_etag = None
        item.studio = server_item.studio
        item.genres = list(server_item.genres)

        item.tmdb_id = item.tmdb_id or guid_int(server_item.guids, "tmdb")
        item.tvdb_id = item.tvdb_id or guid_int(server_item.guids, "tvdb")
        item.imdb_id = item.imdb_id or guid_text(server_item.guids, "imdb")
        apply_provider_collection(item, server_item)

        art_pulled = apply_provider_art_urls(
            item, server_item, resolved, only_missing=not server_changed
        )

        if server_item.media_type == MediaType.SHOW:
            await self._season_sync.upsert_seasons(
                session,
                item,
                server_item.seasons,
                resolved,
                only_missing_art=not server_changed,
            )

        await auto_unmonitor_completed(session, item, policy=auto_unmonitor)
        session.add(item)
        return art_pulled


def apply_provider_collection(item: MediaItem, server_item: ServerItem) -> None:
    """Record the TMDB collection a server names for a movie, sparing TMDB.

    Jellyfin's TMDB plugin stores it among the movie's provider IDs.
    """
    if item.tmdb_collection_checked_id != item.tmdb_id:
        item.tmdb_collection_id = None
        item.tmdb_collection_checked_id = None
    collection_id = guid_int(server_item.guids, "tmdbcollection")
    if item.media_type is MediaType.MOVIE and collection_id and item.tmdb_id:
        item.tmdb_collection_id = collection_id
        item.tmdb_collection_checked_id = item.tmdb_id


def _art_slot_fingerprint(
    item: MediaItem, art_type: ArtType
) -> tuple[str | None, str | None]:
    """Return the change-detection fingerprint for one item artwork slot."""
    slot = read_art_slot(item, art_type)
    return (slot.url, slot.file_hash)


def _has_metadata_conflict(item: MediaItem, server_item: ServerItem) -> bool:
    """Return True if item has conflicting external GUIDs or folder paths."""
    if server_item.guids:
        tmdb = guid_int(server_item.guids, "tmdb")
        if tmdb is not None and item.tmdb_id is not None and item.tmdb_id != tmdb:
            return True
        tvdb = guid_int(server_item.guids, "tvdb")
        if tvdb is not None and item.tvdb_id is not None and item.tvdb_id != tvdb:
            return True
        imdb = guid_text(server_item.guids, "imdb")
        if imdb is not None and item.imdb_id is not None and item.imdb_id != imdb:
            return True

    if server_item.folder_path and item.folder_path:
        p1 = server_item.folder_path.rstrip("/\\").replace("\\", "/").lower()
        p2 = item.folder_path.rstrip("/\\").replace("\\", "/").lower()
        if p1 != p2:
            return True

    return False
