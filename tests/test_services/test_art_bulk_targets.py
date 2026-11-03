"""Artwork slot ownership and last-checked timestamps."""

lazy from datetime import timedelta
lazy from typing import Any

lazy from overture.domain import ArtType
lazy from overture.services.art import bulk_targets as module
lazy from overture.utils.time import utc_now
lazy from tests.factories import (
    MediaItemFactory,
    SeasonFactory,
)


def test_target_art_slot_reads_the_slot_of_the_owner(
    media_item_factory: MediaItemFactory, season_factory: SeasonFactory
) -> None:
    item = media_item_factory(
        id=1,
        art={
            "poster": {"url": "https://x/poster.jpg"},
            "background": {"url": "https://x/bg.jpg"},
        },
    )
    season = season_factory(art={"season_poster": {"url": "https://x/season.jpg"}})

    def slot_url(art_type: ArtType, season_arg: Any) -> str | None:
        slot = module.target_art_slot(item, art_type, season=season_arg)
        return slot.url if slot else None

    assert slot_url(ArtType.POSTER, None) == "https://x/poster.jpg"
    assert slot_url(ArtType.BACKGROUND, None) == "https://x/bg.jpg"
    assert slot_url(ArtType.SEASON_POSTER, season) == "https://x/season.jpg"
    assert module.target_art_slot(item, ArtType.SEASON_POSTER, season=None) is None


def test_season_slots_are_read_from_the_season_not_the_item(
    media_item_factory: MediaItemFactory, season_factory: SeasonFactory
) -> None:
    """A season poster's state must come from the season that owns it."""
    item = media_item_factory(id=1, art={"poster": {"url": "https://x/p.jpg"}})
    season = season_factory(
        art={"season_poster": {"url": "https://x/s.jpg", "file_hash": "h"}}
    )

    slot = module.target_art_slot(item, ArtType.SEASON_POSTER, season=season)
    assert slot is not None
    assert slot.url == "https://x/s.jpg"


def test_last_checked_at_prefers_the_season_that_owns_the_slot(
    media_item_factory: MediaItemFactory, season_factory: SeasonFactory
) -> None:
    item_checked = utc_now()
    season_checked = item_checked - timedelta(days=1)
    item = media_item_factory(id=1, last_matched_at=item_checked)
    season = season_factory(last_matched_at=season_checked)

    assert module.last_checked_at(item, ArtType.POSTER, season=season) == item_checked
    assert (
        module.last_checked_at(item, ArtType.SEASON_POSTER, season=season)
        == season_checked
    )
    assert (
        module.last_checked_at(item, ArtType.SEASON_POSTER, season=None) == item_checked
    )
