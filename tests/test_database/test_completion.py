"""The completeness rules every consumer of artwork and theme state shares."""

lazy import pytest

lazy from overture.db.art_slots import read_art_slot
lazy from overture.db.completion import (
    art_completion,
    collection_theme_status,
    slot_complete,
    theme_status,
)
lazy from overture.domain import ArtType, MediaType
lazy from tests.factories import MediaItemFactory, SeasonFactory

COMPLETE = {"url": "https://x/a.jpg", "file_hash": "h"}


@pytest.mark.parametrize(
    ("fields", "complete"),
    [
        (COMPLETE, True),
        ({"url": "https://x/a.jpg"}, False),
        ({"file_hash": "h"}, False),
        ({}, False),
    ],
)
def test_a_slot_needs_its_link_and_a_local_file(
    media_item_factory: MediaItemFactory, fields: dict[str, str], complete: bool
) -> None:
    item = media_item_factory(art={"poster": fields} if fields else None)

    assert slot_complete(read_art_slot(item, ArtType.POSTER), files=True) is complete


@pytest.mark.parametrize(
    ("fields", "status"),
    [({"url": "https://x/a.jpg"}, "complete"), ({}, "missing")],
)
def test_without_a_folder_the_link_alone_completes_a_slot(
    media_item_factory: MediaItemFactory, fields: dict[str, str], status: str
) -> None:
    item = media_item_factory(
        folder_path=None, art={"poster": fields, "background": fields}
    )

    assert slot_complete(read_art_slot(item, ArtType.POSTER), files=False) is (
        status == "complete"
    )
    assert art_completion(item, []).art_status == status


@pytest.mark.parametrize(
    ("art", "status"),
    [
        ({"poster": COMPLETE, "background": COMPLETE}, "complete"),
        ({"poster": COMPLETE}, "partial"),
        ({"background": {"url": "https://x/b.jpg"}}, "partial"),
        ({"poster": {"file_hash": "h"}}, "partial"),
        (None, "missing"),
    ],
)
def test_movie_art_status(
    media_item_factory: MediaItemFactory,
    art: dict[str, dict[str, str]] | None,
    status: str,
) -> None:
    completion = art_completion(media_item_factory(art=art), [])

    assert completion.art_status == status
    assert completion.season_posters_status == "missing"


@pytest.mark.parametrize(
    ("fields", "status"),
    [
        (COMPLETE, "complete"),
        ({"url": "https://x/a.jpg"}, "partial"),
        ({"file_hash": "h"}, "partial"),
        ({}, "missing"),
    ],
)
def test_each_slot_reports_its_own_status(
    media_item_factory: MediaItemFactory, fields: dict[str, str], status: str
) -> None:
    completion = art_completion(
        media_item_factory(art={"poster": fields, "background": COMPLETE}), []
    )

    assert completion.poster_status == status
    assert completion.background_status == "complete"


def test_a_show_needs_a_complete_poster_for_every_season_with_files(
    media_item_factory: MediaItemFactory, season_factory: SeasonFactory
) -> None:
    show = media_item_factory(
        media_type=MediaType.SHOW, art={"poster": COMPLETE, "background": COMPLETE}
    )
    done = season_factory(id=1, art={"season_poster": COMPLETE})
    linked = season_factory(id=2, art={"season_poster": {"url": "https://x/s.jpg"}})

    assert art_completion(show, [done]).art_status == "complete"
    assert art_completion(show, [done]).season_posters_status == "complete"
    assert art_completion(show, [done, linked]).art_status == "partial"
    assert art_completion(show, [done, linked]).season_posters_status == "partial"
    # Without any season files a show's artwork is never complete.
    assert art_completion(show, []).art_status == "partial"
    assert art_completion(show, []).season_posters_status == "missing"


def test_season_posters_alone_make_a_show_partial(
    media_item_factory: MediaItemFactory, season_factory: SeasonFactory
) -> None:
    show = media_item_factory(media_type=MediaType.SHOW)
    linked = season_factory(art={"season_poster": {"url": "https://x/s.jpg"}})

    assert art_completion(show, [linked]).art_status == "partial"


@pytest.mark.parametrize(
    ("youtube_id", "file_hash", "status"),
    [
        ("abcDEF123_4", "h", "complete"),
        ("abcDEF123_4", None, "partial"),
        (None, "h", "partial"),
        (None, None, "missing"),
    ],
)
def test_theme_status(
    media_item_factory: MediaItemFactory,
    youtube_id: str | None,
    file_hash: str | None,
    status: str,
) -> None:
    item = media_item_factory(youtube_id=youtube_id, theme_file_hash=file_hash)

    assert theme_status(item) == status


def test_without_a_folder_a_selected_theme_is_complete(
    media_item_factory: MediaItemFactory,
) -> None:
    item = media_item_factory(folder_path=None, youtube_id="abcDEF123_4")

    assert theme_status(item) == "complete"


@pytest.mark.parametrize(
    ("server_has_theme", "youtube_id", "status"),
    [
        (True, "abcDEF123_4", "complete"),
        (True, None, "partial"),
        (False, "abcDEF123_4", "partial"),
        (False, None, "missing"),
    ],
)
def test_collection_theme_status(
    *, server_has_theme: bool, youtube_id: str | None, status: str
) -> None:
    assert (
        collection_theme_status(
            server_has_theme=server_has_theme, youtube_id=youtube_id
        )
        == status
    )
