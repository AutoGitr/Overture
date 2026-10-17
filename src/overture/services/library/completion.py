"""Apply completion-based monitoring policy inside asset write transactions."""

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.completion import art_completion, theme_status
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import get_app_settings
lazy from ...domain import AssetStatus, AutoUnmonitor, MediaType
lazy from ...repositories.seasons import SeasonRepository


async def auto_unmonitor_completed(
    session: AsyncSession,
    item: MediaItem,
    *,
    policy: AutoUnmonitor | None = None,
) -> bool:
    """Unmonitor a completed item; return whether monitoring changed.

    Call after recording assets, before committing and publishing the item.
    Completeness follows :mod:`overture.db.completion`, as the library shows it.
    A caller visiting many items passes the *policy* it read once; otherwise
    it is read from the settings here.
    """
    if not item.monitored or item.id is None:
        return False
    if policy is None:
        policy = (await get_app_settings(session)).auto_unmonitor
    if policy is AutoUnmonitor.OFF:
        return False

    theme_complete = theme_status(item) is AssetStatus.COMPLETE
    art_complete = False
    if policy is not AutoUnmonitor.THEME:
        seasons = (
            await SeasonRepository(session).list_tracked_for_item(item.id)
            if item.media_type == MediaType.SHOW
            else []
        )
        art_complete = art_completion(item, seasons).art_status is AssetStatus.COMPLETE

    match policy:
        case AutoUnmonitor.ART:
            complete = art_complete
        case AutoUnmonitor.THEME:
            complete = theme_complete
        case AutoUnmonitor.ART_OR_THEME:
            complete = art_complete or theme_complete
        case AutoUnmonitor.ART_AND_THEME:
            complete = art_complete and theme_complete

    if complete:
        item.monitored = False
        session.add(item)
    return complete
