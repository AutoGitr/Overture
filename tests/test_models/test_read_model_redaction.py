"""Read-model sanitisation and defaults."""

lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import MediaType


def test_media_item_defaults_are_safe_for_new_records() -> None:
    item = MediaItem(media_type=MediaType.MOVIE, title="Movie")

    assert item.monitored is True
    assert item.folder_path is None
    assert item.server_item_id is None
