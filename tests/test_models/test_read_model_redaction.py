"""Read-model sanitisation and defaults."""

lazy from datetime import UTC, datetime

lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import MediaType, ServerType
lazy from overture.schemas.collections import collection_read
lazy from overture.schemas.library import media_item_read_from_model
lazy from tests.collection_helpers import stored_collection


def test_media_item_defaults_are_safe_for_new_records() -> None:
    item = MediaItem(media_type=MediaType.MOVIE, title="Movie")

    assert item.monitored is True
    assert item.folder_path is None
    assert item.server_item_id is None


def test_server_links_go_with_the_server_copy() -> None:
    link = "https://app.plex.tv/desktop#!/server/m/details?key=1"
    on_server = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Movie",
        server_item_id="1",
        server_link=link,
    )
    removed = on_server.model_copy(update={"server_removed_at": datetime.now(UTC)})
    collection = stored_collection(
        id=1,
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        title="Saga",
        server_item_id="9",
        server_link=link,
    )
    withheld = stored_collection(
        server_type=ServerType.PLEX, title="Saga", server_link=link
    )

    assert media_item_read_from_model(on_server, seasons=[]).server_link == link
    assert media_item_read_from_model(removed, seasons=[]).server_link is None
    assert collection_read(collection, None).server_link == link
    assert collection_read(withheld, None).server_link is None
