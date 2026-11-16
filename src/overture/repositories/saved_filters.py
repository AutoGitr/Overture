"""Saved library filter queries."""

lazy from sqlmodel import col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.saved_filter import SavedFilter
lazy from ..domain import MediaType


class SavedFilterRepository:
    """Read and find saved library filters."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, filter_id: int) -> SavedFilter | None:
        """Return a saved filter by ID."""
        return await self.session.get(SavedFilter, filter_id)

    async def of_media_type(self, media_type: MediaType) -> list[SavedFilter]:
        """Return a media type's saved filters by name."""
        result = await self.session.exec(
            select(SavedFilter)
            .where(col(SavedFilter.media_type) == media_type)
            .order_by(col(SavedFilter.name), col(SavedFilter.id))
        )
        return list(result.all())

    async def name_exists(
        self, media_type: MediaType, name: str, *, exclude_id: int | None = None
    ) -> bool:
        """Return whether the media type has a filter of *name*, ignoring case.

        Names are folded in Python: SQLite's ``NOCASE`` folds only ASCII letters.
        """
        stmt = select(SavedFilter.name).where(col(SavedFilter.media_type) == media_type)
        if exclude_id is not None:
            stmt = stmt.where(col(SavedFilter.id) != exclude_id)
        folded = name.casefold()
        return any(
            found.casefold() == folded for found in await self.session.exec(stmt)
        )
