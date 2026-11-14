"""Catalog query helpers."""

lazy from collections.abc import Collection, Iterator, Sequence
lazy from itertools import batched
lazy from typing import Literal

lazy from sqlmodel import and_, col, delete, or_, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..catalog_contract.contract import IDENTITY_FIELDS
lazy from ..db.models.catalog import (
    CatalogCollection,
    CatalogItem,
    CatalogItemSeason,
)
lazy from ..db.models.media_item import MediaItem
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import MediaType

#: One external identifier: media type, ID field name, and its value.
type _ExternalId = tuple[str, str, int | str]


class CatalogRepository:
    """Centralize catalog item and season lookups."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def clear_catalog(self) -> None:
        """Delete every persisted catalog row.

        Seasons hang off their item through a cascading foreign key, so
        removing the items removes them too.
        """
        await self.session.exec(delete(CatalogItem))
        await self.session.exec(delete(CatalogCollection))
        await self.session.flush()

    async def collections_by_tmdb_id(
        self, tmdb_ids: Collection[int]
    ) -> dict[int, CatalogCollection]:
        """Return the catalog's collections with these TMDB collection IDs."""
        found: dict[int, CatalogCollection] = {}
        for batch in batched(tmdb_ids, CHUNK_SIZE, strict=False):
            stmt = select(CatalogCollection).where(
                col(CatalogCollection.tmdb_id).in_(batch)
            )
            found.update(
                (collection.tmdb_id, collection)
                for collection in await self.session.exec(stmt)
            )
        return found

    @staticmethod
    def _external_ids(item: MediaItem | CatalogItem) -> Iterator[_ExternalId]:
        """Yield the item's usable external IDs, most preferred (TMDB) first."""
        for field in IDENTITY_FIELDS:
            value = getattr(item, field)
            if value not in {None, ""}:
                yield (item.media_type, field, value)

    @classmethod
    def ids_agreement(
        cls, item: MediaItem, public_item: CatalogItem | None
    ) -> Literal["matching", "mismatching"] | None:
        """Say whether the IDs both carry agree; ``None`` when there is no entry."""
        if public_item is None:
            return None
        ours = {field: value for _, field, value in cls._external_ids(item)}
        conflict = any(
            ours.get(field, value) != value
            for _, field, value in cls._external_ids(public_item)
        )
        return "mismatching" if conflict else "matching"

    async def items_by_media_item_id(
        self, items: Sequence[MediaItem]
    ) -> dict[int, CatalogItem]:
        """Return the catalog row for each stored item, in one query."""
        return {
            item.id: public_item
            for item, public_item in zip(
                items, await self.match_items(items), strict=True
            )
            if item.id is not None and public_item is not None
        }

    async def match_items(self, items: Sequence[MediaItem]) -> list[CatalogItem | None]:
        """Return each item's catalog row, or ``None``, in input order.

        Every external ID the batch carries goes into a single ``OR`` of
        ``IN`` clauses, so resolving one item and resolving ten thousand cost
        the same round trip. Each item then takes the first row its own lookup
        priority finds. Unsaved items match too, by their external IDs.
        """
        wanted: dict[tuple[str, str], set[int | str]] = {}
        for item in items:
            for media_type, field, value in self._external_ids(item):
                wanted.setdefault((media_type, field), set()).add(value)
        if not wanted:
            return [None] * len(items)

        result = await self.session.exec(
            select(CatalogItem).where(
                or_(
                    *(
                        and_(
                            col(CatalogItem.media_type) == media_type,
                            col(getattr(CatalogItem, field)).in_(values),
                        )
                        for (media_type, field), values in wanted.items()
                    )
                )
            )
        )
        by_external_id: dict[_ExternalId, CatalogItem] = {}
        for public_item in result.all():
            for external_id in self._external_ids(public_item):
                by_external_id.setdefault(external_id, public_item)

        return [
            next(
                (
                    public_item
                    for external_id in self._external_ids(item)
                    if (public_item := by_external_id.get(external_id))
                ),
                None,
            )
            for item in items
        ]

    async def list_items(
        self, media_type: MediaType, tmdb_ids: Collection[int] | None = None
    ) -> list[CatalogItem]:
        """Return catalog entries of a media type, optionally limited to TMDB IDs."""
        stmt = select(CatalogItem).where(col(CatalogItem.media_type) == media_type)
        if tmdb_ids is not None:
            stmt = stmt.where(col(CatalogItem.tmdb_id).in_(tmdb_ids))
        return list((await self.session.exec(stmt)).all())

    async def find_item(
        self, media_type: MediaType, field: str, value: int | str
    ) -> CatalogItem | None:
        """Return the catalog entry of a media type with one identifier."""
        stmt = select(CatalogItem).where(
            col(CatalogItem.media_type) == media_type,
            col(getattr(CatalogItem, field)) == value,
        )
        return (await self.session.exec(stmt)).first()

    async def list_collections(self) -> list[CatalogCollection]:
        """Return every catalog collection."""
        return list((await self.session.exec(select(CatalogCollection))).all())

    async def list_seasons(self, catalog_item_id: int) -> list[CatalogItemSeason]:
        """Return catalog seasons for an item ordered by season number."""
        result = await self.session.exec(
            select(CatalogItemSeason)
            .where(col(CatalogItemSeason.catalog_item_id) == catalog_item_id)
            .order_by(col(CatalogItemSeason.season_num))
        )
        return list(result.all())

    async def season_posters_by_item_ids(
        self, catalog_item_ids: set[int]
    ) -> dict[int, dict[int, str]]:
        """Return poster URLs by season number, keyed by public item ID."""
        if not catalog_item_ids:
            return {}
        result = await self.session.exec(
            select(
                CatalogItemSeason.catalog_item_id,
                CatalogItemSeason.season_num,
                CatalogItemSeason.poster_url,
            ).where(
                col(CatalogItemSeason.catalog_item_id).in_(catalog_item_ids),
                col(CatalogItemSeason.poster_url).is_not(None),
            )
        )
        posters: dict[int, dict[int, str]] = {}
        for public_item_id, season_num, poster_url in result.all():
            if public_item_id is not None and poster_url is not None:
                posters.setdefault(public_item_id, {})[season_num] = poster_url
        return posters
