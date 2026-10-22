"""Saved schedule query helpers."""

lazy from sqlmodel import col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.saved_schedule import SavedSchedule
lazy from ..domain import ScheduleKind


class SavedScheduleRepository:
    """Centralize saved assets and sync schedule persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, schedule_id: int) -> SavedSchedule | None:
        """Return a schedule by ID."""
        return await self.session.get(SavedSchedule, schedule_id)

    async def of_kind(self, kind: ScheduleKind) -> list[SavedSchedule]:
        """Return the schedules of one kind, oldest first."""
        stmt = (
            select(SavedSchedule)
            .where(col(SavedSchedule.kind) == kind)
            .order_by(col(SavedSchedule.created_at), col(SavedSchedule.id))
        )
        result = await self.session.exec(stmt)
        return list(result.all())

    async def name_exists(
        self,
        *,
        kind: ScheduleKind,
        name: str,
        exclude_id: int | None = None,
    ) -> bool:
        """Return whether a kind already uses *name*, ignoring case.

        Names are compared with :meth:`str.casefold` in Python because
        SQLite's ``LOWER`` and ``NOCASE`` only fold ASCII letters.
        """
        stmt = select(SavedSchedule.name).where(col(SavedSchedule.kind) == kind)
        if exclude_id is not None:
            stmt = stmt.where(col(SavedSchedule.id) != exclude_id)
        folded = name.casefold()
        return any(
            existing.casefold() == folded for existing in await self.session.exec(stmt)
        )

    def add(self, record: SavedSchedule) -> None:
        """Stage a schedule for persistence."""
        self.session.add(record)

    async def delete(self, record: SavedSchedule) -> None:
        """Delete a schedule."""
        await self.session.delete(record)
