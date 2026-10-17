"""The Plex client against a scripted Plex server."""

lazy from collections.abc import AsyncIterator, Callable
lazy from typing import Any

lazy import httpx2
lazy import pytest
lazy from blake3 import blake3

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import MediaType, ServerType
lazy from overture.media_servers.adapters import ServerTheme
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.plex import client as plex_module
lazy from overture.media_servers.plex.client import PlexClient
lazy from tests.http_mock import RecordingMockTransport, mock_client_factory

THEME = b"theme audio"

type Route = Callable[[httpx2.Request], httpx2.Response]


def _container(key: str, rows: list[dict[str, Any]]) -> httpx2.Response:
    return httpx2.Response(
        200,
        json={"MediaContainer": {key: rows, "size": len(rows), "totalSize": len(rows)}},
    )


def _metadata(*rows: dict[str, Any]) -> httpx2.Response:
    return _container("Metadata", list(rows))


SECTIONS = _container(
    "Directory",
    [
        {"key": "1", "type": "movie", "title": "Movies"},
        {"key": "2", "type": "show", "title": "Shows"},
    ],
)


@pytest.fixture
def routes() -> dict[str, Route]:
    """What the scripted server answers, by path; a test may change it."""
    return {
        "/identity": lambda _r: httpx2.Response(
            200, json={"MediaContainer": {"machineIdentifier": "machine-1"}}
        ),
        "/library/sections/all": lambda _r: SECTIONS,
        "/library/sections/1/all": lambda request: (
            _metadata(
                {
                    "ratingKey": "10",
                    "title": "Alien",
                    "Guid": [{"id": "imdb://tt0078748"}],
                },
                {"ratingKey": "11", "title": "Alien", "Guid": [{"id": "tmdb://999"}]},
            )
            if request.url.params.get("title") == "Alien"
            else _metadata()
        ),
        "/library/metadata/20/children": lambda _r: _metadata(
            {"ratingKey": "21", "index": 0}, {"ratingKey": "22", "index": 1}
        ),
        "/library/metadata/10": lambda _r: _metadata(
            {"ratingKey": "10", "theme": "/t/1"}
        ),
        "/library/metadata/11": lambda _r: _metadata({"ratingKey": "11"}),
        "/library/metadata/10/theme": lambda _r: httpx2.Response(200, content=THEME),
    }


@pytest.fixture
async def plex(
    app_config: Settings, monkeypatch: pytest.MonkeyPatch, routes: dict[str, Route]
) -> AsyncIterator[tuple[PlexClient, RecordingMockTransport]]:
    app_config.MEDIA_SERVER = ServerType.PLEX
    app_config.MEDIA_SERVER_URL = "http://plex.test:32400"

    async def no_secure_url(_client: PlexClient) -> None:
        return None

    monkeypatch.setattr(PlexClient, "resolve_secure_url", no_secure_url)
    factory, transport = mock_client_factory(
        lambda request: routes.get(request.url.path, lambda _r: httpx2.Response(404))(
            request
        )
    )
    client = PlexClient(app_config=app_config, client_factory=factory)
    yield client, transport
    await client.close()


def _movie(**ids: Any) -> MediaItem:
    return MediaItem(id=1, media_type=MediaType.MOVIE, title="Alien", **ids)


async def test_an_item_is_found_by_any_of_its_ids_in_libraries_of_its_type(
    plex: tuple[PlexClient, RecordingMockTransport],
) -> None:
    client, transport = plex

    assert await client.find_item_id(_movie(tmdb_id=999)) == "11"
    assert await client.find_item_id(_movie(tmdb_id=999)) == "11"
    assert await client.find_item_id(_movie(imdb_id="tt0078748")) == "10"
    assert await client.find_item_id(_movie(tmdb_id=1)) is None

    searched = [
        request.url.path
        for request in transport.requests
        if request.url.path.startswith("/library/sections/")
        and request.url.path != "/library/sections/all"
    ]
    # The repeated lookup is answered from memory; shows are never searched.
    assert searched == ["/library/sections/1/all"] * 3


async def test_a_season_is_found_by_its_number(
    plex: tuple[PlexClient, RecordingMockTransport],
) -> None:
    client, _ = plex

    assert await client.find_season_id("20", 1) == "22"
    assert await client.find_season_id("20", 7) is None


async def test_an_item_plays_its_theme_from_the_server_origin(
    plex: tuple[PlexClient, RecordingMockTransport],
) -> None:
    client, _ = plex

    assert await client.get_theme_songs("10") == [
        ServerTheme(id="10", url="http://plex.test:32400/library/metadata/10/theme")
    ]
    assert await client.get_theme_songs("11") == []


async def test_a_collection_theme_is_verified_by_the_hash_of_what_plex_serves(
    plex: tuple[PlexClient, RecordingMockTransport],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = plex

    assert (
        await client.verify_collection_theme("10", blake3(THEME).hexdigest()) == "/t/1"
    )
    assert await client.verify_collection_theme("10", "another file") is None
    assert await client.verify_collection_theme("11", "any") is None

    monkeypatch.setattr(plex_module, "MAX_REMOTE_AUDIO_BYTES", len(THEME) - 1)
    with pytest.raises(MediaServerError, match="exceeds size limit"):
        await client.verify_collection_theme("10", "any")


async def test_the_connection_test_reads_the_server_identity(
    plex: tuple[PlexClient, RecordingMockTransport],
) -> None:
    client, _ = plex

    assert await client.test_connection()
    assert await client.get_machine_identifier() == "machine-1"


async def test_an_unreachable_server_fails_the_connection_test(
    plex: tuple[PlexClient, RecordingMockTransport], routes: dict[str, Route]
) -> None:
    client, _ = plex
    routes["/identity"] = lambda _r: httpx2.Response(500)

    assert not await client.test_connection()
    assert await client.get_machine_identifier() is None


@pytest.mark.parametrize(
    ("headers", "message"),
    [
        ({"X-Plex-Container-Total-Size": "many"}, "invalid pagination headers"),
        ({"X-Plex-Container-Total-Size": "5"}, "conflicting pagination metadata"),
    ],
)
async def test_pagination_headers_must_agree_with_the_listing(
    app_config: Settings,
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    message: str,
) -> None:
    async def no_secure_url(_client: PlexClient) -> None:
        return None

    monkeypatch.setattr(PlexClient, "resolve_secure_url", no_secure_url)
    rows = [{"key": "1", "type": "movie"}]
    factory, _ = mock_client_factory(
        lambda _r: httpx2.Response(
            200,
            headers=headers,
            json={"MediaContainer": {"Directory": rows, "size": 1, "totalSize": 1}},
        )
    )
    client = PlexClient(app_config=app_config, client_factory=factory)

    with pytest.raises(MediaServerError, match=message):
        await client.get_sections()
    await client.close()


@pytest.mark.parametrize(
    "thumb",
    ["ftp://plex.test/thumb", "http://user@plex.test/thumb", "https:///thumb"],
)
async def test_an_art_url_must_be_a_plain_web_address(
    plex: tuple[PlexClient, RecordingMockTransport],
    routes: dict[str, Route],
    thumb: str,
) -> None:
    client, _ = plex
    routes["/library/metadata/30"] = lambda _r: _metadata(
        {"ratingKey": "30", "thumb": thumb}
    )

    with pytest.raises(MediaServerError, match="invalid asset URL"):
        await client.get_art_url("30", "thumb")
