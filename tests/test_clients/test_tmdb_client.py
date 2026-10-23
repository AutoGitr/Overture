"""TMDB search, details and collection lookups parse what TMDB returns."""

lazy from typing import Any

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.domain import ArtType, CatalogMediaType, MediaType
lazy from overture.integrations.http import RequestLimiter
lazy from overture.integrations.tmdb import TMDBClient, TmdbSeason
lazy from tests.http_mock import mock_client_factory

IMAGE = "https://image.tmdb.org/t/p/original"


def _client(
    app_config: Settings, routes: dict[str, httpx2.Response]
) -> tuple[TMDBClient, Any]:
    def handler(request: httpx2.Request) -> httpx2.Response:
        return routes.get(request.url.path, httpx2.Response(404))

    factory, transport = mock_client_factory(handler)
    app_config.TMDB_API_KEY = SecretStr("test-key")
    client = TMDBClient(
        app_config=app_config,
        client_factory=factory,
        limiter=RequestLimiter(min_interval=0),
    )
    return client, transport


async def test_search_reads_titles_years_and_posters(app_config: Settings) -> None:
    client, transport = _client(
        app_config,
        {
            "/3/search/movie": httpx2.Response(
                200,
                json={
                    "results": [
                        {
                            "id": 603,
                            "title": "The Matrix",
                            "release_date": "1999-03-31",
                            "poster_path": "/matrix.jpg",
                        },
                        {"id": 9, "title": "Undated", "release_date": ""},
                    ]
                },
            ),
            "/3/search/collection": httpx2.Response(
                200, json={"results": [{"id": 2344, "name": "The Matrix Collection"}]}
            ),
        },
    )

    movies = await client.search("movie", "Matrix")
    collections = await client.search("collection", "Matrix")
    # Searches are cached regardless of letter case.
    await client.search("movie", "matrix")
    await client.close()

    assert [(m.tmdb_id, m.title, m.year, m.poster_url) for m in movies] == [
        (603, "The Matrix", 1999, f"{IMAGE}/matrix.jpg"),
        (9, "Undated", None, None),
    ]
    assert [(c.tmdb_id, c.title) for c in collections] == [
        (2344, "The Matrix Collection")
    ]
    assert transport.call_count == 2
    params = transport.requests[0].url.params
    assert params["query"] == "Matrix"
    assert params["include_adult"] == "false"
    assert params["api_key"] == "test-key"


async def test_show_details_carry_external_ids_and_seasons(
    app_config: Settings,
) -> None:
    client, transport = _client(
        app_config,
        {
            "/3/tv/1399": httpx2.Response(
                200,
                json={
                    "id": 1399,
                    "name": "Game of Thrones",
                    "first_air_date": "2011-04-17",
                    "poster_path": "/got.jpg",
                    "backdrop_path": "/got-bg.jpg",
                    "external_ids": {"tvdb_id": 121361, "imdb_id": "tt0944947"},
                    "seasons": [
                        {"season_number": 0, "name": "Specials", "episode_count": 3},
                        {
                            "season_number": 1,
                            "name": "Season 1",
                            "episode_count": 10,
                            "poster_path": "/s1.jpg",
                        },
                        {"season_number": 9, "name": "Announced", "episode_count": 0},
                    ],
                },
            )
        },
    )

    details = await client.get_details(MediaType.SHOW, 1399)
    await client.close()

    assert details is not None
    assert transport.last_request.url.params["append_to_response"] == "external_ids"
    assert (details.title, details.year, details.tvdb_id, details.imdb_id) == (
        "Game of Thrones",
        2011,
        121361,
        "tt0944947",
    )
    assert details.background_url == f"{IMAGE}/got-bg.jpg"
    assert details.tracked_seasons == (
        TmdbSeason(season_num=0, title="Specials", episode_count=3, poster_url=None),
        TmdbSeason(
            season_num=1,
            title="Season 1",
            episode_count=10,
            poster_url=f"{IMAGE}/s1.jpg",
        ),
    )


async def test_missing_titles_and_collections_are_none(app_config: Settings) -> None:
    client, _transport = _client(app_config, {})

    assert await client.get_details(MediaType.MOVIE, 1) is None
    assert await client.get_collection(1) is None
    await client.close()


async def test_other_errors_reach_the_caller(app_config: Settings) -> None:
    client, _transport = _client(app_config, {"/3/collection/1": httpx2.Response(401)})

    with pytest.raises(httpx2.HTTPStatusError):
        await client.get_collection(1)
    await client.close()


async def test_collection_lists_its_movies(app_config: Settings) -> None:
    client, _transport = _client(
        app_config,
        {
            "/3/collection/2344": httpx2.Response(
                200,
                json={
                    "id": 2344,
                    "name": "The Matrix Collection",
                    "poster_path": "/collection.jpg",
                    "parts": [
                        {
                            "id": 604,
                            "title": "The Matrix Reloaded",
                            "release_date": "2003-05-15",
                        },
                        {
                            "id": 603,
                            "title": "The Matrix",
                            "release_date": "1999-03-31",
                        },
                    ],
                },
            )
        },
    )

    collection = await client.get_collection(2344)
    await client.close()

    assert collection is not None
    assert collection.summary.poster_url == f"{IMAGE}/collection.jpg"
    assert [part.tmdb_id for part in collection.parts] == [604, 603]


async def test_collection_art_uses_collection_images_and_caches_by_language(
    app_config: Settings,
) -> None:
    client, transport = _client(
        app_config,
        {
            "/3/collection/10/images": httpx2.Response(
                200,
                json={
                    "posters": [
                        {"file_path": "/collection.jpg", "width": 1000, "height": 1500}
                    ],
                    "backdrops": [
                        {"file_path": "/background.jpg", "width": 1920, "height": 1080}
                    ],
                },
            )
        },
    )
    posters = await client.art_candidates(
        CatalogMediaType.COLLECTION, 10, ArtType.POSTER
    )
    backgrounds = await client.art_candidates(
        CatalogMediaType.COLLECTION, 10, ArtType.BACKGROUND
    )
    await client.close()
    assert [poster.url for poster in posters] == [f"{IMAGE}/collection.jpg"]
    assert [background.url for background in backgrounds] == [f"{IMAGE}/background.jpg"]
    assert transport.call_count == 1
