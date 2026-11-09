"""The metadata values titles hold, such as genres and people."""

lazy from collections.abc import Collection, Iterable, Mapping
lazy from itertools import batched

lazy from sqlmodel import col, delete, exists, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.term import MediaItemTerm, Term
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import TermKind


class TermRepository:
    """Give titles their values and read them back by title."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def assign(
        self, item: MediaItem, values: Mapping[TermKind, Iterable[str]]
    ) -> bool:
        """Give *item* exactly these values of each kind named; kinds not named stay.

        The item is new, or loaded with its terms. Returns whether any changed.
        """
        wanted = {
            kind: list(dict.fromkeys(name for name in names if name))
            for kind, names in values.items()
        }
        if all(item.values(kind) == names for kind, names in wanted.items()):
            return False
        terms = await self._terms(
            {(kind, name) for kind, names in wanted.items() for name in names}
        )
        current = {(link.term.kind, link.term.name): link for link in item.terms}
        links = [link for link in item.terms if link.term.kind not in wanted]
        for kind, names in wanted.items():
            for position, name in enumerate(names):
                link = current.get((kind, name)) or MediaItemTerm(
                    term=terms[kind, name]
                )
                link.position = position
                links.append(link)
        item.terms = links
        return True

    async def _terms(
        self, wanted: Collection[tuple[TermKind, str]]
    ) -> dict[tuple[TermKind, str], Term]:
        """Return the terms *wanted* names, adding those not stored yet."""
        names: dict[TermKind, list[str]] = {}
        for kind, name in wanted:
            names.setdefault(kind, []).append(name)
        found: dict[tuple[TermKind, str], Term] = {}
        for kind, kind_names in names.items():
            for batch in batched(kind_names, CHUNK_SIZE, strict=False):
                for term in (
                    await self.session.exec(
                        select(Term).where(
                            col(Term.kind) == kind, col(Term.name).in_(batch)
                        )
                    )
                ).all():
                    found[term.kind, term.name] = term
        for kind, name in set(wanted) - found.keys():
            term = Term(kind=kind, name=name)
            self.session.add(term)
            found[kind, name] = term
        return found

    async def values_by_item(
        self, item_ids: Collection[int], kind: TermKind
    ) -> dict[int, list[str]]:
        """Return the values of *kind* each of *item_ids* holds, in order."""
        found: dict[int, list[str]] = {}
        for batch in batched(item_ids, CHUNK_SIZE, strict=False):
            rows = await self.session.exec(
                select(MediaItemTerm.media_item_id, Term.name)
                .join(Term, col(Term.id) == col(MediaItemTerm.term_id))
                .where(
                    col(MediaItemTerm.media_item_id).in_(batch),
                    col(Term.kind) == kind,
                )
                .order_by(col(MediaItemTerm.media_item_id), col(MediaItemTerm.position))
            )
            for item_id, name in rows.all():
                if item_id is not None:
                    found.setdefault(item_id, []).append(name)
        return found

    async def values_of(self, item_id: int) -> dict[TermKind, list[str]]:
        """Return every value *item_id* holds, by kind, in order."""
        rows = await self.session.exec(
            select(Term.kind, Term.name)
            .join(MediaItemTerm, col(MediaItemTerm.term_id) == col(Term.id))
            .where(col(MediaItemTerm.media_item_id) == item_id)
            .order_by(col(Term.kind), col(MediaItemTerm.position))
        )
        found: dict[TermKind, list[str]] = {}
        for kind, name in rows.all():
            found.setdefault(TermKind(kind), []).append(name)
        return found

    async def prune(self) -> int:
        """Delete the terms no title holds any more; return how many."""
        result = await self.session.exec(
            delete(Term).where(
                ~exists().where(col(MediaItemTerm.term_id) == col(Term.id))
            )
        )
        return result.rowcount or 0
