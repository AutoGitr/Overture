"""Media-server collection query helpers."""

lazy from collections.abc import Collection, Sequence
lazy from datetime import datetime
lazy from itertools import batched

lazy from sqlmodel import col, delete, select, update
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.collection_group import CollectionGroup
lazy from ..db.models.collection_preset import CollectionPreset
lazy from ..db.models.collection_rule import CollectionRule
lazy from ..db.models.media_collection import MediaCollection, MediaCollectionMember
lazy from ..db.models.media_item import MediaItem
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import MediaType, ServerType


class CollectionRepository:
    """Centralize media-server collection persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def group_policies(
        self, server_type: ServerType, media_type: MediaType
    ) -> list[CollectionGroup]:
        """Return defaults scoped to the active server and media type."""
        return list(
            (
                await self.session.exec(
                    select(CollectionGroup).where(
                        col(CollectionGroup.server_type) == server_type,
                        col(CollectionGroup.media_type) == media_type,
                    )
                )
            ).all()
        )

    async def group_policy(
        self, server_type: ServerType, media_type: MediaType, name: str | None
    ) -> CollectionGroup | None:
        """Return one group's defaults without conflating ungrouped collections."""
        if not name:
            return None
        return (
            await self.session.exec(
                select(CollectionGroup).where(
                    col(CollectionGroup.server_type) == server_type,
                    col(CollectionGroup.media_type) == media_type,
                    col(CollectionGroup.name) == name,
                )
            )
        ).first()

    async def get(
        self, collection_id: int, media_type: MediaType | None = None
    ) -> MediaCollection | None:
        """Return a collection row, listed or not."""
        stmt = select(MediaCollection).where(col(MediaCollection.id) == collection_id)
        if media_type is not None:
            stmt = stmt.where(col(MediaCollection.media_type) == media_type)
        return (await self.session.exec(stmt)).first()

    async def group_members(
        self, server_type: ServerType, media_type: MediaType, name: str
    ) -> list[MediaCollection]:
        """Include unlisted collections so group operations leave no orphaned data."""
        return list(
            (
                await self.session.exec(
                    select(MediaCollection)
                    .where(
                        col(MediaCollection.server_type) == server_type,
                        col(MediaCollection.media_type) == media_type,
                        col(MediaCollection.collection_group) == name,
                    )
                    .order_by(col(MediaCollection.id))
                )
            ).all()
        )

    async def find_server(
        self, server_type: ServerType, server_item_id: str
    ) -> MediaCollection | None:
        """Return the collection identified by one provider."""
        return (
            await self.session.exec(
                select(MediaCollection).where(
                    col(MediaCollection.server_type) == server_type,
                    col(MediaCollection.server_item_id) == server_item_id,
                )
            )
        ).first()

    async def get_listed(
        self, collection_id: int, media_type: MediaType
    ) -> MediaCollection | None:
        """Return a collection the last sync listed."""
        row = await self.get(collection_id, media_type)
        return row if row is not None and row.last_synced_at is not None else None

    async def list_listed(
        self, media_type: MediaType | None = None
    ) -> list[MediaCollection]:
        """Return the collections the last sync listed."""
        stmt = select(MediaCollection).where(
            col(MediaCollection.last_synced_at).is_not(None)
        )
        if media_type is not None:
            stmt = stmt.where(col(MediaCollection.media_type) == media_type)
        return list((await self.session.exec(stmt)).all())

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
        library_ids: list[str] | None = None,
        include_unmonitored: bool = False,
        limit: int = CHUNK_SIZE,
    ) -> list[MediaCollection]:
        """Return a bounded page of listed collections in the requested scope."""
        stmt = select(MediaCollection).where(
            col(MediaCollection.id) > after,
            col(MediaCollection.last_synced_at).is_not(None),
        )
        if collection_ids is not None:
            stmt = stmt.where(col(MediaCollection.id).in_(collection_ids))
        if library_ids:
            stmt = stmt.where(col(MediaCollection.library_id).in_(library_ids))
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

    async def delete_ids(self, collection_ids: Sequence[int]) -> None:
        """Delete collections; their members go with them."""
        for batch in batched(collection_ids, CHUNK_SIZE, strict=False):
            await self.session.exec(
                delete(MediaCollection).where(col(MediaCollection.id).in_(batch))
            )

    async def bulk_set_monitored(
        self,
        collection_ids: list[int],
        media_type: MediaType,
        monitored: bool,
        *,
        timestamp: datetime,
    ) -> int:
        """Set the monitored flag of listed collections; return how many matched."""
        updated = 0
        for batch in batched(set(collection_ids), CHUNK_SIZE, strict=False):
            result = await self.session.exec(
                update(MediaCollection)
                .where(
                    col(MediaCollection.id).in_(batch),
                    col(MediaCollection.media_type) == media_type,
                    col(MediaCollection.last_synced_at).is_not(None),
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

    async def titles_by_item(
        self, media_type: MediaType, library_id: str
    ) -> dict[int, list[str]]:
        """The titles of the listed collections each item of a library belongs to."""
        stmt = (
            select(col(MediaCollectionMember.media_item_id), col(MediaCollection.title))
            .join(
                MediaCollection,
                col(MediaCollection.id) == col(MediaCollectionMember.collection_id),
            )
            .where(
                col(MediaCollection.media_type) == media_type,
                col(MediaCollection.library_id) == library_id,
                col(MediaCollection.last_synced_at).is_not(None),
            )
        )
        titles: dict[int, list[str]] = {}
        for item_id, title in await self.session.exec(stmt):
            titles.setdefault(item_id, []).append(title)
        return titles

    async def rule(self, collection_id: int) -> CollectionRule | None:
        """Return the collection's sole rule."""
        return (
            await self.session.exec(
                select(CollectionRule).where(
                    col(CollectionRule.collection_id) == collection_id
                )
            )
        ).first()

    async def presets(self, media_type: MediaType) -> list[CollectionPreset]:
        """Saved presets for the media type, by label."""
        stmt = (
            select(CollectionPreset)
            .where(col(CollectionPreset.media_type) == media_type)
            .order_by(col(CollectionPreset.label))
        )
        return list((await self.session.exec(stmt)).all())

    async def rules(self) -> list[CollectionRule]:
        """Return every rule in stable order."""
        stmt = select(CollectionRule).order_by(col(CollectionRule.id))
        return list((await self.session.exec(stmt)).all())
