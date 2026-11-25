"""Media-server collection query helpers."""

lazy from collections.abc import Collection, Iterable, Sequence
lazy from datetime import datetime
lazy from itertools import batched

lazy from sqlalchemy.sql.elements import ColumnElement
lazy from sqlmodel import col, delete, or_, select, tuple_, update
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.added_preset import AddedPreset
lazy from ..db.models.collection_group import CollectionGroup
lazy from ..db.models.collection_rule import CollectionRule
lazy from ..db.models.media_collection import (
    CollectionLibrary,
    MediaCollection,
    MediaCollectionMember,
)
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.media_item_copy import MediaItemCopy
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import MediaType, library_parts


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

    async def added_presets(self) -> dict[str, AddedPreset]:
        """Every preset added here, by its ID."""
        rows = (await self.session.exec(select(AddedPreset))).all()
        return {row.id: row for row in rows}

    async def preset_collections(self, preset_id: str) -> dict[str, int]:
        """The collections a preset added, by their item in it, casefolded."""
        rows = await self.session.exec(
            select(MediaCollection.id, MediaCollection.preset_item).where(
                col(MediaCollection.preset_id) == preset_id
            )
        )
        return {item.casefold(): row_id or 0 for row_id, item in rows if item}

    async def preset_groups(self, preset_id: str) -> dict[str, str]:
        """The groups a preset added, their names here by their item in it."""
        rows = await self.session.exec(
            select(CollectionGroup.name, CollectionGroup.preset_item).where(
                col(CollectionGroup.preset_id) == preset_id
            )
        )
        return {item.casefold(): name for name, item in rows if item}

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

    async def holding(
        self, copies: Collection[tuple[int, str]], *, besides: int
    ) -> list[MediaCollection]:
        """The collections besides *besides* that hold any of these server copies."""
        if not copies:
            return []
        return list(
            (
                await self.session.exec(
                    select(MediaCollection)
                    .join(
                        CollectionLibrary,
                        col(CollectionLibrary.collection_id) == col(MediaCollection.id),
                    )
                    .where(
                        col(MediaCollection.id) != besides,
                        tuple_(
                            col(CollectionLibrary.server_id),
                            col(CollectionLibrary.server_item_id),
                        ).in_(list(copies)),
                    )
                    .distinct()
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

    async def mark_matched(self, collection_ids: set[int], when: datetime) -> None:
        """Stamp ``last_matched_at`` on many collections with one statement."""
        if not collection_ids:
            return
        await self.session.exec(
            update(MediaCollection)
            .where(col(MediaCollection.id).in_(collection_ids))
            .values(last_matched_at=when)
        )

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
    ) -> MediaCollection | None:
        """Record that servers no longer hold these copies, or any of them.

        *copies* names each by ``(server, server collection ID)``. The
        collection keeps its row and the members of the copies that remain.
        """
        row = await self.get(collection_id)
        if row is None:
            return None
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
        return row

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
