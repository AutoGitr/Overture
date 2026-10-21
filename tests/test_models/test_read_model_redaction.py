"""Read-model sanitisation and defaults."""

lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import MediaType
lazy from overture.schemas.library import MediaItemRead, SeasonRead


def test_media_item_defaults_are_safe_for_new_records() -> None:
    item = MediaItem(media_type=MediaType.MOVIE, title="Movie")

    assert item.monitored is True
    assert item.folder_path is None
    assert item.server_item_id is None


def test_media_item_read_strips_sensitive_art_urls() -> None:
    read = MediaItemRead(
        id=1,
        media_type=MediaType.MOVIE,
        title="Movie",
        server_item_id="plex-1",
        poster_url="https://img.test/poster.jpg?api_key=secret",
        background_url="https://img.test/bg.jpg?ok=1",
    )

    assert read.poster_url is None
    assert read.background_url == "https://img.test/bg.jpg?ok=1"


def test_season_read_model_strips_sensitive_urls() -> None:
    season = SeasonRead(
        id=1,
        media_item_id=1,
        season_num=1,
        poster_url="https://img.test/season.jpg?X-Plex-Token=secret",
    )

    assert season.poster_url is None
