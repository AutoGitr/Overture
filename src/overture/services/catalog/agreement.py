"""Whether a library title's selections agree with what OvertureDB holds for it."""

lazy from collections.abc import Iterable
lazy from typing import Literal

lazy from ...catalog_contract.contract import catalog_art_url
lazy from ...db.art_slots import find_art_slot
lazy from ...db.models.art import ArtSlot
lazy from ...db.models.catalog import CatalogCollection, CatalogItem
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...domain import ArtType, CollectionPosterStyle
lazy from .entries import catalog_collection_entry, collection_poster_field

type Agreement = Literal["matching", "different"]
#: A local selection beside OvertureDB's, either of them ``None`` when absent.
type Pair = tuple[str | None, str | None]


def _art(slot: ArtSlot | None) -> str | None:
    """A slot's selection as OvertureDB would hold it.

    An upload, which OvertureDB cannot hold, stands as its file hash, so it
    differs from any link.
    """
    if slot is None:
        return None
    if slot.upload_hash or not slot.url:
        return slot.upload_hash
    try:
        return catalog_art_url(slot.url)
    except ValueError:
        return slot.url


def _theme(entry: CatalogItem | CatalogCollection) -> str | None:
    """The theme a theme run takes from the catalog: OvertureDB's, else ThemerrDB's."""
    return entry.youtube_id_overturedb or entry.youtube_id_themerrdb


def agreement(pairs: Iterable[Pair]) -> Agreement | None:
    """Compare the slots both sides select; ``None`` when no slot has both."""
    compared = [local == held for local, held in pairs if local and held]
    if not compared:
        return None
    return "matching" if all(compared) else "different"


def item_agreement(
    item: MediaItem,
    entry: CatalogItem | None,
    seasons: Iterable[Season],
    season_posters: dict[int, str],
) -> Agreement | None:
    """How an item's art and theme selections compare with its catalog entry."""
    if entry is None:
        return None
    return agreement(
        [
            (_art(find_art_slot(item, ArtType.POSTER)), entry.poster_url),
            (_art(find_art_slot(item, ArtType.BACKGROUND)), entry.background_url),
            *(
                (
                    _art(find_art_slot(season, ArtType.SEASON_POSTER)),
                    season_posters.get(season.season_num),
                )
                for season in seasons
            ),
            (item.youtube_id, _theme(entry)),
        ]
    )


def collection_agreement(
    row: MediaCollection,
    entry: CatalogCollection | None,
    posters: CollectionPosterStyle,
) -> Agreement | None:
    """How a collection's selections compare with its catalog entry.

    Its poster is compared with the catalog poster of the style it takes.
    """
    if entry is None:
        return None
    return agreement(
        [
            (
                _art(find_art_slot(row, ArtType.POSTER)),
                catalog_collection_entry(entry)[collection_poster_field(posters)],
            ),
            (_art(find_art_slot(row, ArtType.BACKGROUND)), entry.background_url),
            (row.youtube_id, _theme(entry)),
        ]
    )
