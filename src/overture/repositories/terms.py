"""The metadata values titles hold, such as genres and people."""

lazy from collections.abc import Collection, Iterable, Mapping
lazy from itertools import batched

lazy from sqlmodel import col, delete, exists, insert, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.term import MediaItemTerm, Term
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import TermKind


class TermRepository:
    """Give titles their values and read them back by title."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def assign(
        self, item_id: int, values: Mapping[TermKind, Iterable[str]]
    ) -> frozenset[TermKind]:
        """Give a stored title exactly these values of each kind named.

        Kinds not named stay. Returns the kinds that changed.
        """
        return (await self.assign_many({item_id: values})).get(item_id, frozenset())

    async def assign_many(
        self, values: Mapping[int, Mapping[TermKind, Iterable[str]]]
    ) -> dict[int, frozenset[TermKind]]:
        """Give at most a chunk of stored titles their values; return what changed."""
        wanted = {
            (item_id, kind): list(dict.fromkeys(name for name in names if name))
            for item_id, kinds in values.items()
            for kind, names in kinds.items()
        }
        held = await self._held(values.keys(), {kind for _, kind in wanted})
        stale = {
            key: names for key, names in wanted.items() if held.get(key, []) != names
        }
        if stale:
            await self._replace(stale)
        changed: dict[int, set[TermKind]] = {}
        for item_id, kind in stale:
            changed.setdefault(item_id, set()).add(kind)
        return {item_id: frozenset(kinds) for item_id, kinds in changed.items()}

    async def _held(
        self, item_ids: Collection[int], kinds: Collection[TermKind]
    ) -> dict[tuple[int, TermKind], list[str]]:
        rows = await self.session.exec(
            select(col(MediaItemTerm.media_item_id), col(MediaItemTerm.kind), Term.name)
            .join(Term, col(Term.id) == col(MediaItemTerm.term_id))
            .where(
                col(MediaItemTerm.media_item_id).in_(item_ids),
                col(MediaItemTerm.kind).in_(kinds),
            )
            .order_by(
                col(MediaItemTerm.media_item_id),
                col(MediaItemTerm.kind),
                col(MediaItemTerm.position),
            )
        )
        held: dict[tuple[int, TermKind], list[str]] = {}
        for item_id, kind, name in rows.all():
            held.setdefault((item_id, kind), []).append(name)
        return held

    async def _replace(self, stale: Mapping[tuple[int, TermKind], list[str]]) -> None:
        """Rewrite these titles' values of these kinds, keyed by position."""
        ids = await self._term_ids(
            {(kind, name) for (_, kind), names in stale.items() for name in names}
        )
        by_kind: dict[TermKind, list[int]] = {}
        for item_id, kind in stale:
            by_kind.setdefault(kind, []).append(item_id)
        for kind, item_ids in by_kind.items():
            await self.session.exec(
                delete(MediaItemTerm)
                .where(
                    col(MediaItemTerm.kind) == kind,
                    col(MediaItemTerm.media_item_id).in_(item_ids),
                )
                .execution_options(synchronize_session=False)
            )
        links = [
            {
                "media_item_id": item_id,
                "kind": kind,
                "position": position,
                "term_id": ids[kind, name],
            }
            for (item_id, kind), names in stale.items()
            for position, name in enumerate(names)
        ]
        if links:
            await self.session.exec(insert(MediaItemTerm), params=links)

    async def _term_ids(
        self, wanted: Collection[tuple[TermKind, str]]
    ) -> dict[tuple[TermKind, str], int]:
        """Return the IDs of the terms *wanted* names, adding those not stored yet."""
        found = await self._stored_ids(wanted)
        missing = set(wanted) - found.keys()
        if missing:
            await self.session.exec(
                insert(Term),
                params=[{"kind": kind, "name": name} for kind, name in missing],
            )
            found |= await self._stored_ids(missing)
        return found

    async def _stored_ids(
        self, wanted: Collection[tuple[TermKind, str]]
    ) -> dict[tuple[TermKind, str], int]:
        names: dict[TermKind, list[str]] = {}
        for kind, name in wanted:
            names.setdefault(kind, []).append(name)
        found: dict[tuple[TermKind, str], int] = {}
        for kind, kind_names in names.items():
            for batch in batched(kind_names, CHUNK_SIZE, strict=False):
                rows = await self.session.exec(
                    select(Term.id, Term.name).where(
                        col(Term.kind) == kind, col(Term.name).in_(batch)
                    )
                )
                found.update(
                    {(kind, name): term_id or 0 for term_id, name in rows.all()}
                )
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
                    col(MediaItemTerm.kind) == kind,
                )
                .order_by(col(MediaItemTerm.media_item_id), col(MediaItemTerm.position))
            )
            for item_id, name in rows.all():
                found.setdefault(item_id, []).append(name)
        return found

    async def values_of(self, item_id: int) -> dict[TermKind, list[str]]:
        """Return every value *item_id* holds, by kind, in order."""
        rows = await self.session.exec(
            select(col(MediaItemTerm.kind), Term.name)
            .join(Term, col(Term.id) == col(MediaItemTerm.term_id))
            .where(col(MediaItemTerm.media_item_id) == item_id)
            .order_by(col(MediaItemTerm.kind), col(MediaItemTerm.position))
        )
        found: dict[TermKind, list[str]] = {}
        for kind, name in rows.all():
            found.setdefault(kind, []).append(name)
        return found

    async def prune(self) -> int:
        """Delete the terms no title holds any more; return how many."""
        result = await self.session.exec(
            delete(Term).where(
                ~exists().where(col(MediaItemTerm.term_id) == col(Term.id))
            )
        )
        return result.rowcount or 0
