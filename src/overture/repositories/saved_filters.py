"""Saved library filter queries."""

lazy from sqlmodel import col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.saved_filter import SavedFilter


class SavedFilterRepository:
    """Read and find saved library filters."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, filter_id: int) -> SavedFilter | None:
        """Return a saved filter by ID."""
        return await self.session.get(SavedFilter, filter_id)

    async def by_name(self) -> list[SavedFilter]:
        """Return every saved filter by name."""
        result = await self.session.exec(
            select(SavedFilter).order_by(col(SavedFilter.name), col(SavedFilter.id))
        )
        return list(result.all())

    async def name_exists(self, name: str, *, exclude_id: int | None = None) -> bool:
        """Return whether a filter is named *name*, ignoring case.

        Names are folded in Python: SQLite's ``NOCASE`` folds only ASCII letters.
        """
        stmt = select(SavedFilter.name)
        if exclude_id is not None:
            stmt = stmt.where(col(SavedFilter.id) != exclude_id)
        folded = name.casefold()
        return any(
            found.casefold() == folded for found in await self.session.exec(stmt)
        )
