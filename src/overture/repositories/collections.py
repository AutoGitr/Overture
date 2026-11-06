"""Media-server collection query helpers."""

lazy from collections.abc import Collection, Sequence
lazy from datetime import datetime
lazy from itertools import batched

lazy from sqlmodel import col, delete, select, update
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.collection_group import CollectionGroup
lazy from ..db.models.collection_rule import CollectionRule
lazy from ..db.models.media_collection import (
    CollectionLibrary,
    MediaCollection,
    MediaCollectionMember,
)
lazy from ..db.models.media_item import MediaItem
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import MediaType, ServerType


class CollectionRepository:
    """Centralize media-server collection persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def group_policies(self, server_type: ServerType) -> list[CollectionGroup]:
        """Return the active server's group defaults."""
        return list(
            (
                await self.session.exec(
                    select(CollectionGroup).where(
                        col(CollectionGroup.server_type) == server_type
                    )
                )
            ).all()
        )

    async def group_policy(
        self, server_type: ServerType, name: str | None
    ) -> CollectionGroup | None:
        """Return one group's defaults without conflating ungrouped collections."""
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

    async def get(self, collection_id: int) -> MediaCollection | None:
        """Return a collection row, listed or not."""
        return (
            await self.session.exec(
                select(MediaCollection).where(col(MediaCollection.id) == collection_id)
            )
        ).first()

    async def group_members(
        self, server_type: ServerType, name: str
    ) -> list[MediaCollection]:
        """Include unlisted collections so group operations leave no orphaned data."""
        return list(
            (
                await self.session.exec(
                    select(MediaCollection)
                    .where(
                        col(MediaCollection.server_type) == server_type,
                        col(MediaCollection.collection_group) == name,
                    )
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
            stmt = stmt.where(
                col(MediaCollection.collection_group).in_(collection_groups)
            )
        if not include_unmonitored:
            stmt = stmt.where(col(MediaCollection.monitored).is_(True))
        return list(
            (
                await self.session.exec(
                    stmt.order_by(col(MediaCollection.id)).limit(limit)
                )
            ).all()
        )

    async def members(self, collection_id: int) -> list[MediaItem]:
        """Return the visible stored items a collection holds."""
        stmt = (
            select(MediaItem)
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
        return list((await self.session.exec(stmt)).all())

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
            for item_id, server_id in await self.session.exec(stmt):
                if server_id is not None:
                    found.setdefault(item_id, []).append(server_id)
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
            updated += result.rowcount
        return updated

    async def library_items(
        self, media_type: MediaType, library_id: str
    ) -> list[MediaItem]:
        """Return active server items in one library, with deterministic order."""
        return list(
            (
                await self.session.exec(
                    select(MediaItem)
                    .where(
                        col(MediaItem.media_type) == media_type,
                        col(MediaItem.library_id) == library_id,
                        col(MediaItem.server_removed_at).is_(None),
                        col(MediaItem.server_item_id).is_not(None),
                    )
                    .order_by(col(MediaItem.id))
                )
            ).all()
        )

    async def titles_by_item(self, library_id: str) -> dict[int, list[str]]:
        """The titles of the listed collections each item of a library belongs to."""
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

    async def rules(self) -> list[CollectionRule]:
        """Return every rule in stable order."""
        stmt = select(CollectionRule).order_by(col(CollectionRule.id))
        return list((await self.session.exec(stmt)).all())
