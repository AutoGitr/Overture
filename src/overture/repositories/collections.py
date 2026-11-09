"""Media-server collection query helpers."""

lazy import asyncio
lazy from collections.abc import Collection, Iterable, Mapping, Sequence
lazy from dataclasses import dataclass, field
lazy from datetime import datetime
lazy from itertools import batched
lazy from typing import Any, NamedTuple, cast

lazy from sqlalchemy.sql.elements import ColumnElement
lazy from sqlmodel import col, delete, func, select, update
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
lazy from ..db.models.term import MediaItemTerm, Term
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import MediaType, ServerType, TermKind


class CollectionItem(NamedTuple):
    """What collection rules read of a stored title.

    A whole library is read for each rule, so this holds plain column values
    rather than an entity per title.
    """

    id: int
    media_type: MediaType
    title: str
    sort_title: str | None
    library_id: str | None
    server_item_id: str | None
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

#: The stored columns of a :class:`CollectionItem`, in its field order.
_ITEM_COLUMNS = [
    col(getattr(MediaItem, name)) for name in CollectionItem._fields if name != "terms"
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
    return cast("Select[Any]", select(*_ITEM_COLUMNS))


def _in_library(media_type: MediaType, library_id: str) -> list[ColumnElement[bool]]:
    """Match the active server items of one library."""
    return [
        col(MediaItem.media_type) == media_type,
        col(MediaItem.library_id) == library_id,
        col(MediaItem.server_removed_at).is_(None),
        col(MediaItem.server_item_id).is_not(None),
    ]


class CollectionRepository:
    """Centralize media-server collection persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def groups(self, server_type: ServerType) -> list[CollectionGroup]:
        """Return the server's groups."""
        return list(
            (
                await self.session.exec(
                    select(CollectionGroup).where(
                        col(CollectionGroup.server_type) == server_type
                    )
                )
            ).all()
        )

    async def group(
        self, server_type: ServerType, name: str | None
    ) -> CollectionGroup | None:
        """Return the server's group named *name*; none for no name."""
        if not name:
            return None
        return (
            await self.session.exec(
                select(CollectionGroup).where(
                    col(CollectionGroup.server_type) == server_type,
                    col(CollectionGroup.name) == name,
                )
            )
        ).first()

    async def ensure_group(self, server_type: ServerType, name: str) -> CollectionGroup:
        """Return the server's group named *name*, added without defaults if new."""
        group = await self.group(server_type, name)
        if group is None:
            group = CollectionGroup(server_type=server_type, name=name)
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
        self, server_type: ServerType, server_item_id: str
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
                    col(MediaCollection.server_type) == server_type,
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

        Asset runs leave collections Overture does not manage as they are.
        """
        stmt = select(MediaCollection).where(
            col(MediaCollection.id) > after,
            col(MediaCollection.last_synced_at).is_not(None),
            col(MediaCollection.id).in_(select(CollectionRule.collection_id)),
        )
        if collection_ids is not None:
            stmt = stmt.where(col(MediaCollection.id).in_(collection_ids))
        if collection_groups is not None:
            stmt = stmt.join(
                CollectionGroup,
                col(MediaCollection.group_id) == col(CollectionGroup.id),
            ).where(col(CollectionGroup.name).in_(collection_groups))
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
        """Return the visible stored items a collection holds."""
        stmt = (
            _select_items()
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
            CollectionItem._make((*row, {}))
            for row in (await self.session.exec(stmt)).all()
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
        server_ids: Collection[str] | None = None,
    ) -> None:
        """Record that the server no longer holds these copies, or any of them.

        The collection keeps its row and the members of the copies that remain.
        """
        row = await self.get(collection_id)
        if row is None:
            return
        gone = {
            part.library_id
            for part in row.libraries
            if part.server_item_id
            and (server_ids is None or part.server_item_id in server_ids)
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
                    col(MediaItem.library_id).not_in(gone),
                )
                .order_by(col(MediaCollectionMember.position))
            )
        ).all()
        row.child_count = len(kept)
        row.updated_at = timestamp
        self.session.add(row)
        await self.replace_members(collection_id, [i for i in kept if i is not None])

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
        self, server_ids: Collection[str]
    ) -> dict[str, int]:
        """Return Overture item IDs by media-server item ID."""
        found: dict[str, int] = {}
        for batch in batched(server_ids, CHUNK_SIZE, strict=False):
            rows = await self.session.exec(
                select(MediaItem.server_item_id, MediaItem.id).where(
                    col(MediaItem.server_item_id).in_(batch),
                    col(MediaItem.server_removed_at).is_(None),
                )
            )
            found.update(
                {
                    server_id: item_id
                    for server_id, item_id in rows.all()
                    if server_id is not None and item_id is not None
                }
            )
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
            if kind not in selection.kinds
        ]
        if selection.kinds:
            reads.append(col(MediaItemTerm.kind).in_(selection.kinds))
        found: dict[int, dict[TermKind, list[str]]] = {}
        for read in reads:
            rows = await self.session.exec(
                select(
                    col(MediaItemTerm.media_item_id), col(MediaItemTerm.kind), Term.name
                )
                .join(MediaItem, col(MediaItem.id) == col(MediaItemTerm.media_item_id))
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

    async def term_counts(
        self, media_type: MediaType, library_id: str, kind: TermKind
    ) -> dict[str, int]:
        """How many of a library's items hold each value of *kind*."""
        rows = await self.session.exec(
            select(Term.name, func.count())
            .select_from(MediaItemTerm)
            .join(MediaItem, col(MediaItem.id) == col(MediaItemTerm.media_item_id))
            .join(Term, col(Term.id) == col(MediaItemTerm.term_id))
            .where(
                *_in_library(media_type, library_id), col(MediaItemTerm.kind) == kind
            )
            .group_by(col(Term.id))
        )
        return dict(rows.all())

    async def titles_by_item(
        self, library_id: str, excluding: int | None = None
    ) -> dict[int, list[str]]:
        """The titles of the listed collections each item of a library belongs to.

        The collection *excluding* names is left out.
        """
        stmt = (
            select(col(MediaCollectionMember.media_item_id), col(MediaCollection.title))
            .join(
                MediaCollection,
                col(MediaCollection.id) == col(MediaCollectionMember.collection_id),
            )
            .join(
                MediaItem, col(MediaItem.id) == col(MediaCollectionMember.media_item_id)
            )
            .where(
                col(MediaItem.library_id) == library_id,
                col(MediaCollection.last_synced_at).is_not(None),
            )
        )
        if excluding is not None:
            stmt = stmt.where(col(MediaCollection.id) != excluding)
        titles: dict[int, list[str]] = {}
        for item_id, title in await self.session.exec(stmt):
            titles.setdefault(item_id, []).append(title)
        return titles

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
