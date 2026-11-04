"""One entry contributed through a prefilled OvertureDB issue form."""

lazy from urllib.parse import parse_qs, urlsplit

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.art_slots import select_art
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType, ServerType
lazy from overture.services.public_dataset.issue import (
    collection_issue,
    contribution_issue,
    item_issue,
)
lazy from overture.utils.art_urls import PublicArtUrl
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.time import utc_now

POSTER = "https://image.tmdb.org/t/p/original/poster.jpg"


def _query(url: str | None) -> dict[str, str]:
    assert url is not None
    parsed = urlsplit(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == (
        "https://github.com/AutoGitr/OvertureDB/issues/new"
    )
    return {key: values[0] for key, values in parse_qs(parsed.query).items()}


async def test_a_show_issue_fills_its_form_with_the_saved_selections(
    db_session: AsyncSession, database: Database
) -> None:
    show = MediaItem(
        media_type=MediaType.SHOW,
        title="Show",
        year=2001,
        tmdb_id=99,
        youtube_id="abcdefghijk",
        folder_path="/private/show",
    )
    select_art(show, ArtType.POSTER, PublicArtUrl(POSTER))
    db_session.add(show)
    await db_session.flush()
    assert show.id is not None
    season = Season(media_item_id=show.id, season_num=1)
    select_art(season, ArtType.SEASON_POSTER, PublicArtUrl(POSTER))
    db_session.add(season)
    await db_session.commit()

    issue = await item_issue(show.id, database=database)

    assert _query(issue.url) == {
        "template": "show.yml",
        "title": "[Show]: Show (2001)",
        "item_title": "Show",
        "year": "2001",
        "tmdb_id": "99",
        "poster_url": POSTER,
        "youtube_id": "abcdefghijk",
        "season_posters": f"1={POSTER}",
    }
    assert issue.notes == []


async def test_an_item_without_selections_has_no_issue(
    db_session: AsyncSession, database: Database
) -> None:
    movie = MediaItem(media_type=MediaType.MOVIE, title="Movie", tmdb_id=12)
    db_session.add(movie)
    await db_session.commit()
    assert movie.id is not None

    issue = await item_issue(movie.id, database=database)

    assert (issue.url, issue.reason) == (None, "Nothing is selected to contribute")
    with pytest.raises(PublicServiceError, match="Item not found"):
        await item_issue(movie.id + 1, database=database)


async def test_a_collection_issue_needs_its_tmdb_collection(
    db_session: AsyncSession, database: Database
) -> None:
    matched, unmatched = (
        MediaCollection(
            server_item_id=key,
            media_type=MediaType.MOVIE,
            server_type=ServerType.PLEX,
            title="Saga",
            tmdb_collection_id=tmdb_id,
            last_synced_at=utc_now(),
        )
        for key, tmdb_id in (("saga", 10), ("custom", None))
    )
    select_art(matched, ArtType.POSTER, PublicArtUrl(POSTER))
    db_session.add_all([matched, unmatched])
    await db_session.commit()
    assert matched.id is not None
    assert unmatched.id is not None

    query = _query((await collection_issue(matched.id, database=database)).url)
    assert (query["template"], query["title"], query["tmdb_id"]) == (
        "collection.yml",
        "[Collection]: Saga",
        "10",
    )
    assert "year" not in query
    assert (await collection_issue(unmatched.id, database=database)).url is None


def test_a_no_theme_draft_asks_for_the_checkbox_a_link_cannot_tick() -> None:
    issue = contribution_issue(
        {
            "media_type": "movie",
            "title": "Silent",
            "year": 1927,
            "tmdb_id": 5,
            "tvdb_id": None,
            "imdb_id": None,
            "poster_url": None,
            "background_url": None,
            "youtube_id_overturedb": None,
            "youtube_id_themerrdb": None,
            "no_theme": True,
        },
        [],
    )

    assert "no_theme" not in _query(issue.url)
    assert issue.notes == ["Tick No theme on the form"]


def test_a_replacement_names_what_it_replaces_for_its_reason() -> None:
    held = {
        "media_type": "show",
        "title": "Show",
        "year": 2001,
        "tmdb_id": 99,
        "tvdb_id": None,
        "imdb_id": None,
        "poster_url": "https://image.tmdb.org/t/p/original/old.jpg",
        "background_url": "https://image.tmdb.org/t/p/original/back.jpg",
        "youtube_id_overturedb": None,
        "youtube_id_themerrdb": None,
        "seasons": [
            {"season_num": 1, "poster_url": "https://image.tmdb.org/t/p/original/s.jpg"}
        ],
    }
    proposed = {
        **held,
        "poster_url": POSTER,
        "background_url": None,
        "youtube_id_overturedb": "abcdefghijk",
        "seasons": [{"season_num": 1, "poster_url": POSTER}],
    }

    issue = contribution_issue(proposed, [], current=held)

    # A theme OvertureDB lacks is added, and a field left empty replaces nothing.
    assert _query(issue.url)["modification_reason"] == (
        "Replaces the poster, season 1 posters OvertureDB holds, because: "
    )
    assert issue.notes == ["Finish the reason for modification"]
    assert "modification_reason" not in _query(
        contribution_issue(held, [], current=held).url
    )
