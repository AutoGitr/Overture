"""Resolve artwork targets and adopt a local file's identical source.

Adopting records which public URL a local file came from without touching the
file. It is only done for bytes verified identical, and only while the file is
still the one that was verified.
"""

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.art_slots import ArtFileFacts, art_file_facts, read_art_slot, select_art
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import ArtType
lazy from ...repositories.seasons import SeasonRepository
lazy from ...utils.threads import owned_thread
lazy from ..library.completion import auto_unmonitor_completed
lazy from ..storage.assets import AssetStorage


async def resolve_art_target(
    session: AsyncSession,
    item_id: int,
    art_type: ArtType,
    season_id: int | None,
) -> tuple[MediaItem, Season | None, MediaItem | Season] | None:
    """Load the item, its season when relevant, and the slot's owner.

    Returns:
        ``(item, season, owner)``, or ``None`` when the requested target does
        not exist or does not apply to this item.
    """
    item = await session.get(MediaItem, item_id)
    if not item:
        return None
    owner = await SeasonRepository(session).art_owner(item, art_type, season_id)
    if owner is None:
        return None
    return item, owner if isinstance(owner, Season) else None, owner


async def adopt_art(
    item_id: int,
    art_type: ArtType,
    *,
    season_id: int | None,
    url: str,
    verified: ArtFileFacts,
    asset_storage: AssetStorage,
    database: Database,
) -> bool:
    """Record *url* as the selection of the identical local file *verified*.

    Returns:
        Whether it was recorded; ``False`` when the file or its record changed
        after verification, so the bytes compared are no longer on disk.
    """
    async with asset_storage.asset_locks.acquire(item_id):
        async with database.read_session() as session:
            target = await resolve_art_target(session, item_id, art_type, season_id)
        if target is None:
            return False
        item, season, _ = target
        path = await owned_thread(
            asset_storage.find_local_art_path, art_type, item=item, season=season
        )
        stored = (
            None
            if path is None
            else await owned_thread(asset_storage.stored_file, path)
        )
        if stored is None or (stored.file_hash, stored.mtime_ns, stored.size) != (
            verified.file_hash,
            verified.file_mtime_ns,
            verified.file_size,
        ):
            return False
        async with database.write_session() as session:
            target = await resolve_art_target(session, item_id, art_type, season_id)
            if target is None:
                return False
            item, _, owner = target
            if art_file_facts(read_art_slot(owner, art_type)) != verified:
                return False
            select_art(owner, art_type, url)
            session.add(owner)
            await auto_unmonitor_completed(session, item)
    return True
