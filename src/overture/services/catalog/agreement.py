"""Whether a library title's selections agree with what OvertureDB holds for it."""

lazy from collections.abc import Iterable, Sequence

lazy from ...catalog_contract.contract import catalog_art_url
lazy from ...db.ledger import read_asset
lazy from ...db.models.asset import Asset
lazy from ...db.models.catalog import CatalogCollection, CatalogItem
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...domain import CollectionPosterStyle, MediaType, ServerAsset
lazy from ...schemas.catalog import Agreement, CatalogSelections
lazy from .entries import (
    catalog_collection_entry,
    catalog_collection_poster,
    collection_poster_field,
)

#: A local selection beside OvertureDB's, either of them ``None`` when absent.
type Pair = tuple[str | None, str | None]


def _art(asset: Asset) -> str | None:
    """An asset's selection as OvertureDB would hold it.

    An upload, which OvertureDB cannot hold, stands as its hash, so it
    differs from any link.
    """
    if asset.upload_hash or not asset.url:
        return asset.upload_hash
    try:
        return catalog_art_url(asset.url)
    except ValueError:
        return asset.url


def _theme(entry: CatalogItem | CatalogCollection) -> str | None:
    """The theme a theme run takes from the catalog: OvertureDB's, else ThemerrDB's."""
    return entry.youtube_id_overturedb or entry.youtube_id_themerrdb


def agreement(*pairs: Pair) -> Agreement:
    """Compare selections; a value on one side only is a difference."""
    return "matching" if all(local == held for local, held in pairs) else "different"


def item_agreement(
    item: MediaItem,
    entry: CatalogItem | None,
    seasons: Iterable[Season],
    season_posters: dict[int, str],
) -> CatalogSelections | None:
    """How each of an item's selections compares with its catalog entry."""
    if entry is None:
        return None
    return CatalogSelections(
        poster=agreement(
            (_art(read_asset(item, ServerAsset.POSTER)), entry.poster_url)
        ),
        background=agreement(
            (_art(read_asset(item, ServerAsset.BACKGROUND)), entry.background_url)
        ),
        season_posters=agreement(
            *(
                (
                    _art(read_asset(season, ServerAsset.SEASON_POSTER)),
                    season_posters.get(season.season_num),
                )
                for season in seasons
            )
        )
        if item.media_type is MediaType.SHOW
        else None,
        theme=agreement(
            (read_asset(item, ServerAsset.THEME).youtube_id, _theme(entry))
        ),
    )


def collection_agreement(
    row: MediaCollection,
    entry: CatalogCollection | None,
    posters: Sequence[CollectionPosterStyle],
) -> CatalogSelections | None:
    """How each of a collection's selections compares with its catalog entry.

    A chosen poster link is compared with the catalog poster of the style it
    was chosen as; any other poster, or none, with the first poster of the
    styles *posters* orders.
    """
    if entry is None:
        return None
    poster = read_asset(row, ServerAsset.POSTER)
    if poster.poster_style:
        held = catalog_collection_entry(entry)[
            collection_poster_field(poster.poster_style)
        ]
    else:
        taken = catalog_collection_poster(entry, posters)
        held = taken[0] if taken else None
    return CatalogSelections(
        poster=agreement((_art(poster), held)),
        background=agreement(
            (_art(read_asset(row, ServerAsset.BACKGROUND)), entry.background_url)
        ),
        theme=agreement((read_asset(row, ServerAsset.THEME).youtube_id, _theme(entry))),
    )
