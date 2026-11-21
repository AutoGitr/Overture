"""What removing artwork or themes would change: counts over many records."""

lazy from collections.abc import Sequence
lazy from dataclasses import dataclass
lazy from itertools import batched

lazy from sqlalchemy.sql.elements import ColumnElement
lazy from sqlmodel import col, exists, func, or_, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession
lazy from sqlmodel.sql.expression import SelectOfScalar

lazy from ..db.models.asset import Asset, AssetDelivery
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.media_item_copy import MediaItemCopy
lazy from ..db.models.season import Season
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import DeliveryChannel, ServerAsset


@dataclass(slots=True, frozen=True)
class RemovalCounts:
    """How many records have a selection, a file and a copy on a server."""

    selected: int = 0
    files: int = 0
    on_server: int = 0

    def __add__(self, other: RemovalCounts) -> RemovalCounts:
        return RemovalCounts(
            self.selected + other.selected,
            self.files + other.files,
            self.on_server + other.on_server,
        )


#: The asset selects something.
_SELECTED = or_(
    col(Asset.url).is_not(None),
    col(Asset.upload_hash).is_not(None),
    col(Asset.youtube_id).is_not(None),
)


def _delivered(*where: ColumnElement[bool]) -> ColumnElement[bool]:
    """Whether the asset has a delivery that holds something and meets *where*."""
    return (
        select(AssetDelivery.id)
        .where(
            col(AssetDelivery.asset_id) == col(Asset.id),
            or_(
                col(AssetDelivery.observed_hash).is_not(None),
                col(AssetDelivery.observed_ref).is_not(None),
            ),
            *where,
        )
        .exists()
    )


#: A file the asset was found or written as.
_FILE = _delivered(col(AssetDelivery.channel) == DeliveryChannel.FILE)
#: An image or theme a server copy of a collection shows.
_SERVER_COPY = _delivered(col(AssetDelivery.channel) == DeliveryChannel.UPLOAD)


class RemovalRepository:
    """Count what a removal would change, a bounded chunk of records at a time."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def item_assets(
        self,
        item_ids: Sequence[int],
        kinds: Sequence[ServerAsset],
        season_id: int | None = None,
    ) -> RemovalCounts:
        """Count titles whose assets of *kinds* are selected or on disk.

        Season posters count the title's seasons, or only *season_id*; every
        title a server holds counts as on the server, which shows its files.
        """
        total = RemovalCounts()
        for batch in batched(item_ids, CHUNK_SIZE, strict=False):
            owner = func.coalesce(col(Asset.media_item_id), col(Season.media_item_id))
            seasons = col(Season.media_item_id).in_(batch)
            if season_id is not None:
                seasons = seasons & (col(Season.id) == season_id)
            assets = (
                select(owner)
                .select_from(Asset)
                .outerjoin(Season, col(Season.id) == col(Asset.season_id))
                .where(
                    col(Asset.kind).in_(kinds),
                    or_(col(Asset.media_item_id).in_(batch), seasons),
                )
            )
            on_server = (
                await self.session.exec(
                    select(func.count()).where(
                        col(MediaItem.id).in_(batch),
                        exists().where(
                            col(MediaItemCopy.media_item_id) == col(MediaItem.id)
                        ),
                    )
                )
            ).one()
            total += RemovalCounts(
                await self._count(assets.where(_SELECTED)),
                await self._count(assets.where(_FILE)),
                on_server,
            )
        return total

    async def collection_assets(
        self, collection_ids: Sequence[int], kinds: Sequence[ServerAsset]
    ) -> RemovalCounts:
        """Count collections whose assets of *kinds* are selected, in a folder,
        or shown by a server copy."""
        total = RemovalCounts()
        for batch in batched(collection_ids, CHUNK_SIZE, strict=False):
            assets = select(col(Asset.collection_id)).where(
                col(Asset.collection_id).in_(batch), col(Asset.kind).in_(kinds)
            )
            total += RemovalCounts(
                await self._count(assets.where(_SELECTED)),
                await self._count(assets.where(_FILE)),
                await self._count(assets.where(_SERVER_COPY)),
            )
        return total

    async def _count(
        self, owners: SelectOfScalar[int] | SelectOfScalar[int | None]
    ) -> int:
        """Count the distinct owners a selection of assets names."""
        subquery = owners.distinct().subquery()
        return (
            await self.session.exec(select(func.count()).select_from(subquery))
        ).one()
