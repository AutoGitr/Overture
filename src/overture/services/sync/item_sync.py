"""Per-item matching, creation, and update reconciliation."""

lazy from dataclasses import dataclass

lazy from sqlmodel import col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.ledger import local_file, place_local, read_asset, selection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.media_item_copy import MediaItemCopy
lazy from ...domain import (
    ITEM_ASSETS,
    AutoUnmonitor,
    MediaType,
    ServerAsset,
    TermKind,
    guid_int,
    guid_text,
)
lazy from ...media_servers.adapters import ServerItem, SyncItemResult, image_version
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.terms import TermRepository
lazy from ...utils.time import utc_now
lazy from ..library.completion import auto_unmonitor_completed
lazy from ..needs import apply_needs
lazy from .art_urls import ResolvedArtUrls, apply_provider_art_urls
lazy from .season_sync import SeasonSynchronizer
lazy from .tmdb_enrichment import record_tmdb_facts


@dataclass(slots=True, frozen=True)
class CopyPlace:
    """Where one server holds an item: its database number and whether it leads.

    The lead server is the first in MEDIA_SERVERS that lists the title; only
    its copy describes the title.
    """

    server_id: int
    lead: bool


class ItemReconciler:
    """Match a server's items to titles, and record each as that server's copy."""

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
            item.monitored,
            item.studio,
            item.last_matched_at,
            item.created_at,
            item.server_added_at,
            item.server_removed_at,
        )

    def visible_item_snapshot(self, item: MediaItem) -> tuple[object, ...]:
        """Return sidebar-relevant item and asset fields for change detection."""
        if item.id is None:
            return (self.visible_item_fields(item), (), (), ())
        return (
            self.visible_item_fields(item),
            *(_asset_fingerprint(item, kind) for kind in ITEM_ASSETS),
        )

    async def sync_item(
        self,
        session: AsyncSession,
        place: CopyPlace,
        server_item: ServerItem,
        resolved: ResolvedArtUrls,
        item: MediaItem | None,
        *,
        auto_unmonitor: AutoUnmonitor,
    ) -> SyncItemResult:
        """Reconcile one normalized provider item."""
        if not item:
            return await self.create_item(
                session, place, server_item, resolved, auto_unmonitor=auto_unmonitor
            )

        before_snapshot = self.visible_item_snapshot(item)
        before_fields = self.visible_item_fields(item)
        art_pulled, metadata_changed, left = await self.update_item(
            session, place, item, server_item, resolved, auto_unmonitor=auto_unmonitor
        )
        changes = tuple(
            change
            for change, happened in (
                (
                    "metadata",
                    metadata_changed or before_fields != self.visible_item_fields(item),
                ),
                ("artwork selection from the server", art_pulled),
            )
            if happened
        )
        return SyncItemResult(
            item_id=item.id,
            media_type=item.media_type,
            visible_changed=bool(changes)
            or before_snapshot != self.visible_item_snapshot(item),
            changes=changes,
            left_libraries=left,
        )

    async def find_existing_item(
        self,
        session: AsyncSession,
        server_id: int,
        server_item: ServerItem,
        *,
        exclude_item_ids: set[int] | None = None,
        for_update: bool = True,
    ) -> MediaItem | None:
        """Find the title a server's item is a copy of.

        The title the server already keeps it as comes first, unless the server
        now names it another title; then the title in its folder; then one
        with its IDs. A lookup that only identifies the row passes
        ``for_update=False``.
        """
        media_items = MediaItemRepository(session)
        item = await media_items.find_by_copy(
            server_id,
            server_item.id,
            server_item.media_type,
            exclude_item_ids=exclude_item_ids,
            for_update=for_update,
        )
        if item is not None and not _has_metadata_conflict(item, server_item):
            return item

        if server_item.folder_path:
            item = await media_items.find_by_folder_path(
                server_item.folder_path,
                server_item.media_type,
                exclude_item_ids=exclude_item_ids,
                for_update=for_update,
            )
            if item is not None:
                return item

        if server_item.guids:
            return await media_items.find_by_external_guids(
                server_item.guids,
                server_item.media_type,
                server_id=server_id,
                folder_path=server_item.folder_path,
                exclude_item_ids=exclude_item_ids,
                for_update=for_update,
            )
        return None

    async def create_item(
        self,
        session: AsyncSession,
        place: CopyPlace,
        server_item: ServerItem,
        resolved: ResolvedArtUrls,
        *,
        auto_unmonitor: AutoUnmonitor,
    ) -> SyncItemResult:
        """Create a title from the first server item found of it."""
        item = MediaItem(
            media_type=MediaType(server_item.media_type),
            title=server_item.title,
            year=server_item.year,
            tmdb_id=guid_int(server_item.guids, "tmdb"),
            tvdb_id=guid_int(server_item.guids, "tvdb"),
            imdb_id=guid_text(server_item.guids, "imdb"),
            folder_path=server_item.folder_path,
            monitored=True,
            created_at=utc_now(),
        )
        session.add(item)
        await session.flush()
        place_local(item, ITEM_ASSETS, folder=item.folder_path is not None)
        await record_copy(session, item, place.server_id, server_item)
        await apply_server_metadata(session, item, server_item)
        await apply_provider_collection(session, item, server_item)

        item.last_synced_at = utc_now()
        apply_provider_art_urls(item, server_item, resolved, only_missing=False)
        if server_item.media_type == MediaType.SHOW:
            await self._season_sync.upsert_seasons(
                session,
                item,
                server_item.seasons,
                resolved,
                server_id=place.server_id,
                lead=True,
                only_missing_art=False,
            )
        await apply_needs(session, items=[item])
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
        place: CopyPlace,
        item: MediaItem,
        server_item: ServerItem,
        resolved: ResolvedArtUrls,
        *,
        auto_unmonitor: AutoUnmonitor,
    ) -> tuple[bool, bool, tuple[str, ...]]:
        """Record a server's copy of a title, and let the lead copy describe it.

        Only values that differ are written, so an unchanged item commits an
        empty transaction; the caller stamps the item as synced.

        An item chosen from TMDB has never been linked to a server item: its
        selections are the user's, so the server only fills empty slots. On
        the sync that first gives it a folder the server fills none, so every
        selection it holds then is one to download.

        Returns:
            Whether the server's artwork selection was saved, whether the
            title's metadata changed, and the libraries it was held in before.
        """
        copy = await record_copy(session, item, place.server_id, server_item)
        item.server_removed_at = None
        if item.folder_path is None and server_item.folder_path is not None:
            resolved = {}
        if not place.lead and item.folder_path is not None:
            if server_item.media_type == MediaType.SHOW:
                await self._season_sync.upsert_seasons(
                    session,
                    item,
                    server_item.seasons,
                    resolved,
                    server_id=place.server_id,
                    lead=False,
                    only_missing_art=True,
                )
            session.add(item)
            return False, False, copy.left
        moved = item.folder_path != server_item.folder_path
        item.folder_path = server_item.folder_path
        place_local(item, ITEM_ASSETS, folder=item.folder_path is not None, moved=moved)

        if server_item.title:
            item.title = server_item.title
        if server_item.year is not None and (item.year is None or copy.replaced):
            item.year = server_item.year
        changed = await apply_server_metadata(session, item, server_item)

        item.tmdb_id = item.tmdb_id or guid_int(server_item.guids, "tmdb")
        item.tvdb_id = item.tvdb_id or guid_int(server_item.guids, "tvdb")
        item.imdb_id = item.imdb_id or guid_text(server_item.guids, "imdb")
        await apply_provider_collection(session, item, server_item)

        art_pulled = apply_provider_art_urls(
            item, server_item, resolved, only_missing=not copy.replaced
        )

        if server_item.media_type == MediaType.SHOW:
            await self._season_sync.upsert_seasons(
                session,
                item,
                server_item.seasons,
                resolved,
                server_id=place.server_id,
                lead=place.lead,
                only_missing_art=not copy.replaced,
                moved=moved,
            )

        await apply_needs(session, items=[item])
        await auto_unmonitor_completed(session, item, policy=auto_unmonitor)
        session.add(item)
        return art_pulled, TermKind.DIRECTOR in changed, copy.left


@dataclass(slots=True, frozen=True)
class RecordedCopy:
    """A server's copy as a sync recorded it."""

    copy: MediaItemCopy
    #: The server held the title under another item: what it shows for it
    #: replaces what it showed.
    replaced: bool
    #: Libraries the title was held in before, which this one may succeed:
    #: the server's own earlier library, or other servers' when it is new here.
    left: tuple[str, ...]


async def record_copy(
    session: AsyncSession, item: MediaItem, server_id: int, server_item: ServerItem
) -> RecordedCopy:
    """Record what a server keeps for its copy of *item*."""
    copies = (
        await session.exec(
            select(MediaItemCopy).where(col(MediaItemCopy.media_item_id) == item.id)
        )
    ).all()
    copy = next((each for each in copies if each.server_id == server_id), None)
    replaced = copy is not None and copy.server_item_id != server_item.id
    left = tuple(
        each.library_id
        for each in (copies if copy is None else [copy])
        if each.library_id != server_item.library_id
    )
    if copy is None:
        copy = MediaItemCopy(
            media_item_id=item.id or 0,
            server_id=server_id,
            media_type=item.media_type,
            server_item_id=server_item.id,
            library_id=server_item.library_id,
        )
    copy.server_item_id = server_item.id
    copy.library_id = server_item.library_id
    copy.removed_at = None
    copy.verified_at = utc_now()
    copy.added_at = server_item.server_added_at
    copy.plays = server_item.plays
    copy.last_played_at = server_item.last_played_at
    copy.unplayed = server_item.unplayed
    copy.in_progress = server_item.in_progress
    copy.user_rating = server_item.user_rating
    copy.labels = list(server_item.labels)
    copy.poster_version = image_version(server_item.poster_url)
    copy.background_version = image_version(server_item.background_url)
    copy.director_etag = (
        server_item.director_etag if server_item.media_type == MediaType.MOVIE else None
    )
    session.add(copy)
    await session.flush()
    return RecordedCopy(copy, replaced, left)


async def apply_server_metadata(
    session: AsyncSession, item: MediaItem, server_item: ServerItem
) -> frozenset[TermKind]:
    """Copy the lead server's description of a title, which criteria evaluate.

    Only movies have directors. Returns the kinds of values that changed.
    """
    changed = await TermRepository(session).assign(
        item.id or 0,
        {
            TermKind.GENRE: server_item.genres,
            TermKind.ACTOR: server_item.actors,
            TermKind.WRITER: server_item.writers,
            TermKind.PRODUCER: server_item.producers,
            TermKind.COUNTRY: server_item.countries,
            TermKind.LABEL: server_item.labels,
            TermKind.RESOLUTION: server_item.resolutions,
            TermKind.DIRECTOR: server_item.directors
            if server_item.media_type == MediaType.MOVIE
            else (),
        },
    )
    item.server_added_at = server_item.server_added_at
    item.sort_title = server_item.sort_title
    item.studio = server_item.studio
    item.content_rating = server_item.content_rating
    item.edition = server_item.edition
    item.critic_rating = server_item.critic_rating
    item.audience_rating = server_item.audience_rating
    item.user_rating = server_item.user_rating
    item.duration_seconds = server_item.duration_seconds
    item.plays = server_item.plays
    item.last_played_at = server_item.last_played_at
    item.unplayed = server_item.unplayed
    item.in_progress = server_item.in_progress
    item.release_date = server_item.release_date
    item.versions = server_item.versions
    return changed


async def apply_provider_collection(
    session: AsyncSession, item: MediaItem, server_item: ServerItem
) -> None:
    """Record the TMDB collection a server names for a movie, without a TMDB token.

    Jellyfin's TMDB plugin stores it among the movie's provider IDs. A
    rematched title drops the TMDB facts of its previous match.
    """
    if item.tmdb_checked_id is not None and item.tmdb_checked_id != item.tmdb_id:
        await record_tmdb_facts(session, item, None)
        item.tmdb_checked_id = None
    collection_id = guid_int(server_item.guids, "tmdbcollection")
    if item.media_type is MediaType.MOVIE and collection_id and item.tmdb_id:
        item.tmdb_collection_id = collection_id


def _asset_fingerprint(item: MediaItem, kind: ServerAsset) -> tuple[object, ...]:
    """Return the change-detection fingerprint of one of an item's assets."""
    asset = read_asset(item, kind)
    return (asset.status, selection(asset), local_file(asset))


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
