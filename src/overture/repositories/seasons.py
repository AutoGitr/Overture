"""Season query helpers."""

lazy from datetime import datetime

lazy from sqlmodel import col, or_, select, update
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.completion import HOLDS_FILES
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.season import Season
lazy from ..domain import ArtType

#: Seasons whose artwork counts: those with video files, and every season of
#: an item without a local folder, whose seasons come from TMDB.
TRACKED_SEASON = or_(
    col(Season.file_count) > 0,
    col(Season.media_item_id).in_(select(MediaItem.id).where(~HOLDS_FILES)),
)


class SeasonRepository:
    """Centralize recurring season persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_item(self, season_id: int, media_item_id: int) -> Season | None:
        """Return a season only when it belongs to the requested media item.

        A season the session already holds is returned without a query.
        """
        season = await self.session.get(Season, season_id)
        return season if season and season.media_item_id == media_item_id else None

    async def art_owner(
        self, item: MediaItem, art_type: ArtType, season_id: int | None
    ) -> MediaItem | Season | None:
        """Return the item, or its season *season_id*, that owns an artwork slot.

        ``None`` means a season-owned slot named no season of this item.
        """
        if not art_type.owned_by_season:
            return item
        if season_id is None or item.id is None:
            return None
        return await self.get_for_item(season_id, item.id)

    async def mark_matched(self, season_ids: set[int], when: datetime) -> None:
        """Stamp ``last_matched_at`` on many seasons with one statement."""
        if not season_ids:
            return
        await self.session.exec(
            update(Season)
            .where(col(Season.id).in_(season_ids))
            .values(last_matched_at=when)
        )

    async def list_for_item(self, media_item_id: int) -> list[Season]:
        """Return seasons belonging to one media item."""
        stmt = select(Season).where(col(Season.media_item_id) == media_item_id)
        result = await self.session.exec(stmt)
        return list(result.all())

    async def list_for_items(self, media_item_ids: list[int]) -> list[Season]:
        """Return the seasons belonging to the media items."""
        stmt = select(Season).where(col(Season.media_item_id).in_(media_item_ids))
        result = await self.session.exec(stmt)
        return list(result.all())

    async def map_by_number_for_item(self, media_item_id: int) -> dict[int, Season]:
        """Return seasons for one media item keyed by season number."""
        seasons = await self.list_for_item(media_item_id)
        return {season.season_num: season for season in seasons}

    async def list_tracked_for_item(self, media_item_id: int) -> list[Season]:
        """Return the item's tracked seasons, by season number."""
        stmt = (
            select(Season)
            .where(col(Season.media_item_id) == media_item_id, TRACKED_SEASON)
            .order_by(col(Season.season_num))
        )
        result = await self.session.exec(stmt)
        return list(result.all())

    async def list_tracked_for_items(
        self, media_item_ids: list[int], *, ordered: bool = False
    ) -> list[Season]:
        """Return the tracked seasons of the parent items."""
        if not media_item_ids:
            return []
        stmt = select(Season).where(
            col(Season.media_item_id).in_(media_item_ids), TRACKED_SEASON
        )
        if ordered:
            stmt = stmt.order_by(col(Season.media_item_id), col(Season.season_num))
        result = await self.session.exec(stmt)
        return list(result.all())

    async def tracked_season_nums_by_item_ids(
        self, media_item_ids: list[int]
    ) -> dict[int, set[int]]:
        """Return tracked season numbers keyed by media item ID."""
        if not media_item_ids:
            return {}
        result = await self.session.exec(
            select(Season.media_item_id, Season.season_num).where(
                col(Season.media_item_id).in_(media_item_ids), TRACKED_SEASON
            )
        )
        seasons_by_item_id: dict[int, set[int]] = {}
        for item_id, season_num in result.all():
            seasons_by_item_id.setdefault(item_id, set()).add(season_num)
        return seasons_by_item_id
