"""Give test titles metadata values, such as genres and people."""

lazy from collections.abc import Sequence

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import TermKind
lazy from overture.repositories.collections import CollectionItem
lazy from overture.repositories.terms import TermRepository


def holding(item: MediaItem, **values: Sequence[str]) -> CollectionItem:
    """Return an unsaved *item* as rules read it, with values by kind.

    Every other kind reads as empty, for evaluating criteria in memory.
    """
    columns = [getattr(item, name) for name in CollectionItem._fields[:-1]]
    held = {TermKind(kind): names for kind, names in values.items()}
    return CollectionItem._make((*columns, {**dict.fromkeys(TermKind, ()), **held}))


async def assign(
    session: AsyncSession, item: MediaItem, **values: Sequence[str]
) -> None:
    """Give *item* values by kind, saving it first if it is new."""
    session.add(item)
    await session.flush()
    await TermRepository(session).assign(
        item.id or 0, {TermKind(kind): names for kind, names in values.items()}
    )
