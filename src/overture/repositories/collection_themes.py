"""Collection theme query helpers."""

lazy from collections.abc import Mapping
lazy from datetime import datetime
lazy from itertools import batched

lazy from sqlalchemy.dialects.sqlite import insert
lazy from sqlmodel import col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.collection_theme import CollectionTheme
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import MediaType, ServerType


class CollectionThemeRepository:
    """Centralize collection theme persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_for_collection(
        self, server_item_id: str, media_type: MediaType | None = None
    ) -> CollectionTheme | None:
        """Return a collection theme row."""
        stmt = select(CollectionTheme).where(
            col(CollectionTheme.server_item_id) == server_item_id
        )
        if media_type is not None:
            stmt = stmt.where(col(CollectionTheme.media_type) == media_type)
        return (await self.session.exec(stmt)).first()

    async def list_for_media_type(self, media_type: str) -> list[CollectionTheme]:
        """Return all persisted collection preferences and provenance for a type."""
        stmt = select(CollectionTheme).where(
            col(CollectionTheme.media_type) == media_type
        )
        return list((await self.session.exec(stmt)).all())

    async def clear_theme(
        self, server_item_id: str, media_type: MediaType, *, timestamp: datetime
    ) -> None:
        """Clear stored theme state for a collection if present."""
        row = await self.get_for_collection(server_item_id, media_type)
        if not row:
            return
        row.sqlmodel_update(
            {
                "youtube_id": None,
                "youtube_title": None,
                "youtube_duration": None,
                "server_theme_id": None,
                "updated_at": timestamp,
            }
        )
        self.session.add(row)

    async def upsert_uploaded_theme(
        self,
        *,
        server_item_id: str,
        media_type: MediaType,
        server_type: ServerType,
        youtube_id: str,
        youtube_title: str | None,
        youtube_duration: int | None,
        server_theme_id: str,
        timestamp: datetime,
    ) -> CollectionTheme:
        """Create or update a collection row after a successful upload."""
        row = await self.get_for_collection(server_item_id, media_type)
        if row:
            row.sqlmodel_update(
                {
                    "youtube_id": youtube_id,
                    "youtube_title": youtube_title,
                    "youtube_duration": youtube_duration,
                    "server_theme_id": server_theme_id,
                    "updated_at": timestamp,
                }
            )
        else:
            row = CollectionTheme(
                server_item_id=server_item_id,
                media_type=media_type,
                server_type=server_type,
                youtube_id=youtube_id,
                youtube_title=youtube_title,
                youtube_duration=youtube_duration,
                server_theme_id=server_theme_id,
                created_at=timestamp,
                updated_at=timestamp,
            )
        self.session.add(row)
        return row

    async def reconcile_provider_themes(
        self,
        provider_theme_ids: Mapping[str, str | None],
        media_type: MediaType,
        *,
        timestamp: datetime,
    ) -> dict[str, CollectionTheme]:
        """Invalidate provenance when a provider theme changed externally."""
        rows = await self.list_for_media_type(media_type)
        for row in rows:
            provider_theme_id = provider_theme_ids.get(row.server_item_id)
            if row.server_theme_id == provider_theme_id:
                continue
            row.sqlmodel_update(
                {
                    "youtube_id": None,
                    "youtube_title": None,
                    "youtube_duration": None,
                    "server_theme_id": provider_theme_id,
                    "updated_at": timestamp,
                }
            )
            self.session.add(row)
        return {
            row.server_item_id: row
            for row in rows
            if row.server_item_id in provider_theme_ids
        }

    async def set_monitored(
        self,
        *,
        server_item_id: str,
        media_type: MediaType,
        server_type: ServerType,
        monitored: bool,
        timestamp: datetime,
    ) -> CollectionTheme:
        """Set a collection monitored flag, creating a row when needed."""
        row = await self.get_for_collection(server_item_id, media_type)
        if row:
            row.sqlmodel_update(
                {
                    "monitored": monitored,
                    "updated_at": timestamp,
                }
            )
        else:
            row = CollectionTheme(
                server_item_id=server_item_id,
                media_type=media_type,
                server_type=server_type,
                monitored=monitored,
                created_at=timestamp,
                updated_at=timestamp,
            )
        self.session.add(row)
        return row

    async def bulk_set_monitored(
        self,
        collection_ids: list[str],
        media_type: MediaType,
        monitored: bool,
        *,
        server_type: ServerType,
        timestamp: datetime,
    ) -> int:
        """Upsert collection preferences in batches, preserving theme metadata."""
        ids = set(collection_ids)
        for batch in batched(ids, CHUNK_SIZE, strict=False):
            stmt = insert(CollectionTheme).values(
                [
                    {
                        "server_item_id": server_id,
                        "media_type": media_type,
                        "server_type": server_type,
                        "monitored": monitored,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                    }
                    for server_id in batch
                ]
            )
            await self.session.exec(
                stmt.on_conflict_do_update(
                    index_elements=["server_item_id", "media_type"],
                    set_={"monitored": monitored, "updated_at": timestamp},
                )
            )
        return len(ids)
