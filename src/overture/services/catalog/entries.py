"""Stored catalog rows spelled as the contract spells their entries."""

lazy from collections.abc import Sequence
lazy from typing import Any

lazy from ...catalog_contract.contract import catalog_art_url, entry_fields
lazy from ...db.models.catalog import CatalogCollection, CatalogItem
lazy from ...domain import CatalogMediaType, CollectionPosterStyle

type Entry = dict[str, Any]


def collection_poster_field(posters: CollectionPosterStyle) -> str:
    """The entry field that is a collection's poster, as *posters* chooses."""
    return f"poster_url_{posters.value}"


def catalog_collection_poster(
    entry: CatalogCollection, posters: Sequence[CollectionPosterStyle]
) -> tuple[str, CollectionPosterStyle] | None:
    """The first poster of the styles *posters* orders that the entry holds."""
    held = catalog_collection_entry(entry)
    return next(
        (
            (url, style)
            for style in posters
            if (url := held[collection_poster_field(style)])
        ),
        None,
    )


def held_poster_style(
    entry: CatalogCollection | None, url: str
) -> CollectionPosterStyle | None:
    """The style of OvertureDB's poster for the collection that *url* links to."""
    if entry is None:
        return None
    try:
        canonical = catalog_art_url(url)
    except ValueError:
        return None
    held = catalog_collection_entry(entry)
    return next(
        (
            style
            for style in CollectionPosterStyle
            if held[collection_poster_field(style)] == canonical
        ),
        None,
    )


def catalog_item_entry(item: CatalogItem, season_posters: dict[int, str]) -> Entry:
    """Return a stored movie or show as the contract spells the entry."""
    seasons = [
        {"season_num": number, "poster_url": url}
        for number, url in sorted(season_posters.items())
    ]
    entry: Entry = {
        name: seasons if name == "seasons" else getattr(item, name)
        for name in entry_fields(item.media_type)
    }
    if item.no_theme:
        entry["no_theme"] = True
    return entry


def catalog_collection_entry(collection: CatalogCollection) -> Entry:
    """Return a stored collection as the contract spells the entry."""
    entry: Entry = {
        name: CatalogMediaType.COLLECTION.value
        if name == "media_type"
        else getattr(collection, name)
        for name in entry_fields(CatalogMediaType.COLLECTION)
    }
    if collection.no_theme:
        entry["no_theme"] = True
    return entry
