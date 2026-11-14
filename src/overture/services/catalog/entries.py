"""Stored catalog rows spelled as the contract spells their entries."""

lazy from typing import Any

lazy from ...catalog_contract.contract import entry_fields
lazy from ...db.models.catalog import CatalogCollection, CatalogItem
lazy from ...domain import CatalogMediaType, CollectionPosterStyle, MediaType

type Entry = dict[str, Any]


def collection_poster_field(posters: CollectionPosterStyle) -> str:
    """The entry field that is a collection's poster, as *posters* chooses."""
    return (
        "consistent_poster_url"
        if posters is CollectionPosterStyle.CONSISTENT
        else "poster_url"
    )


def shown_entry(entry: Entry, posters: CollectionPosterStyle) -> Entry:
    """Return *entry* with a collection's chosen poster as its only poster."""
    if entry["media_type"] != CatalogMediaType.COLLECTION:
        return entry
    shown = {
        name: value for name, value in entry.items() if name != "consistent_poster_url"
    }
    shown["poster_url"] = entry.get(collection_poster_field(posters))
    return shown


def catalog_item_entry(item: CatalogItem, season_posters: dict[int, str]) -> Entry:
    """Return a stored movie or show as the contract spells the entry."""
    entry: Entry = {
        name: getattr(item, name)
        for name in entry_fields(item.media_type)
        if name != "seasons"
    }
    if item.no_theme:
        entry["no_theme"] = True
    if item.media_type is MediaType.SHOW:
        entry["seasons"] = [
            {"season_num": number, "poster_url": url}
            for number, url in sorted(season_posters.items())
        ]
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
    if collection.consistent_poster_url is not None:
        entry["consistent_poster_url"] = collection.consistent_poster_url
    return entry
