"""Stored catalog rows spelled as the contract spells their entries."""

lazy from typing import Any

lazy from ...dataset_contract.contract import entry_fields
lazy from ...db.models.public_dataset import PublicDatasetCollection, PublicDatasetItem
lazy from ...domain import CatalogMediaType, MediaType

type Entry = dict[str, Any]


def catalog_item_entry(
    item: PublicDatasetItem, season_posters: dict[int, str]
) -> Entry:
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


def catalog_collection_entry(collection: PublicDatasetCollection) -> Entry:
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
