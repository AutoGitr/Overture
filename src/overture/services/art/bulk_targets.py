"""Per-target slot reads for bulk art runs."""

lazy from datetime import datetime

lazy from ...db.art_slots import read_art_slot
lazy from ...db.models.art import ArtSlot
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...domain import ArtType


def target_art_slot(
    item: MediaItem, art_type: ArtType, *, season: Season | None
) -> ArtSlot | None:
    """Return the slot *art_type* names on the item or season that owns it.

    ``None`` means the target has no owner to read - a season-owned art type
    asked for without a season - not that the slot is empty.
    """
    owner = season if art_type.owned_by_season else item
    return None if owner is None else read_art_slot(owner, art_type)


def awaiting_match(
    item: MediaItem, art_type: ArtType, *, season: Season | None
) -> bool:
    """Return whether the slot lacks a saved selection, regardless of disk state."""
    slot = target_art_slot(item, art_type, season=season)
    return not (slot and slot.url)


def last_checked_at(
    item: MediaItem, art_type: ArtType, *, season: Season | None
) -> datetime | None:
    """Return the check timestamp governing this target's skip-recent window."""
    if art_type.owned_by_season and season:
        return season.last_matched_at
    return item.last_matched_at
