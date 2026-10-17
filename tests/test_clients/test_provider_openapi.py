"""Real client requests and consumed responses conform to the bundled APIs."""

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import ArtType, MediaType, ServerType
lazy from overture.media_servers.emby.client import EmbyClient
lazy from overture.media_servers.jellyfin.client import JellyfinClient
lazy from overture.media_servers.plex.client import PlexClient
lazy from tests.http_mock import mock_client_factory
lazy from tests.provider_specs import ProviderSpec


@pytest.mark.parametrize("client_type", [JellyfinClient, EmbyClient])
async def test_media_browser_consumed_operations(
    client_type: type[JellyfinClient],
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    emby = client_type is EmbyClient
    server_type = ServerType.EMBY if emby else ServerType.JELLYFIN
    prefix = "/reverse/emby" if emby else "/reverse"
    spec = ProviderSpec(server_type, prefix)
    app_config.MEDIA_SERVER = server_type
    app_config.MEDIA_SERVER_URL = "https://server.test/reverse"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("test-token")
    client: JellyfinClient | EmbyClient
    library = {"ItemId": "library", "Name": "Movies", "CollectionType": "movies"}
    movie = {
        "Id": "movie",
        "Name": "Movie",
        "ProductionYear": 2026,
        "ProviderIds": {"Tmdb": "1"},
        "Path": "/media/Movie/Movie.mkv",
        "Etag": "etag",
    }
    season = {"Id": "season", "SeriesId": "show", "IndexNumber": 0, "ChildCount": 1}
    theme = {"Id": "theme", "Name": "Theme", "RunTimeTicks": 30_000_000}
    image = {
        "Url": "https://image.tmdb.org/t/p/original/a.jpg",
        "ProviderName": "TheMovieDb",
        "Width": 100,
        "Height": 150,
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.host == "server.test"
        assert request.url.path.startswith(prefix + "/")
        assert request.headers["Accept"] == "application/json"
        assert all(
            request.headers[key] == value for key, value in client.auth_headers.items()
        )
        assert "test-token" not in str(request.url)
        path = request.url.path.removeprefix(prefix)
        params = request.url.params
        item_path = "/Items/{Id}" if emby else "/Items/{itemId}"
        if path == "/System/Info":
            return spec.response(request, path, {"Id": "server"})
        if path.startswith("/Library/"):
            return spec.response(
                request,
                path,
                {"Items": [library], "TotalRecordCount": 1} if emby else [library],
            )
        if path == "/Items":
            kind = params.get("IncludeItemTypes" if emby else "includeItemTypes")
            ids = params.get("Ids" if emby else "ids")
            rows = (
                [season]
                if kind == "Season"
                else [{"Id": "episode", "SeasonId": "season"}]
                if kind == "Episode"
                else [movie]
                if ids == "movie"
                else [theme]
                if ids
                else [movie, {**movie, "Id": "movie2"}]
            )
            offset = int(params["StartIndex" if emby else "startIndex"])
            # Servers may cap a page below the requested limit.
            return spec.response(
                request,
                path,
                {"Items": rows[offset : offset + 1], "TotalRecordCount": len(rows)},
            )
        if path == "/Shows/show/Seasons":
            template = "/Shows/{Id}/Seasons" if emby else "/Shows/{seriesId}/Seasons"
            return spec.response(
                request, template, {"Items": [season], "TotalRecordCount": 1}
            )
        if path.endswith("/RemoteImages"):
            return spec.response(
                request,
                item_path + "/RemoteImages",
                {"Images": [image, image], "TotalRecordCount": 2},
            )
        if path.endswith("/ThemeSongs"):
            return spec.response(
                request,
                item_path + "/ThemeSongs",
                {"Items": [{"Id": "theme"}], "TotalRecordCount": 1},
            )
        if path.endswith("/Images/Primary"):
            template = (
                "/Items/{Id}/Images/{Type}"
                if emby
                else "/Items/{itemId}/Images/{imageType}"
            )
            return spec.response(request, template)
        if path.endswith("/Refresh"):
            return spec.response(
                request, item_path + "/Refresh", status=200 if emby else 204
            )
        if request.method == "DELETE":
            return spec.response(request, item_path, status=200 if emby else 204)
        return spec.response(
            request, item_path, movie if path.endswith("/movie") else theme
        )

    factory, transport = mock_client_factory(handler)
    client = client_type(app_config=app_config, client_factory=factory)

    try:
        assert await client.test_connection()
        assert await client.get_sections() == [library]
        assert (
            await client.find_item_id(
                MediaItem(media_type=MediaType.MOVIE, title="Movie", tmdb_id=1)
            )
            == "movie"
        )
        pages = client.iter_section_items("library", "Movie")
        assert [item["Id"] async for page in pages for item in page] == [
            "movie",
            "movie2",
        ]
        seasons = client.iter_seasons("library")
        assert [item["Id"] async for page in seasons for item in page] == ["season"]
        assert await client.count_episodes_by_season("library") == {"season": 1}
        assert await client.find_season_id("show", 0) == "season"
        art = await client.get_art_candidates("movie", ArtType.POSTER)
        assert len(art) == 1
        assert art[0].source == "tmdb"
        assert (
            await client.get_active_image_url("movie", ArtType.POSTER)
            == f"https://server.test{prefix}/Items/movie/Images/Primary"
        )
        assert (await client.get_theme_songs("movie"))[0].duration == 3
        assert (await client.get_item("movie"))["Id"] == "movie"
        assert [item["Id"] for item in await client.get_people(["movie"])] == ["movie"]
        await client.refresh_item("movie")
        await client.delete_item("theme")
        assert {request.method for request in transport.requests} == {
            "GET",
            "HEAD",
            "POST",
            "DELETE",
        }
    finally:
        await client.close()


async def test_plex_consumed_operations(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    spec = ProviderSpec("plex", "/reverse")
    app_config.MEDIA_SERVER = ServerType.PLEX
    app_config.MEDIA_SERVER_URL = "https://server.test/reverse"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("test-token")
    row = {
        "ratingKey": "1",
        "title": "Movie",
        "year": 2026,
        "thumb": "/library/metadata/1/thumb",
        "theme": "/library/metadata/1/theme/1",
    }

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["X-Plex-Token"] == "test-token"
        assert request.headers["Accept"] == "application/json"
        assert "test-token" not in str(request.url)
        path = request.url.path.removeprefix("/reverse")
        if path == "/identity":
            return spec.response(
                request, path, {"MediaContainer": {"machineIdentifier": "server"}}
            )
        if path == "/library/sections/all":
            return spec.response(
                request,
                path,
                {
                    "MediaContainer": {
                        "Directory": [{"key": "1", "title": "Movies", "type": "movie"}]
                    }
                },
            )
        if path.startswith("/library/sections/1/"):
            offset = int(request.url.params["X-Plex-Container-Start"])
            rows = [row, {**row, "ratingKey": "2"}]
            template = "/library/sections/{sectionId}/" + path.rsplit("/", 1)[-1]
            response = spec.response(
                request,
                template,
                {"MediaContainer": {"Metadata": rows[offset : offset + 1]}},
            )
            response.headers["X-Plex-Container-Total-Size"] = "2"
            response.headers["X-Plex-Container-Start"] = str(offset)
            return response
        if path == "/library/metadata/1,2":
            assert request.url.params["includeChildren"] == "1"
            season = {"ratingKey": "3", "index": 1, "leafCount": 4}
            return spec.response(
                request,
                "/library/metadata/{ids}",
                {
                    "MediaContainer": {
                        "Metadata": [
                            {
                                **row,
                                "ratingKey": key,
                                "childCount": 1,
                                "Location": [{"path": f"/media/Show {key}"}],
                                "Children": {"size": 1, "Metadata": [season]},
                            }
                            for key in ("1", "2")
                        ]
                    }
                },
            )
        if path == "/library/metadata/1/posters":
            # Plex Web reads a field's candidate listing before a refresh; the
            # bundled spec does not describe the listing routes.
            return httpx2.Response(200, json={"MediaContainer": {"size": 0}})
        if request.method == "GET":
            return spec.response(
                request,
                "/library/metadata/{ids}",
                {"MediaContainer": {"Metadata": [row]}},
            )
        if request.method == "POST":
            # PlexAPI uploads to the plural endpoint; the bundled spec only
            # describes the singular element route used for deletion.
            assert path == "/library/metadata/1/themes"
            assert request.content == b"MP3 bytes"
            assert request.headers["Content-Type"] == "audio/mpeg"
            return httpx2.Response(200)
        template = (
            "/library/metadata/{ids}/{element}"
            if path.endswith("/theme")
            else "/library/metadata/{ids}/refresh"
            if path.endswith("/refresh")
            else "/library/metadata/{ids}"
        )
        return spec.response(request, template)

    factory, transport = mock_client_factory(handler)
    client = PlexClient(app_config=app_config, client_factory=factory)
    monkeypatch.setattr(client, "_resolved_url", app_config.MEDIA_SERVER_URL)

    try:
        assert await client.test_connection()
        assert await client.get_machine_identifier() == "server"
        assert (await client.get_sections())[0]["key"] == "1"
        pages = client.iter_section_items("1")
        assert [item["ratingKey"] async for page in pages for item in page] == [
            "1",
            "2",
        ]
        shows = await client.get_shows_with_seasons(["1", "2"])
        assert [show.get("Location") for show in shows] == [
            [{"path": "/media/Show 1"}],
            [{"path": "/media/Show 2"}],
        ]
        assert [show.get("Children") for show in shows] == [
            {"Metadata": [{"ratingKey": "3", "index": 1, "leafCount": 4}]}
        ] * 2
        assert len(await client.get_collections("1")) == 2
        assert (
            await client.get_art_url("1", "thumb")
            == "https://server.test/reverse/library/metadata/1/thumb"
        )
        assert len(await client.get_theme_songs("1")) == 1
        await client.refresh_item("1", unlock={"thumb"})
        assert (
            await client.upload_collection_theme("1", b"MP3 bytes")
            == "/library/metadata/1/theme/1"
        )
        await client.delete_collection_theme("1")
        assert {request.method for request in transport.requests} == {
            "GET",
            "PUT",
            "POST",
            "DELETE",
        }
    finally:
        await client.close()
