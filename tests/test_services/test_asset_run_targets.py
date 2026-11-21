"""An Assets run's targets read the asset and check time of their own owner."""

lazy from datetime import timedelta

lazy from overture.domain import MediaType, ServerAsset
lazy from overture.services.asset_runs.plan import Target
lazy from overture.utils.time import utc_now
lazy from tests.collection_helpers import stored_collection
lazy from tests.factories import MediaItemFactory, SeasonFactory


def test_a_target_reads_the_asset_of_its_owner(
    media_item_factory: MediaItemFactory, season_factory: SeasonFactory
) -> None:
    item = media_item_factory(
        id=1,
        media_type=MediaType.SHOW,
        title="Show",
        art={
            "poster": {"url": "https://x/poster.jpg"},
            "background": {"url": "https://x/bg.jpg"},
        },
    )
    season = season_factory(
        season_num=2, art={"season_poster": {"url": "https://x/season.jpg"}}
    )

    poster = Target(item, ServerAsset.POSTER)
    season_poster = Target(season, ServerAsset.SEASON_POSTER, item)
    assert poster.asset.url == "https://x/poster.jpg"
    assert Target(item, ServerAsset.BACKGROUND).asset.url == "https://x/bg.jpg"
    assert season_poster.asset.url == "https://x/season.jpg"
    assert (poster.label, season_poster.label) == (
        "Show (poster)",
        "Show S02 (season_poster)",
    )
    saga = Target(stored_collection(title="Saga"), ServerAsset.THEME)
    assert saga.label == "Saga (collection theme)"


def test_a_season_poster_is_checked_when_its_season_was(
    media_item_factory: MediaItemFactory, season_factory: SeasonFactory
) -> None:
    item_checked = utc_now()
    season_checked = item_checked - timedelta(days=1)
    item = media_item_factory(id=1, last_matched_at=item_checked)
    season = season_factory(last_matched_at=season_checked)

    assert Target(item, ServerAsset.POSTER).last_checked == item_checked
    assert (
        Target(season, ServerAsset.SEASON_POSTER, item).last_checked == season_checked
    )
