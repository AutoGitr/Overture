"""Server-audit work planning."""

lazy from collections import defaultdict
lazy from collections.abc import Collection
lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import CHUNK_SIZE, Database
lazy from ...domain import (
    ITEM_ART_TYPES,
    ArtType,
    MediaSortKey,
    MediaType,
    ServerAsset,
    media_sort_key,
)
lazy from ...repositories.media_items import MediaItemRepository
lazy from ...repositories.seasons import SeasonRepository
lazy from ...schemas.server_audit import ServerAuditRequest
lazy from ...utils.path import is_within_roots, real_path
lazy from ...utils.threads import owned_thread
lazy from ..local_assets.service import LocalAssets
lazy from ..storage.assets import AssetStorage, FolderListing


@dataclass(slots=True, frozen=True)
class AuditTarget:
    """One local file a server audit compares: an artwork slot, or the theme."""

    item_id: int
    #: The artwork slot, or ``None`` for the item's theme.
    art_type: ArtType | None = None
    season_id: int | None = None

    @property
    def asset(self) -> ServerAsset:
        """Return the media-server asset the target is compared with."""
        return (
            ServerAsset.THEME if self.art_type is None else self.art_type.server_asset
        )


def item_in_selected_roots(item: MediaItem, real_roots: Collection[Path]) -> bool:
    """Return whether an item's folder lies in one of the resolved roots."""
    return bool(item.folder_path) and is_within_roots(item.folder_path, real_roots)


def item_audit_work(
    item: MediaItem,
    art_types: Collection[ArtType],
    check_themes: bool,
    seasons: list[Season],
    asset_storage: AssetStorage,
) -> list[AuditTarget]:
    """Return one item's targets whose local files exist, reading each folder once.

    They are always in the order its results are listed: poster, background,
    season posters (*seasons*, in order), then theme.
    """
    item_id = item.id
    if item_id is None:
        return []
    listing = FolderListing()
    work = [
        AuditTarget(item_id, art_type)
        for art_type in ITEM_ART_TYPES
        if art_type in art_types
        and asset_storage.find_local_art_path(art_type, item=item, listing=listing)
        is not None
    ]
    work.extend(
        AuditTarget(item_id, ArtType.SEASON_POSTER, season.id)
        for season in seasons
        if asset_storage.find_local_art_path(
            ArtType.SEASON_POSTER, item=item, season=season, listing=listing
        )
        is not None
    )
    if (
        check_themes
        and asset_storage.local_theme_path(item, listing=listing) is not None
    ):
        work.append(AuditTarget(item_id))
    return work


def _select(
    items: list[MediaItem], roots: dict[MediaType, list[Path]]
) -> list[MediaItem]:
    """Keep the items whose folders lie under the selected roots of their type."""
    return [
        item
        for item in items
        if item_in_selected_roots(item, roots.get(item.media_type, ()))
    ]


def _inspect(
    params: ServerAuditRequest,
    items: list[MediaItem],
    seasons: list[Season],
    asset_storage: AssetStorage,
) -> list[tuple[MediaSortKey, list[AuditTarget]]]:
    """Return each item's targets: the files of the audited types present now."""
    seasons_by_item: defaultdict[int, list[Season]] = defaultdict(list)
    for season in seasons:
        seasons_by_item[season.media_item_id].append(season)
    return [
        (
            media_sort_key(item.media_type, item.title, item.id),
            item_audit_work(
                item,
                params.art_types,
                params.check_themes,
                seasons_by_item[item.id or 0],
                asset_storage,
            ),
        )
        for item in items
    ]


async def plan_audit(
    params: ServerAuditRequest,
    local_assets: LocalAssets,
    *,
    database: Database,
    chunk: int = CHUNK_SIZE,
) -> list[AuditTarget]:
    """Return every local asset the audit will compare, movies then shows by title.

    Only monitored items in scope are read: their theme records are refreshed
    when themes are audited, and only files present now become targets.
    """
    roots = {
        media_type: [Path(real_path(root)) for root in folders]
        for media_type, folders in (
            (MediaType.MOVIE, params.movie_folders),
            (MediaType.SHOW, params.show_folders),
        )
    }
    planned: list[tuple[MediaSortKey, list[AuditTarget]]] = []
    after_id = 0
    while True:
        async with database.read_session() as session:
            items = await MediaItemRepository(session).list_monitored_with_folder_paths(
                item_ids=params.item_ids, after_id=after_id, limit=chunk
            )
        selected = (
            items
            if params.item_ids is not None
            else await owned_thread(_select, items, roots)
        )
        if params.check_themes and selected:
            await local_assets.reconcile(
                item_ids=[item.id for item in selected if item.id is not None],
                art=False,
                source="server.audit",
            )
        show_ids = [
            item.id
            for item in selected
            if item.media_type == "show" and item.id is not None
        ]
        async with database.read_session() as session:
            seasons = (
                await SeasonRepository(session).list_tracked_for_items(
                    show_ids, ordered=True
                )
                if ArtType.SEASON_POSTER in params.art_types
                else []
            )
        planned.extend(
            await owned_thread(
                _inspect, params, selected, seasons, local_assets.asset_storage
            )
        )
        if len(items) < chunk:
            return [target for _, targets in sorted(planned) for target in targets]
        after_id = max(item.id or 0 for item in items)
