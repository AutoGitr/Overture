"""Artwork target presentation helpers."""

lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season


def target_label(item: MediaItem, *, season: Season | None = None) -> str:
    """Build a user-facing label for an artwork target."""
    label = item.title
    if season:
        label += f" S{season.season_num:02d}"
    return label
