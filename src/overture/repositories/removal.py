"""What removing artwork or themes would change: counts over many records."""

lazy from collections.abc import Sequence
lazy from dataclasses import dataclass
lazy from itertools import batched

lazy from sqlalchemy.sql.elements import ColumnElement
lazy from sqlmodel import col, func, or_, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession
lazy from sqlmodel.sql.expression import SelectOfScalar

lazy from ..db.models.art import ArtSlot
lazy from ..db.models.media_collection import MediaCollection
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.season import Season
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import ArtType


@dataclass(slots=True, frozen=True)
class RemovalCounts:
    """How many records have a selection, a local file and a server copy."""

    selected: int = 0
    files: int = 0
    on_server: int = 0

    def __add__(self, other: RemovalCounts) -> RemovalCounts:
        return RemovalCounts(
            self.selected + other.selected,
            self.files + other.files,
            self.on_server + other.on_server,
        )


def _selected(slot: type[ArtSlot]) -> ColumnElement[bool]:
    return or_(col(slot.url).is_not(None), col(slot.upload_hash).is_not(None))


class RemovalRepository:
    """Count what a removal would change, a bounded chunk of records at a time."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def item_art(
        self,
        item_ids: Sequence[int],
        art_types: Sequence[ArtType],
        season_id: int | None,
    ) -> RemovalCounts:
        """Count items whose art of *art_types* is selected, on disk, on the server.

        Season posters count the item's seasons, or only *season_id*.
        """
        total = RemovalCounts()
        for batch in batched(item_ids, CHUNK_SIZE, strict=False):
            owner = func.coalesce(col(ArtSlot.media_item_id), col(Season.media_item_id))
            seasons = col(Season.media_item_id).in_(batch)
            if season_id is not None:
                seasons = seasons & (col(Season.id) == season_id)
            in_batch = or_(
                col(ArtSlot.media_item_id).in_(batch)
                & col(ArtSlot.art_type).in_(
                    [art for art in art_types if not art.owned_by_season]
                ),
                seasons
                & col(ArtSlot.art_type).in_(
                    [art for art in art_types if art.owned_by_season]
                ),
            )
            slots = (
                select(owner)
                .select_from(ArtSlot)
                .outerjoin(Season, col(Season.id) == col(ArtSlot.season_id))
                .join(MediaItem, col(MediaItem.id) == owner)
                .where(in_batch)
            )
            selected = await self._count(slots.where(_selected(ArtSlot)))
            files = await self._count(
                slots.where(
                    col(ArtSlot.file_hash).is_not(None),
                    col(MediaItem.folder_path).is_not(None),
                )
            )
            on_server = (
                await self.session.exec(
                    select(func.count()).where(
                        col(MediaItem.id).in_(batch),
                        col(MediaItem.server_item_id).is_not(None),
                    )
                )
            ).one()
            total += RemovalCounts(selected, files, on_server)
        return total

    async def item_themes(self, item_ids: Sequence[int]) -> RemovalCounts:
        """Count items whose theme is selected, on disk, and that are on the server."""
        total = RemovalCounts()
        for batch in batched(item_ids, CHUNK_SIZE, strict=False):
            selected, files, on_server = (
                await self.session.exec(
                    select(
                        func.count(col(MediaItem.youtube_id)),
                        func.count().filter(
                            col(MediaItem.folder_path).is_not(None),
                            col(MediaItem.theme_file_hash).is_not(None),
                        ),
                        func.count(col(MediaItem.server_item_id)),
                    ).where(col(MediaItem.id).in_(batch))
                )
            ).one()
            total += RemovalCounts(selected, files, on_server)
        return total

    async def collection_art(
        self, collection_ids: Sequence[int], art_types: Sequence[ArtType]
    ) -> RemovalCounts:
        """Count collections with art selected and an image on the server."""
        total = RemovalCounts()
        server_images = [
            col(
                MediaCollection.thumb_url
                if art is ArtType.POSTER
                else MediaCollection.art_url
            ).is_not(None)
            for art in art_types
        ]
        for batch in batched(collection_ids, CHUNK_SIZE, strict=False):
            selected = await self._count(
                select(col(ArtSlot.collection_id)).where(
                    col(ArtSlot.collection_id).in_(batch),
                    col(ArtSlot.art_type).in_(art_types),
                    _selected(ArtSlot),
                )
            )
            on_server = (
                await self.session.exec(
                    select(func.count()).where(
                        col(MediaCollection.id).in_(batch), or_(*server_images)
                    )
                )
            ).one()
            total += RemovalCounts(selected, 0, on_server)
        return total

    async def collection_themes(self, collection_ids: Sequence[int]) -> RemovalCounts:
        """Count collections whose theme is selected, in a folder, on the server."""
        total = RemovalCounts()
        for batch in batched(collection_ids, CHUNK_SIZE, strict=False):
            selected, files, on_server = (
                await self.session.exec(
                    select(
                        func.count(col(MediaCollection.youtube_id)),
                        func.count(col(MediaCollection.theme_file_hash)),
                        func.count(col(MediaCollection.server_theme_id)),
                    ).where(col(MediaCollection.id).in_(batch))
                )
            ).one()
            total += RemovalCounts(selected, files, on_server)
        return total

    async def _count(
        self, owners: SelectOfScalar[int] | SelectOfScalar[int | None]
    ) -> int:
        """Count the distinct owners a selection of slots names."""
        subquery = owners.distinct().subquery()
        return (
            await self.session.exec(select(func.count()).select_from(subquery))
        ).one()
