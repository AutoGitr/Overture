"""Give test titles metadata values, such as genres and people."""

lazy from collections.abc import Sequence

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.term import MediaItemTerm, Term
lazy from overture.domain import TermKind
lazy from overture.repositories.terms import TermRepository


def holding(item: MediaItem, **values: Sequence[str]) -> MediaItem:
    """Give an unsaved *item* values by kind, such as ``genre=["Action"]``.

    The terms live only in memory, for evaluating criteria; titles saved
    together use :func:`assign` so they share each term.
    """
    item.terms = [
        MediaItemTerm(term=Term(kind=TermKind(kind), name=name), position=position)
        for kind, names in values.items()
        for position, name in enumerate(names)
    ]
    return item


async def assign(
    session: AsyncSession, item: MediaItem, **values: Sequence[str]
) -> None:
    """Give a new or terms-loaded *item* values by kind, saved with the session."""
    await TermRepository(session).assign(
        item, {TermKind(kind): names for kind, names in values.items()}
    )
