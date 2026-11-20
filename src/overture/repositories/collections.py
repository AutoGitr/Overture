"""Media-server collection query helpers."""

lazy import asyncio
lazy from collections.abc import Collection, Iterable, Mapping, Sequence
lazy from dataclasses import dataclass, field
lazy from datetime import datetime
lazy from itertools import batched
lazy from typing import Any, NamedTuple, cast

lazy from sqlalchemy.sql.elements import ColumnElement
lazy from sqlmodel import and_, col, delete, func, or_, select, update
lazy from sqlmodel.ext.asyncio.session import AsyncSession
lazy from sqlmodel.sql.expression import Select

lazy from ..db.models.collection_group import CollectionGroup
lazy from ..db.models.collection_rule import CollectionRule
lazy from ..db.models.media_collection import (
    CollectionLibrary,
    MediaCollection,
    MediaCollectionMember,
)
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.media_item_copy import MediaItemCopy
lazy from ..db.models.term import MediaItemTerm, Term
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import MediaType, TermKind, library_parts


class CollectionItem(NamedTuple):
    """What collection rules read of a stored title in one library.

    A whole library is read for each rule, so this holds plain column values
    rather than an entity per title. The facts its server keeps for its own
    copy (its ID, play state, rating, when it was added and its labels) are
    that copy's; the rest describe the title.
    """

    id: int
    media_type: MediaType
    title: str
    sort_title: str | None
    library_id: str
    server_item_id: str
    tmdb_id: int | None
    tvdb_id: int | None
    imdb_id: str | None
    tmdb_collection_id: int | None
    tmdb_checked_id: int | None
    year: int | None
    folder_path: str | None
    studio: str | None
    content_rating: str | None
    edition: str | None
    resolution: str | None
    critic_rating: float | None
    audience_rating: float | None
    user_rating: float | None
    duration_seconds: int | None
    plays: int | None
    last_played_at: datetime | None
    unplayed: bool | None
    in_progress: bool | None
    release_date: str | None
    versions: int | None
    original_language: str | None
    tmdb_rating: float | None
    tmdb_votes: int | None
    show_status: str | None
    last_aired: str | None
    server_added_at: datetime | None
    #: The values read for it, by kind; see :class:`TermSelection`.
    terms: Mapping[TermKind, Sequence[str]]

    def values(self, kind: TermKind) -> Sequence[str]:
        """Its values of *kind*, which must have been read."""
        return self.terms[kind]


#: Values converted between letting other requests run, for reads of whole kinds.
_ROWS_PER_TURN = 10_000

#: The fields of a :class:`CollectionItem` each server keeps for its own copy.
_COPY_COLUMNS = {
    "library_id": "library_id",
    "server_item_id": "server_item_id",
    "user_rating": "user_rating",
    "plays": "plays",
    "last_played_at": "last_played_at",
    "unplayed": "unplayed",
    "in_progress": "in_progress",
    "server_added_at": "added_at",
}

#: The copy's fields a title outside every library of a collection lacks.
_COPY_KEYS = frozenset({"library_id", "server_item_id"})

#: The stored columns of a :class:`CollectionItem`, in its field order.
_ITEM_COLUMNS = [
    col(getattr(MediaItemCopy, _COPY_COLUMNS[name]))
    if name in _COPY_COLUMNS
    else col(getattr(MediaItem, name))
    for name in CollectionItem._fields
    if name != "terms"
]


@dataclass(slots=True, frozen=True)
class TermSelection:
    """Which of a library's values to read with its items.

    Only what evaluation looks at is read: titles hold dozens of values each,
    and a rule naming one actor tests for that actor alone.
    """

    #: Kinds read completely.
    kinds: frozenset[TermKind] = frozenset()
    #: Kinds of which only these case-folded values are read.
    matching: Mapping[TermKind, frozenset[str]] = field(
        default_factory=dict[TermKind, frozenset[str]]
    )

    @property
    def read(self) -> frozenset[TermKind]:
        """Every kind an item read this way can answer for."""
        return self.kinds | self.matching.keys()


def _select_items() -> Select[Any]:
    return cast("Select[Any]", select(*_ITEM_COLUMNS)).join(
        MediaItemCopy, col(MediaItemCopy.media_item_id) == col(MediaItem.id)
    )


def _in_library(media_type: MediaType, library_id: str) -> list[ColumnElement[bool]]:
    """Match the listed copies of one library, joined to their titles."""
    return [
        col(MediaItemCopy.media_type) == media_type,
        col(MediaItemCopy.library_id) == library_id,
        col(MediaItemCopy.removed_at).is_(None),
        col(MediaItem.server_removed_at).is_(None),
    ]


def _labels(labels: Sequence[str], wanted: frozenset[str] | None) -> list[str]:
    """A copy's labels, only those *wanted* case-folded when it says."""
    return [label for label in labels if wanted is None or label.casefold() in wanted]


class CollectionRepository:
    """Centralize media-server collection persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def groups(self) -> list[CollectionGroup]:
        """Return every group."""
        return list((await self.session.exec(select(CollectionGroup))).all())

    async def group(self, name: str | None) -> CollectionGroup | None:
        """Return the group named *name*; none for no name."""
        if not name:
            return None
        return (
            await self.session.exec(
                select(CollectionGroup).where(col(CollectionGroup.name) == name)
            )
        ).first()

    async def ensure_group(self, name: str) -> CollectionGroup:
        """Return the group named *name*, added without defaults if new."""
        group = await self.group(name)
        if group is None:
            group = CollectionGroup(name=name)
            self.session.add(group)
            await self.session.flush()
        return group

    async def get(self, collection_id: int) -> MediaCollection | None:
        """Return a collection row, listed or not."""
        return (
            await self.session.exec(
                select(MediaCollection).where(col(MediaCollection.id) == collection_id)
            )
        ).first()

    async def group_members(self, group: CollectionGroup) -> list[MediaCollection]:
        """Include unlisted collections so group operations leave no orphaned data."""
        return list(
            (
                await self.session.exec(
                    select(MediaCollection)
                    .where(col(MediaCollection.group_id) == group.id)
                    .order_by(col(MediaCollection.id))
                )
            ).all()
        )

    async def find_server(
        self, server_id: int, server_item_id: str
    ) -> MediaCollection | None:
        """Return the collection one of whose server copies this is."""
        return (
            await self.session.exec(
                select(MediaCollection)
                .join(
                    CollectionLibrary,
                    col(CollectionLibrary.collection_id) == col(MediaCollection.id),
                )
                .where(
                    col(CollectionLibrary.server_id) == server_id,
                    col(CollectionLibrary.server_item_id) == server_item_id,
                )
            )
        ).first()

    async def get_listed(self, collection_id: int) -> MediaCollection | None:
        """Return a collection the last sync listed."""
        row = await self.get(collection_id)
        return row if row is not None and row.last_synced_at is not None else None

    async def list_listed(self) -> list[MediaCollection]:
        """Return the collections the last sync listed."""
        return list(
            (
                await self.session.exec(
                    select(MediaCollection).where(
                        col(MediaCollection.last_synced_at).is_not(None)
                    )
                )
            ).all()
        )

    async def list_all(self) -> list[MediaCollection]:
        """Return every collection row, listed or not."""
        return list((await self.session.exec(select(MediaCollection))).all())

    async def member_ids(self, collection_id: int) -> list[int]:
        """Return the IDs of the stored items a collection holds."""
        stmt = (
            select(col(MediaCollectionMember.media_item_id))
            .where(col(MediaCollectionMember.collection_id) == collection_id)
            .order_by(
                col(MediaCollectionMember.position),
                col(MediaCollectionMember.media_item_id),
            )
        )
        return list((await self.session.exec(stmt)).all())

    async def bulk_targets(
        self,
        *,
        after: int = 0,
        collection_ids: list[int] | None = None,
        collection_groups: list[str] | None = None,
        include_unmonitored: bool = False,
        limit: int = CHUNK_SIZE,
    ) -> list[MediaCollection]:
        """Return a bounded page of listed, managed collections in the scope.

        The scope is *collection_ids* and the collections of
        *collection_groups*, or every collection when neither is given. Asset
        runs leave collections Overture does not manage as they are.
        """
        stmt = select(MediaCollection).where(
            col(MediaCollection.id) > after,
            col(MediaCollection.last_synced_at).is_not(None),
            col(MediaCollection.id).in_(select(CollectionRule.collection_id)),
        )
        chosen: list[ColumnElement[bool]] = []
        if collection_ids is not None:
            chosen.append(col(MediaCollection.id).in_(collection_ids))
        if collection_groups is not None:
            chosen.append(
                col(MediaCollection.group_id).in_(
                    select(CollectionGroup.id).where(
                        col(CollectionGroup.name).in_(collection_groups)
                    )
                )
            )
        if chosen:
            stmt = stmt.where(or_(*chosen))
        if not include_unmonitored:
            stmt = stmt.where(col(MediaCollection.monitored).is_(True))
        return list(
            (
                await self.session.exec(
                    stmt.order_by(col(MediaCollection.id)).limit(limit)
                )
            ).all()
        )

    async def members(self, collection_id: int) -> list[CollectionItem]:
        """Return the visible stored items a collection holds, in its libraries.

        A title holds one copy in each library, so it comes once for each of
        the collection's libraries it is in, with that copy's facts; a member
        in none of them comes once, without them.
        """
        in_collection = and_(
            col(MediaItemCopy.media_item_id) == col(MediaItem.id),
            col(MediaItemCopy.removed_at).is_(None),
            col(MediaItemCopy.library_id).in_(
                select(CollectionLibrary.library_id).where(
                    col(CollectionLibrary.collection_id) == collection_id
                )
            ),
        )
        stmt = (
            cast("Select[Any]", select(*_ITEM_COLUMNS))
            .outerjoin(MediaItemCopy, in_collection)
            .join(
                MediaCollectionMember,
                col(MediaCollectionMember.media_item_id) == col(MediaItem.id),
            )
            .where(
                col(MediaCollectionMember.collection_id) == collection_id,
                col(MediaItem.server_removed_at).is_(None),
            )
            .order_by(
                col(MediaCollectionMember.position),
                col(MediaCollectionMember.media_item_id),
            )
        )
        return [
            CollectionItem._make(
                (
                    *(
                        value if value is not None or name not in _COPY_KEYS else ""
                        for name, value in zip(
                            CollectionItem._fields, row, strict=False
                        )
                    ),
                    {},
                )
            )
            for row in (await self.session.exec(stmt)).all()
        ]

    async def member_tmdb_titles(
        self, collection_id: int, limit: int
    ) -> list[tuple[MediaType, int]]:
        """Return the TMDB identity of up to *limit* visible members, in order."""
        rows = await self.session.exec(
            select(col(MediaItem.media_type), col(MediaItem.tmdb_id))
            .join(
                MediaCollectionMember,
                col(MediaCollectionMember.media_item_id) == col(MediaItem.id),
            )
            .where(
                col(MediaCollectionMember.collection_id) == collection_id,
                col(MediaItem.server_removed_at).is_(None),
                col(MediaItem.tmdb_id).is_not(None),
            )
            .order_by(
                col(MediaCollectionMember.position),
                col(MediaCollectionMember.media_item_id),
            )
            .limit(limit)
        )
        return [
            (MediaType(media_type), tmdb_id)
            for media_type, tmdb_id in rows
            if tmdb_id is not None
        ]

    async def members_of(self, collection_ids: Collection[int]) -> list[CollectionItem]:
        """Return the visible stored items these collections hold, each once."""
        found: dict[int, CollectionItem] = {}
        for batch in batched(collection_ids, CHUNK_SIZE, strict=False):
            rows = await self.session.exec(
                _select_items()
                .join(
                    MediaCollectionMember,
                    col(MediaCollectionMember.media_item_id) == col(MediaItem.id),
                )
                .where(
                    col(MediaCollectionMember.collection_id).in_(batch),
                    col(MediaItem.server_removed_at).is_(None),
                )
            )
            found.update(
                {row[0]: CollectionItem._make((*row, {})) for row in rows.all()}
            )
        return list(found.values())

    async def collection_ids_by_item(
        self, item_ids: Collection[int]
    ) -> dict[int, list[int]]:
        """Link movies to a listed collection matching their TMDB franchise."""
        found: dict[int, list[int]] = {}
        for batch in batched(item_ids, CHUNK_SIZE, strict=False):
            stmt = (
                select(
                    col(MediaCollectionMember.media_item_id),
                    MediaCollection.id,
                )
                .join(
                    MediaCollection,
                    col(MediaCollection.id) == col(MediaCollectionMember.collection_id),
                )
                .join(
                    MediaItem,
                    col(MediaItem.id) == col(MediaCollectionMember.media_item_id),
                )
                .where(
                    col(MediaCollectionMember.media_item_id).in_(batch),
                    col(MediaCollection.last_synced_at).is_not(None),
                    col(MediaCollection.tmdb_collection_id)
                    == col(MediaItem.tmdb_collection_id),
                )
                .order_by(col(MediaCollection.id))
            )
            for item_id, collection_id in await self.session.exec(stmt):
                if collection_id is not None:
                    found.setdefault(item_id, []).append(collection_id)
        return found

    async def replace_members(
        self, collection_id: int, media_item_ids: Collection[int]
    ) -> None:
        """Make *media_item_ids* the collection's members."""
        await self.session.exec(
            delete(MediaCollectionMember).where(
                col(MediaCollectionMember.collection_id) == collection_id
            )
        )
        self.session.add_all(
            MediaCollectionMember(
                collection_id=collection_id, media_item_id=item_id, position=position
            )
            for position, item_id in enumerate(media_item_ids)
        )

    async def clear_server_copies(
        self,
        collection_id: int,
        timestamp: datetime,
        copies: Collection[tuple[int, str]] | None = None,
    ) -> None:
        """Record that servers no longer hold these copies, or any of them.

        *copies* names each by ``(server, server collection ID)``. The
        collection keeps its row and the members of the copies that remain.
        """
        row = await self.get(collection_id)
        if row is None:
            return
        gone = {
            part.library_id
            for part in row.libraries
            if part.server_item_id
            and (copies is None or (part.server_id, part.server_item_id) in copies)
        }
        for part in row.libraries:
            if part.library_id in gone:
                part.server_item_id = None
                self.session.add(part)
        kept = (
            await self.session.exec(
                select(col(MediaItem.id))
                .join(
                    MediaCollectionMember,
                    col(MediaCollectionMember.media_item_id) == col(MediaItem.id),
                )
                .where(
                    col(MediaCollectionMember.collection_id) == collection_id,
                    col(MediaItem.id).in_(
                        select(MediaItemCopy.media_item_id).where(
                            col(MediaItemCopy.library_id).in_(
                                {part.library_id for part in row.libraries} - gone
                            )
                        )
                    ),
                )
                .order_by(col(MediaCollectionMember.position))
            )
        ).all()
        row.child_count = len(kept)
        row.updated_at = timestamp
        self.session.add(row)
        await self.replace_members(collection_id, [i for i in kept if i is not None])

    async def move_library(
        self, library_id: str, media_type: MediaType, replacement: str
    ) -> None:
        """Make collections and sets that hold a library hold its replacement.

        A collection already holding the replacement keeps that part alone.
        """
        parts = (
            await self.session.exec(
                select(CollectionLibrary).where(
                    col(CollectionLibrary.library_id) == library_id,
                    col(CollectionLibrary.media_type) == media_type,
                )
            )
        ).all()
        holding = set(
            (
                await self.session.exec(
                    select(CollectionLibrary.collection_id).where(
                        col(CollectionLibrary.library_id) == replacement,
                        col(CollectionLibrary.media_type) == media_type,
                    )
                )
            ).all()
        )
        server = library_parts(replacement)
        for part in parts:
            if part.collection_id in holding:
                await self.session.delete(part)
                continue
            part.library_id = replacement
            if server is not None and server[0] != part.server_id:
                # Another server makes its own copy at its next sync.
                part.server_id = server[0]
                part.server_item_id = None
                part.server_path = None
            self.session.add(part)
        for group in await self.groups():
            ids: list[str] = (group.generator or {}).get("library_ids") or []
            if library_id in ids:
                moved = [replacement if each == library_id else each for each in ids]
                group.generator = {
                    **(group.generator or {}),
                    "library_ids": list(dict.fromkeys(moved)),
                }
                self.session.add(group)

    async def forget_unmanaged_on(self, server_ids: Collection[int]) -> None:
        """Forget servers' copies of collections Overture does not manage.

        A collection left with no copy anywhere is forgotten with them.
        """
        unmanaged = ~col(CollectionLibrary.collection_id).in_(
            select(CollectionRule.collection_id)
        )
        emptied = set(
            (
                await self.session.exec(
                    select(CollectionLibrary.collection_id).where(
                        col(CollectionLibrary.server_id).in_(server_ids), unmanaged
                    )
                )
            ).all()
        )
        await self.session.exec(
            delete(CollectionLibrary).where(
                col(CollectionLibrary.server_id).in_(server_ids), unmanaged
            )
        )
        remaining = set(
            (
                await self.session.exec(
                    select(CollectionLibrary.collection_id).where(
                        col(CollectionLibrary.collection_id).in_(emptied)
                    )
                )
            ).all()
        )
        await self.delete_ids(sorted(emptied - remaining))

    async def delete_ids(self, collection_ids: Sequence[int]) -> None:
        """Delete collections; their members go with them."""
        for batch in batched(collection_ids, CHUNK_SIZE, strict=False):
            await self.session.exec(
                delete(MediaCollection).where(col(MediaCollection.id).in_(batch))
            )

    async def bulk_set_monitored(
        self,
        collection_ids: list[int],
        monitored: bool,
        *,
        timestamp: datetime,
    ) -> int:
        """Set the monitored flag of listed, managed collections; count the matches."""
        updated = 0
        for batch in batched(set(collection_ids), CHUNK_SIZE, strict=False):
            result = await self.session.exec(
                update(MediaCollection)
                .where(
                    col(MediaCollection.id).in_(batch),
                    col(MediaCollection.last_synced_at).is_not(None),
                    # Collections Overture does not manage stay as they are.
                    col(MediaCollection.id).in_(select(CollectionRule.collection_id)),
                )
                .values(monitored=monitored, updated_at=timestamp)
            )
            updated += result.rowcount or 0
        return updated

    async def item_ids_by_server_id(
        self, server_id: int, server_item_ids: Collection[str]
    ) -> dict[str, int]:
        """Return Overture item IDs by one server's item IDs."""
        found: dict[str, int] = {}
        for batch in batched(server_item_ids, CHUNK_SIZE, strict=False):
            rows = await self.session.exec(
                select(MediaItemCopy.server_item_id, MediaItemCopy.media_item_id)
                .join(MediaItem, col(MediaItem.id) == col(MediaItemCopy.media_item_id))
                .where(
                    col(MediaItemCopy.server_id) == server_id,
                    col(MediaItemCopy.server_item_id).in_(batch),
                    col(MediaItemCopy.removed_at).is_(None),
                    col(MediaItem.server_removed_at).is_(None),
                )
            )
            found.update(rows.all())
        return found

    async def library_items(
        self,
        media_type: MediaType,
        library_id: str,
        terms: TermSelection | None = None,
    ) -> list[CollectionItem]:
        """Return active server items in one library, with deterministic order.

        Only the values *terms* selects are read; asking for another kind raises.
        """
        selection = terms or TermSelection()
        library = _in_library(media_type, library_id)
        values = await self._selected_terms(library, selection)
        if TermKind.LABEL in selection.read:
            await self._read_labels(library, selection, values)
        blank = dict.fromkeys(selection.read, ())
        rows = await self.session.exec(
            _select_items().where(*library).order_by(col(MediaItem.id))
        )
        return [
            CollectionItem._make(
                (*row, {**blank, **held} if (held := values.get(row[0])) else blank)
            )
            for row in rows.all()
        ]

    async def _selected_terms(
        self, library: Iterable[ColumnElement[bool]], selection: TermSelection
    ) -> dict[int, dict[TermKind, list[str]]]:
        """Read the selected values of a library's items, by item and kind."""
        reads: list[ColumnElement[bool]] = [
            col(MediaItemTerm.term_id).in_(
                select(Term.id).where(
                    col(Term.kind) == kind, func.casefold(Term.name).in_(values)
                )
            )
            for kind, values in selection.matching.items()
            if kind not in selection.kinds and kind is not TermKind.LABEL
        ]
        if kinds := selection.kinds - {TermKind.LABEL}:
            reads.append(col(MediaItemTerm.kind).in_(kinds))
        found: dict[int, dict[TermKind, list[str]]] = {}
        for read in reads:
            rows = await self.session.exec(
                select(
                    col(MediaItemTerm.media_item_id), col(MediaItemTerm.kind), Term.name
                )
                .join(MediaItem, col(MediaItem.id) == col(MediaItemTerm.media_item_id))
                .join(
                    MediaItemCopy, col(MediaItemCopy.media_item_id) == col(MediaItem.id)
                )
                .join(Term, col(Term.id) == col(MediaItemTerm.term_id))
                .where(*library, read)
                .order_by(
                    col(MediaItemTerm.media_item_id),
                    col(MediaItemTerm.kind),
                    col(MediaItemTerm.position),
                )
            )
            for part in rows.partitions(_ROWS_PER_TURN):
                for item_id, kind, name in part:
                    found.setdefault(item_id, {}).setdefault(kind, []).append(name)
                await asyncio.sleep(0)
        return found

    async def _read_labels(
        self,
        library: Iterable[ColumnElement[bool]],
        selection: TermSelection,
        found: dict[int, dict[TermKind, list[str]]],
    ) -> None:
        """Read the selected labels each copy holds on its own server."""
        wanted = (
            None
            if TermKind.LABEL in selection.kinds
            else selection.matching[TermKind.LABEL]
        )
        rows = await self.session.exec(
            select(col(MediaItemCopy.media_item_id), col(MediaItemCopy.labels))
            .join(MediaItem, col(MediaItem.id) == col(MediaItemCopy.media_item_id))
            .where(*library)
        )
        for item_id, labels in rows.all():
            if held := _labels(labels, wanted):
                found.setdefault(item_id, {})[TermKind.LABEL] = held

    async def term_counts(
        self, media_type: MediaType, library_id: str, kind: TermKind
    ) -> dict[str, int]:
        """How many of a library's items hold each value of *kind*."""
        if kind is TermKind.LABEL:
            counts: dict[str, int] = {}
            rows = await self.session.exec(
                select(col(MediaItemCopy.labels))
                .join(MediaItem, col(MediaItem.id) == col(MediaItemCopy.media_item_id))
                .where(*_in_library(media_type, library_id))
            )
            for labels in rows.all():
                for label in dict.fromkeys(labels):
                    counts[label] = counts.get(label, 0) + 1
            return counts
        rows = await self.session.exec(
            select(Term.name, func.count())
            .select_from(MediaItemTerm)
            .join(MediaItem, col(MediaItem.id) == col(MediaItemTerm.media_item_id))
            .join(MediaItemCopy, col(MediaItemCopy.media_item_id) == col(MediaItem.id))
            .join(Term, col(Term.id) == col(MediaItemTerm.term_id))
            .where(
                *_in_library(media_type, library_id), col(MediaItemTerm.kind) == kind
            )
            .group_by(col(Term.id))
        )
        return dict(rows.all())

    async def memberships_by_item(
        self, library_id: str, excluding: int | None = None
    ) -> dict[int, list[str]]:
        """The listed collections each item of a library belongs to, by ID.

        The IDs are strings, as criteria hold them. The collection *excluding*
        names is left out.
        """
        stmt = (
            select(
                col(MediaCollectionMember.media_item_id),
                col(MediaCollectionMember.collection_id),
            )
            .join(
                MediaCollection,
                col(MediaCollection.id) == col(MediaCollectionMember.collection_id),
            )
            .join(
                MediaItemCopy,
                col(MediaItemCopy.media_item_id)
                == col(MediaCollectionMember.media_item_id),
            )
            .where(
                col(MediaItemCopy.library_id) == library_id,
                col(MediaCollection.last_synced_at).is_not(None),
            )
        )
        if excluding is not None:
            stmt = stmt.where(col(MediaCollection.id) != excluding)
        memberships: dict[int, list[str]] = {}
        for item_id, collection_id in await self.session.exec(stmt):
            memberships.setdefault(item_id, []).append(str(collection_id))
        return memberships

    async def titles_of(self, collection_ids: Iterable[int]) -> dict[int, str]:
        """The titles of the collections *collection_ids* names that exist."""
        ids = set(collection_ids)
        if not ids:
            return {}
        rows = await self.session.exec(
            select(col(MediaCollection.id), col(MediaCollection.title)).where(
                col(MediaCollection.id).in_(ids)
            )
        )
        return {collection_id: title for collection_id, title in rows if collection_id}

    async def server_copies(self, server_id: int) -> dict[str, int]:
        """The collections with a copy on a server, by the copy's server ID."""
        rows = await self.session.exec(
            select(
                col(CollectionLibrary.server_item_id),
                col(CollectionLibrary.collection_id),
            ).where(
                col(CollectionLibrary.server_id) == server_id,
                col(CollectionLibrary.server_item_id).is_not(None),
            )
        )
        return {
            server_item_id: collection_id
            for server_item_id, collection_id in rows
            if server_item_id
        }

    async def managed_ids(self, collection_ids: list[int]) -> set[int]:
        """The given collections Overture manages, which are those with a rule."""
        managed: set[int] = set()
        for batch in batched(set(collection_ids), CHUNK_SIZE, strict=False):
            managed.update(
                (
                    await self.session.exec(
                        select(CollectionRule.collection_id).where(
                            col(CollectionRule.collection_id).in_(batch)
                        )
                    )
                ).all()
            )
        return managed

    async def rule(self, collection_id: int) -> CollectionRule | None:
        """Return the collection's sole rule."""
        return (
            await self.session.exec(
                select(CollectionRule).where(
                    col(CollectionRule.collection_id) == collection_id
                )
            )
        ).first()
