"""Season file_count must come from each provider's reliable count source."""

lazy from collections import Counter
lazy from collections.abc import AsyncIterator, Callable
lazy from datetime import UTC, datetime
lazy from typing import Any, cast

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.media_servers.emby import EmbyProvider
lazy from overture.media_servers.emby.client import EmbyClient
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.jellyfin.client import JellyfinClient
lazy from overture.media_servers.jellyfin.provider import JellyfinProvider
lazy from overture.media_servers.plex.client import PlexClient
lazy from overture.media_servers.plex.provider import PlexProvider
lazy from tests.http_mock import mock_client_factory


def _complete_listing(response: httpx2.Response) -> httpx2.Response:
    """Give mocked item pages the total required for safe reconciliation."""
    if response.status_code != 200:
        return response
    raw: object = response.json()
    if not isinstance(raw, dict):
        return response
    payload = cast("dict[str, Any]", raw)
    container = payload.get("MediaContainer")
    if isinstance(container, dict):
        complete = cast("dict[str, Any]", container)
        metadata = complete.get("Metadata")
        if not isinstance(metadata, list):
            return response
        complete.setdefault("totalSize", len(cast("list[object]", metadata)))
    elif isinstance(payload.get("Items"), list):
        payload.setdefault("TotalRecordCount", len(payload["Items"]))
    else:
        return response
    return httpx2.Response(response.status_code, json=payload, headers=response.headers)


def _plex_handler(
    *, show_updated_at: int | None = None, child_count: int = 2
) -> Callable[[httpx2.Request], httpx2.Response]:
    """Serve one movie section and one show section; details come in batch."""

    def show_details(key: str) -> dict[str, Any]:
        seasons = [
            {"ratingKey": "200", "index": 2, "title": "Season 2", "leafCount": 1},
            {"ratingKey": "201", "index": 1, "title": "Season 1", "leafCount": 3},
        ]
        if key == "101":
            return {"ratingKey": "101", "childCount": 0}
        return {
            "ratingKey": "100",
            "childCount": child_count,
            "Location": [{"path": "/media/shows/Show"}],
            "Children": {"size": 2, "Metadata": seasons},
        }

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        params = request.url.params

        if path == "/identity":
            return httpx2.Response(
                200, json={"MediaContainer": {"machineIdentifier": "m1"}}
            )
        if request.url.host == "plex.tv":
            return httpx2.Response(200, json=[])
        if path == "/library/sections/all":
            return httpx2.Response(
                200,
                json={
                    "MediaContainer": {
                        "Directory": [
                            {"key": "1", "type": "show"},
                            {"key": "2", "type": "movie"},
                        ]
                    }
                },
            )
        if path == "/library/sections/2/all":
            return httpx2.Response(
                200,
                json={
                    "MediaContainer": {
                        "Metadata": [
                            {
                                "ratingKey": "50",
                                "title": "Movie",
                                "Guid": [],
                                "addedAt": 1_000,
                                "Media": [
                                    {
                                        "Part": [
                                            {"file": ("/media/movies/Movie/Movie.mkv")}
                                        ]
                                    }
                                ],
                            }
                        ]
                    }
                },
            )
        if path == "/library/sections/1/all":
            return httpx2.Response(
                200,
                json={
                    "MediaContainer": {
                        "Metadata": [
                            {
                                "ratingKey": "100",
                                "title": "Show",
                                "Guid": [],
                                "addedAt": 1_000,
                                "updatedAt": show_updated_at,
                            },
                            {"ratingKey": "101", "title": "Empty", "addedAt": 1_000},
                        ]
                    }
                },
            )
        if path.startswith("/library/metadata/"):
            assert params.get("includeChildren") == "1"
            keys = path.removeprefix("/library/metadata/").split(",")
            return httpx2.Response(
                200,
                json={"MediaContainer": {"Metadata": [show_details(k) for k in keys]}},
            )
        return httpx2.Response(404, json={})

    return handler


def _plex_provider(
    app_config: Settings, handler: Callable[[httpx2.Request], httpx2.Response]
) -> tuple[PlexProvider, list[httpx2.Request]]:
    app_config.MEDIA_SERVER_URL = "http://plex.test:32400"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("token")
    factory, transport = mock_client_factory(
        lambda request: _complete_listing(handler(request))
    )
    provider = PlexProvider(
        app_config=app_config,
        client=PlexClient(app_config=app_config, client_factory=factory),
    )
    return provider, transport.requests


async def test_plex_reads_show_folders_and_seasons_in_one_request_per_page(
    *,
    app_config: Settings,
) -> None:
    provider, requests = _plex_provider(app_config, _plex_handler())
    items = [item async for page in provider.iter_items(["2", "1"]) for item in page]

    assert [item.id for item in items] == ["50", "100", "101"]
    movie, show, empty = items
    assert movie.folder_path == "/media/movies/Movie"
    assert show.folder_path == "/media/shows/Show"
    assert [(s.num, s.file_count, s.server_item_id) for s in show.seasons] == [
        (1, 3, "201"),
        (2, 1, "200"),
    ]
    assert empty.folder_path is None
    assert empty.seasons == []
    details = [r.url.path for r in requests if r.url.path.startswith("/library/meta")]
    assert details == ["/library/metadata/100,101"]


async def test_plex_rejects_a_shortened_season_list(
    *,
    app_config: Settings,
) -> None:
    provider, _ = _plex_provider(app_config, _plex_handler(child_count=3))

    with pytest.raises(MediaServerError, match="incomplete season list"):
        async for _ in provider.iter_items(["1"]):
            pass


async def test_plex_poll_reads_details_of_changed_shows_only(
    *,
    app_config: Settings,
) -> None:
    provider, requests = _plex_provider(
        app_config, _plex_handler(show_updated_at=3_000)
    )
    since = datetime.fromtimestamp(2_000, UTC)
    items = [
        item
        async for page in provider.iter_items_since(since, ["2", "1"])
        for item in page
    ]

    assert [item.id for item in items] == ["100"]
    assert [season.num for season in items[0].seasons] == [1, 2]
    assert items[0].folder_path == "/media/shows/Show"
    details = [r.url.path for r in requests if r.url.path.startswith("/library/meta")]
    assert details == ["/library/metadata/100"]


async def test_jellyfin_reads_seasons_and_episode_counts_once_per_library(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    app_config.MEDIA_SERVER_URL = "http://jellyfin.test"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("token")

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        params = request.url.params

        if path == "/Library/VirtualFolders":
            return httpx2.Response(
                200,
                json=[
                    {
                        "ItemId": "lib1",
                        "Name": "Shows",
                        "CollectionType": "tvshows",
                    },
                    {
                        "ItemId": "lib2",
                        "Name": "Movies",
                        "CollectionType": "movies",
                    },
                ],
            )
        if path == "/Items":
            if params.get("ids") == "movie1,movie2":
                assert params.get("fields") == "People"
                assert params.get("enableImages") == "false"
                assert params.get("enableUserData") == "false"
                return httpx2.Response(
                    200,
                    json={
                        "Items": [
                            {
                                "Id": "movie1",
                                "People": [
                                    {"Name": "Jonathan Pryce", "Type": "Actor"},
                                    {"Name": "Terry Gilliam", "Type": "Director"},
                                ],
                            },
                            {"Id": "movie2", "People": []},
                        ]
                    },
                )
            include_types = params.get("includeItemTypes")
            if include_types == "Season":
                assert params.get("parentId") == "lib1"
                assert "fields" not in params
                return httpx2.Response(
                    200,
                    json={
                        "Items": [
                            {
                                "Id": "s1",
                                "SeriesId": "show1",
                                "IndexNumber": 1,
                                "Name": "Season 1",
                            },
                            {
                                "Id": "s2",
                                "SeriesId": "show1",
                                "IndexNumber": 2,
                                "Name": "Season 2",
                            },
                        ]
                    },
                )
            if include_types == "Episode":
                assert params.get("parentId") == "lib1"
                assert params.get("limit") == "5000"
                seasons = ["s1", "s1", "s1", "s2", None]
                return httpx2.Response(
                    200,
                    json={
                        "Items": [
                            {"Id": f"e{index}", "SeasonId": season}
                            for index, season in enumerate(seasons)
                        ]
                    },
                )
            if include_types == "Movie":
                assert params.get("fields") == (
                    "Genres,ProviderIds,Path,Studios,DateCreated,DateLastMediaAdded,"
                    "Tags,ProductionLocations,Width,Etag"
                )
            else:
                assert params.get("fields") == (
                    "Genres,ProviderIds,Path,Studios,DateCreated,DateLastMediaAdded,"
                    "Tags,ProductionLocations,Width"
                )
            assert params.get("enableUserData") == "false"
            if params.get("parentId") == "lib2":
                assert include_types == "Movie"
                return httpx2.Response(
                    200,
                    json={
                        "Items": [
                            {
                                "Id": "movie1",
                                "Name": "Movie",
                                "Path": "/media/movies/Movie/Movie.mkv",
                                "IsFolder": False,
                                "Etag": "movie-etag",
                                "ImageTags": {"Primary": "poster-tag"},
                                "BackdropImageTags": ["background-tag"],
                            }
                        ]
                    },
                )
            assert include_types == "Series"
            return httpx2.Response(
                200, json={"Items": [{"Id": "show1", "Name": "Show"}]}
            )
        return httpx2.Response(404, json={})

    factory, transport = mock_client_factory(
        lambda request: _complete_listing(handler(request))
    )
    provider = JellyfinProvider(
        app_config=app_config,
        client=JellyfinClient(app_config=app_config, client_factory=factory),
    )
    items = [
        item async for page in provider.iter_items(["lib2", "lib1"]) for item in page
    ]

    assert transport.called

    assert [item.id for item in items] == ["movie1", "show1"]
    assert items[0].folder_path == "/media/movies/Movie"
    assert items[0].poster_url == (
        "http://jellyfin.test/Items/movie1/Images/Primary?tag=poster-tag"
    )
    assert items[0].background_url == (
        "http://jellyfin.test/Items/movie1/Images/Backdrop"
    )
    assert items[0].director is None
    assert items[0].director_etag == "movie-etag"
    assert items[1].director_etag is None
    seasons = {season.num: season for season in items[1].seasons}
    assert seasons[1].file_count == 3
    assert seasons[2].file_count == 1
    listed = [r.url.params.get("includeItemTypes") for r in transport.requests]
    assert listed.count("Season") == listed.count("Episode") == 1
    assert await provider.get_directors(["movie1", "movie2"]) == {
        "movie1": "Terry Gilliam",
        "movie2": None,
    }


async def test_jellyfin_poll_reads_seasons_of_changed_shows_only(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    provider = JellyfinProvider(app_config=app_config)
    season_parents: list[str] = []
    count_parents: list[str] = []

    async def sections() -> list[dict[str, Any]]:
        return [{"ItemId": "lib1", "CollectionType": "tvshows"}]

    async def seasons(parent_id: str) -> AsyncIterator[list[dict[str, Any]]]:
        season_parents.append(parent_id)
        yield [
            {
                "Id": f"{parent_id}-s1",
                "SeriesId": parent_id,
                "IndexNumber": 1,
            }
        ]

    async def episode_counts(parent_id: str) -> Counter[str]:
        count_parents.append(parent_id)
        return Counter({f"{parent_id}-s1": 5})

    async def items(
        _section_id: str, _item_type: str
    ) -> AsyncIterator[list[dict[str, Any]]]:
        yield [
            {"Id": "old", "Name": "Old", "DateCreated": "2026-01-01T00:00:00Z"},
            {
                "Id": "new",
                "Name": "New",
                "DateCreated": "2026-01-01T00:00:00Z",
                "DateLastMediaAdded": "2026-03-01T00:00:00Z",
            },
        ]

    monkeypatch.setattr(provider.client, "get_sections", sections)
    monkeypatch.setattr(provider.client, "iter_seasons", seasons)
    monkeypatch.setattr(provider.client, "count_episodes_by_season", episode_counts)
    monkeypatch.setattr(provider.client, "iter_section_items", items)

    since = datetime(2026, 2, 1, tzinfo=UTC)
    result = [item async for page in provider.iter_items_since(since) for item in page]

    assert [item.id for item in result] == ["new"]
    assert [season.file_count for season in result[0].seasons] == [5]
    assert season_parents == count_parents == ["new"]


async def test_emby_uses_prefixed_api_and_real_episode_counts(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    app_config.MEDIA_SERVER_URL = "http://emby.test:8096"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("token")

    def handler(request: httpx2.Request) -> httpx2.Response:
        path = request.url.path
        params = request.url.params
        assert request.headers["X-Emby-Token"] == "token"

        if path == "/emby/System/Info":
            return httpx2.Response(200, json={"Id": "server-1"})
        if path == "/emby/Library/VirtualFolders/Query":
            return httpx2.Response(
                200,
                json={
                    "Items": [
                        {
                            "ItemId": "lib1",
                            "Name": "Shows",
                            "CollectionType": "tvshows",
                        },
                        {
                            "ItemId": "lib2",
                            "Name": "Movies",
                            "CollectionType": "movies",
                        },
                    ]
                },
            )
        if path == "/emby/Items":
            if params.get("Ids") == "movie1":
                assert params.get("Fields") == "People"
                assert params.get("EnableImages") == "false"
                assert params.get("EnableUserData") == "false"
                return httpx2.Response(
                    200,
                    json={
                        "Items": [
                            {
                                "Id": "movie1",
                                "People": [
                                    {"Name": "John Carpenter", "Type": "Director"}
                                ],
                            }
                        ]
                    },
                )
            include_types = params.get("IncludeItemTypes")
            if include_types == "Season":
                assert params.get("EnableImages") == "true"
                assert params.get("ParentId") == "lib1"
                assert params.get("EnableImageTypes") == "Primary"
                return httpx2.Response(
                    200,
                    json={
                        "Items": [
                            {
                                "Id": "s1",
                                "SeriesId": "show1",
                                "IndexNumber": 1,
                                "Name": "Season 1",
                            }
                        ]
                    },
                )
            if include_types == "Episode":
                assert params.get("EnableImages") == "false"
                assert params.get("ParentId") == "lib1"
                assert params.get("Limit") == "5000"
                assert params.get("EnableUserData") == "false"
                return httpx2.Response(
                    200,
                    json={"Items": [{"Id": "e1", "SeasonId": "s1"}]},
                )
            if include_types == "Movie":
                assert params.get("Fields") == (
                    "ProviderIds,Path,Studios,Genres,DateCreated,ProductionYear,Etag"
                )
            else:
                assert params.get("Fields") == (
                    "ProviderIds,Path,Studios,Genres,DateCreated,ProductionYear"
                )
            assert params.get("EnableUserData") == "false"
            assert params.get("EnableImages") == "true"
            assert params.get("EnableImageTypes") == "Primary,Backdrop"
            assert include_types in {"Movie", "Series"}
            if params.get("ParentId") == "lib2":
                assert include_types == "Movie"
                return httpx2.Response(
                    200,
                    json={
                        "Items": [
                            {
                                "Id": "movie1",
                                "Name": "Movie",
                                "ProductionYear": 1982,
                                "Path": "/media/movies/Movie/Movie.mkv",
                                "IsFolder": False,
                                "Etag": "movie-etag",
                            }
                        ]
                    },
                )
            assert include_types == "Series"
            return httpx2.Response(
                200,
                json={
                    "Items": [
                        {
                            "Id": "show1",
                            "Name": "Show",
                            "ProductionYear": 2024,
                            "Path": "/media/shows/Show",
                            "ImageTags": {"Primary": "poster-tag"},
                            "BackdropImageTags": ["background-tag"],
                        }
                    ]
                },
            )
        return httpx2.Response(404, json={})

    factory, transport = mock_client_factory(
        lambda request: _complete_listing(handler(request))
    )
    provider = EmbyProvider(
        app_config=app_config,
        client=EmbyClient(app_config=app_config, client_factory=factory),
    )
    items = [
        item async for page in provider.iter_items(["lib2", "lib1"]) for item in page
    ]

    assert transport.called

    assert [item.id for item in items] == ["movie1", "show1"]
    movie, show = items
    assert show.year == 2024
    assert show.folder_path == "/media/shows/Show"
    assert show.poster_url == (
        "http://emby.test:8096/emby/Items/show1/Images/Primary?Tag=poster-tag"
    )
    assert show.background_url == (
        "http://emby.test:8096/emby/Items/show1/Images/Backdrop"
    )
    assert show.server_link == (
        "http://emby.test:8096/web/index.html#!/item?id=show1&serverId=server-1"
    )
    assert show.seasons[0].file_count == 1
    assert movie.year == 1982
    assert movie.folder_path == "/media/movies/Movie"
    assert movie.director is None
    assert movie.director_etag == "movie-etag"
    assert show.director_etag is None
    assert await provider.get_directors(["movie1"]) == {"movie1": "John Carpenter"}
    assert movie.server_link.endswith("item?id=movie1&serverId=server-1")


async def test_people_lookups_keep_their_urls_short(*, app_config: Settings) -> None:
    app_config.MEDIA_SERVER_URL = "http://jellyfin.test"

    def handler(request: httpx2.Request) -> httpx2.Response:
        ids = request.url.params["ids"].split(",")
        return httpx2.Response(
            200,
            json={"Items": [{"Id": i} for i in ids], "TotalRecordCount": len(ids)},
        )

    factory, transport = mock_client_factory(handler)
    client = JellyfinClient(app_config=app_config, client_factory=factory)
    ids = [f"{index:032x}" for index in range(250)]
    try:
        items = await client.get_people(ids)
    finally:
        await client.close()

    assert [item["Id"] for item in items] == ids
    sizes = [len(r.url.params["ids"].split(",")) for r in transport.requests]
    assert sizes == [100, 100, 50]
