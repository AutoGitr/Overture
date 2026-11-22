"""Collection item and term projection query helpers."""

lazy import asyncio
lazy from collections.abc import Collection, Iterable, Mapping, Sequence
lazy from dataclasses import dataclass, field
lazy from datetime import datetime
lazy from itertools import batched
lazy from typing import Any, NamedTuple, cast

lazy from sqlalchemy.sql.elements import ColumnElement
lazy from sqlmodel import and_, col, func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession
lazy from sqlmodel.sql.expression import Select

lazy from ..db.models.media_collection import (
    CollectionLibrary,
    MediaCollection,
    MediaCollectionMember,
)
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.media_item_copy import MediaItemCopy
lazy from ..db.models.term import MediaItemTerm, Term
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import MediaType, TermKind


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


def _named_terms[*Ts](stmt: Select[*Ts]) -> Select[*Ts]:
    """*stmt* over titles' values, with each title's copies and value names."""
    return (
        stmt.select_from(MediaItemTerm)
        .join(MediaItem, col(MediaItem.id) == col(MediaItemTerm.media_item_id))
        .join(MediaItemCopy, col(MediaItemCopy.media_item_id) == col(MediaItem.id))
        .join(Term, col(Term.id) == col(MediaItemTerm.term_id))
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


class CollectionItemRepository:
    """Read-only projection queries for collection members, library items, and terms."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def members(self, collection_id: int) -> list[CollectionItem]:
        """Return the visible stored items a collection holds, in its libraries."""
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
        """Return active server items in one library, with deterministic order."""
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
                _named_terms(
                    select(
                        col(MediaItemTerm.media_item_id),
                        col(MediaItemTerm.kind),
                        Term.name,
                    )
                )
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
            _named_terms(select(Term.name, func.count()))
            .where(
                *_in_library(media_type, library_id), col(MediaItemTerm.kind) == kind
            )
            .group_by(col(Term.id))
        )
        return dict(rows.all())

    async def memberships_by_item(
        self, library_id: str, excluding: int | None = None
    ) -> dict[int, list[str]]:
        """The listed collections each item of a library belongs to, by ID."""
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
