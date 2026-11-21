"""Saved schedule query helpers."""

lazy from sqlmodel import col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.saved_schedule import SavedSchedule
lazy from ..domain import ScheduleKind


class SavedScheduleRepository:
    """Centralize persisted schedule queries and mutations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, schedule_id: int) -> SavedSchedule | None:
        """Return a schedule by ID."""
        return await self.session.get(SavedSchedule, schedule_id)

    async def singleton(self, kind: ScheduleKind) -> SavedSchedule | None:
        """Return the singleton schedule row for *kind*, if one was saved."""
        return (
            await self.session.exec(
                select(SavedSchedule).where(col(SavedSchedule.kind) == kind)
            )
        ).first()

    async def enabled(self, kind: ScheduleKind, *, default: bool) -> bool:
        """Return whether *kind* is enabled, defaulting when no row was saved."""
        value = (
            await self.session.exec(
                select(col(SavedSchedule.enabled)).where(
                    col(SavedSchedule.kind) == kind
                )
            )
        ).first()
        return default if value is None else bool(value)

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

    async def move_library(self, library_id: str, replacement: str) -> None:
        """Make every schedule that names a library name its replacement instead."""
        await self._replace("library_ids", library_id, replacement)

    async def rename_group(self, name: str, replacement: str) -> None:
        """Make every schedule that runs a collection group name it as renamed."""
        await self._replace("collection_groups", name, replacement)

    async def _replace(self, key: str, value: str, replacement: str) -> None:
        """Replace *value* in each named schedule's list under *key*."""
        stmt = select(SavedSchedule).where(
            col(SavedSchedule.kind).in_((ScheduleKind.ASSETS, ScheduleKind.SYNC))
        )
        for record in (await self.session.exec(stmt)).all():
            values: list[str] = record.payload.get(key) or []
            if value in values:
                moved = [replacement if each == value else each for each in values]
                record.payload = {**record.payload, key: list(dict.fromkeys(moved))}
                self.session.add(record)

    def add(self, record: SavedSchedule) -> None:
        """Stage a schedule for persistence."""
        self.session.add(record)

    async def delete(self, record: SavedSchedule) -> None:
        """Delete a schedule."""
        await self.session.delete(record)
