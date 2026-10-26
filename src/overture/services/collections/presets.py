"""Library-driven presets compiled into ordinary collection builders."""

lazy from collections import Counter

lazy from ...db.models.media_item import MediaItem
lazy from ...domain import FilterField
lazy from ...schemas.collections import (
    CollectionPreset,
    CollectionPresetEntry,
    FilterCondition,
    FilterGroup,
    LibraryFilterBuilder,
)


def preview_preset(
    preset: CollectionPreset, items: list[MediaItem]
) -> list[CollectionPresetEntry]:
    """Generate only values present in a library, with stable ordering."""
    counts: Counter[str | int] = Counter()
    for item in items:
        if preset == "genres":
            counts.update(set(item.genres))
        elif item.year is not None:
            counts[item.year // 10 * 10 if preset == "decades" else item.year] += 1
    field = (
        FilterField.GENRE
        if preset == "genres"
        else FilterField.DECADE
        if preset == "decades"
        else FilterField.YEAR
    )
    return [
        CollectionPresetEntry(
            key=str(value),
            title=f"{value}s" if preset == "decades" else str(value),
            member_count=counts[value],
            builder=LibraryFilterBuilder(
                filter_group=FilterGroup(
                    conditions=[FilterCondition(field=field, value=value)]
                )
            ),
        )
        for value in sorted(counts, key=lambda value: str(value).casefold())
    ]
