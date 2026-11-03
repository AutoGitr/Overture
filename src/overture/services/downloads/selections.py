"""Download the selections an item recorded before it had a local folder."""

lazy from ...db.art_slots import find_art_slot
lazy from ...db.models.media_item import MediaItem
lazy from ...db.session import Database
lazy from ...domain import ITEM_ART_TYPES, ArtType
lazy from ...repositories.seasons import SeasonRepository
lazy from .queue import JobTarget
lazy from .service import DownloadService


async def queue_saved_selection_downloads(
    item_id: int,
    *,
    youtube_id: str | None,
    downloads: DownloadService,
    database: Database,
) -> int:
    """Queue the choices made before adoption, replacing existing local files.

    An item chosen from TMDB records selections only; once sync gives it a
    folder, these downloads fetch what was chosen. The theme ID comes from
    before the local refresh, which may discover an unrelated file's ID.
    Returns how many were queued.
    """
    async with (
        downloads.asset_locks.acquire(item_id),
        database.write_session() as session,
    ):
        item = await session.get(MediaItem, item_id)
        if item is None:
            return 0
        seasons = await SeasonRepository(session).list_tracked_for_item(item_id)
        art = [
            (art_type, slot.url, None)
            for art_type in ITEM_ART_TYPES
            if (slot := find_art_slot(item, art_type)) and slot.url
        ] + [
            (ArtType.SEASON_POSTER, slot.url, season.id)
            for season in seasons
            if (slot := find_art_slot(season, ArtType.SEASON_POSTER)) and slot.url
        ]
        for art_type, url, season_id in art:
            await downloads.queue_job(
                session, JobTarget.art(item_id, art_type, url, season_id=season_id)
            )
        theme = youtube_id is not None and item.youtube_id == youtube_id
        if youtube_id is not None and theme:
            await downloads.queue_job(session, JobTarget.theme(item_id, youtube_id))

    await downloads.committed(session)
    return len(art) + theme
