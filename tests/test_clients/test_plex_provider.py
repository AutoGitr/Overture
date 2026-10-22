"""Adapting Plex listings to the shared media-server contract."""

lazy from collections.abc import AsyncIterator
lazy from typing import Any, cast

lazy import pytest

lazy from overture.config import Settings
lazy from overture.domain import ArtType, ImageSize, MediaType, ServerType
lazy from overture.media_servers.adapters import ServerItem, ServerSeason
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.plex import provider as provider_module
lazy from overture.media_servers.plex.client import PlexClient
lazy from overture.media_servers.plex.provider import PlexProvider

BASE = "http://plex.test:32400"


class FakePlexClient:
    """The Plex calls the provider makes, answered from fixed rows."""

    def __init__(
        self,
        *,
        pages: dict[str, list[dict[str, Any]]] | None = None,
        details: list[dict[str, Any]] | None = None,
    ) -> None:
        self.auth_headers = {"X-Plex-Token": "token"}
        self.pages = pages or {}
        self.details = details or []
        self.art_fields: list[tuple[str, str]] = []

    async def get_machine_identifier(self) -> str:
        return "machine"

    async def base_url(self) -> str:
        return BASE

    async def get_sections(self) -> list[dict[str, Any]]:
        return [
            {"key": "1", "type": "movie", "title": "Movies"},
            {"key": "2", "type": "show"},
            {"key": "3", "type": "artist", "title": "Music"},
        ]

    async def iter_section_items(self, section_key: str) -> AsyncIterator[list[Any]]:
        if section_key in self.pages:
            yield self.pages[section_key]

    async def get_shows_with_seasons(
        self, show_keys: list[str]
    ) -> list[dict[str, Any]]:
        return [row for row in self.details if str(row["ratingKey"]) in show_keys]

    async def get_collections(self, section_key: str) -> list[dict[str, Any]]:
        return [{"id": f"collection-{section_key}"}]

    async def get_art_url(self, rating_key: str, field: str) -> str:
        self.art_fields.append((rating_key, field))
        return f"{BASE}/{field}"


def _provider(app_config: Settings, client: FakePlexClient) -> PlexProvider:
    app_config.MEDIA_SERVER = ServerType.PLEX
    app_config.MEDIA_SERVER_URL = BASE
    return PlexProvider(app_config=app_config, client=cast("PlexClient", client))


async def _items(provider: PlexProvider) -> list[ServerItem]:
    return [item async for page in provider.iter_items() for item in page]


async def test_sections_keep_only_movie_and_show_libraries(
    app_config: Settings,
) -> None:
    sections = await _provider(app_config, FakePlexClient()).get_sections()

    assert [(s.key, s.title, s.media_type) for s in sections] == [
        ("1", "Movies", MediaType.MOVIE),
        ("2", "2", MediaType.SHOW),
    ]


async def test_a_movie_row_is_normalised(app_config: Settings) -> None:
    client = FakePlexClient(
        pages={
            "1": [
                {
                    "ratingKey": 10,
                    "title": "Alien",
                    "year": 1979,
                    "Guid": [{"id": "tmdb://348"}, {"id": "imdb://tt0078748"}, {}],
                    "thumb": "/library/metadata/10/thumb/1",
                    "art": f"{BASE}/art.jpg?X-Plex-Token=secret",
                    "Director": [{"tag": "Ridley Scott"}],
                    "studio": "",
                    "Media": [{"Part": [{"file": "/movies/Alien (1979)/alien.mkv"}]}],
                },
                {"ratingKey": "11", "title": "Odd art", "thumb": "relative.jpg"},
            ]
        }
    )

    alien, odd = await _items(_provider(app_config, client))

    assert alien.id == "10"
    assert alien.guids == {"tmdb": "348", "imdb": "tt0078748"}
    assert alien.poster_url == f"{BASE}/library/metadata/10/thumb/1"
    assert alien.background_url == f"{BASE}/art.jpg"
    assert alien.folder_path == "/movies/Alien (1979)"
    assert (alien.director, alien.studio) == ("Ridley Scott", None)
    assert "machine" in alien.server_link
    assert (odd.poster_url, odd.background_url, odd.folder_path) == (None, None, None)


async def test_a_show_gets_its_folder_and_ordered_seasons(app_config: Settings) -> None:
    client = FakePlexClient(
        pages={"2": [{"ratingKey": "20", "title": "Firefly"}]},
        details=[
            {
                "ratingKey": "20",
                "childCount": 2,
                "Location": [{"path": "/shows/Firefly"}],
                "Children": {
                    "Metadata": [
                        {"ratingKey": "22", "index": 1, "leafCount": 14},
                        {"ratingKey": "21", "index": 0, "leafCount": 3, "thumb": "/s0"},
                    ]
                },
            }
        ],
    )

    [show] = await _items(_provider(app_config, client))

    assert show.folder_path == "/shows/Firefly"
    assert show.seasons == [
        ServerSeason(
            num=0,
            title="Specials",
            file_count=3,
            poster_url=f"{BASE}/s0",
            server_item_id="21",
        ),
        ServerSeason(num=1, title="Season 1", file_count=14, server_item_id="22"),
    ]


INCOMPLETE_SHOWS: list[tuple[list[dict[str, Any]], str]] = [
    ([], "did not return a listed show"),
    (
        [{"ratingKey": "20", "childCount": 2, "Children": {"Metadata": []}}],
        "incomplete season list",
    ),
    (
        [
            {
                "ratingKey": "20",
                "childCount": 1,
                "Children": {"Metadata": [{"ratingKey": "21", "index": 1}]},
            }
        ],
        "season without its episode count",
    ),
]


@pytest.mark.parametrize(("details", "message"), INCOMPLETE_SHOWS)
async def test_an_incomplete_show_fails_the_listing(
    app_config: Settings, details: list[dict[str, Any]], message: str
) -> None:
    client = FakePlexClient(pages={"2": [{"ratingKey": "20"}]}, details=details)

    with pytest.raises(MediaServerError, match=message):
        await _items(_provider(app_config, client))


async def test_a_show_with_too_many_seasons_fails_the_listing(
    app_config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provider_module, "MAX_SEASONS_PER_SHOW", 1)
    seasons = [{"ratingKey": str(n), "index": n, "leafCount": 1} for n in (1, 2)]
    client = FakePlexClient(
        pages={"2": [{"ratingKey": "20"}]},
        details=[
            {"ratingKey": "20", "childCount": 2, "Children": {"Metadata": seasons}}
        ],
    )

    with pytest.raises(MediaServerError, match="too many seasons"):
        await _items(_provider(app_config, client))


async def test_sized_art_goes_through_the_transcoder_in_the_slot_shape(
    app_config: Settings,
) -> None:
    provider = _provider(app_config, FakePlexClient())

    original = await provider.build_provider_art_request("10", ArtType.POSTER, None)
    background = await provider.build_provider_art_request(
        "10", ArtType.BACKGROUND, ImageSize.DISPLAY
    )

    assert (original.url, original.params) == (
        f"{BASE}/library/metadata/10/thumb",
        None,
    )
    assert original.headers == {"X-Plex-Token": "token"}
    assert background.url == f"{BASE}/photo/:/transcode"
    assert background.params is not None
    width, height = int(background.params["width"]), int(background.params["height"])
    assert background.params["url"] == "/library/metadata/10/art"
    assert height == width * 9 // 16


async def test_active_art_is_read_from_the_field_holding_it(
    app_config: Settings,
) -> None:
    client = FakePlexClient()
    provider = _provider(app_config, client)

    await provider.get_active_art_url("10", ArtType.BACKGROUND)
    await provider.get_active_art_url("10", ArtType.SEASON_POSTER)

    assert client.art_fields == [("10", "art"), ("10", "thumb")]


async def test_collections_are_listed_from_libraries_of_the_media_type(
    app_config: Settings,
) -> None:
    provider = _provider(app_config, FakePlexClient())

    assert await provider.list_collections(MediaType.SHOW) == [
        {"id": "collection-2", "media_type": MediaType.SHOW, "server_type": "plex"}
    ]
