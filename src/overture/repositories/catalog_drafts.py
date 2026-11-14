"""Catalog draft query helpers."""

lazy from collections.abc import Iterable

lazy from sqlmodel import col, or_, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.catalog import CatalogDraft
lazy from ..domain import CatalogMediaType


class CatalogDraftRepository:
    """Centralize catalog draft persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_all(self) -> list[CatalogDraft]:
        """Return every draft."""
        return list((await self.session.exec(select(CatalogDraft))).all())

    async def find(
        self,
        media_type: CatalogMediaType,
        identities: Iterable[tuple[str, int | str]],
    ) -> CatalogDraft | None:
        """Return the draft of an entry that shares any of these identities."""
        clauses = [
            col(getattr(CatalogDraft, field)) == value for field, value in identities
        ]
        if not clauses:
            return None
        stmt = select(CatalogDraft).where(
            col(CatalogDraft.media_type) == media_type, or_(*clauses)
        )
        return (await self.session.exec(stmt)).first()
