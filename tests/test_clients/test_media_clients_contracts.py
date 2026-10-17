"""Plex, Jellyfin, TMDB, proxy, and provider contract tests."""

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.domain import ArtType, ImageSize, MediaType, ServerAsset, ServerType
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import extract_art
lazy from overture.media_servers.adapters import ServerItem, ServerTheme
lazy from overture.media_servers.emby import EmbyClient, EmbyProvider
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from overture.media_servers.jellyfin.client import JellyfinClient
lazy from overture.media_servers.plex import PlexProvider
lazy from overture.media_servers.plex.client import (
    PlexClient,
    plex_web_link,
)
lazy from overture.media_servers.registry import ProviderRegistry
lazy from overture.schemas.art import ArtCandidate
lazy from tests.http_mock import mock_client_factory


def _normalised_base_url(client: httpx2.AsyncClient) -> str:
    return f"{str(client.base_url).rstrip('/')}/"


def test_plex_deep_links_encode_metadata_and_collection_keys(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER_URL = "http://plex.local:32400"

    assert (
        plex_web_link("metadata", "123", "machine", app_config=app_config)
        == "https://app.plex.tv/desktop/#!/server/machine/details?key=%2Flibrary%2Fmetadata%2F123"
    )
    assert (
        plex_web_link("collections", "456", None, app_config=app_config)
        == "http://plex.local:32400/web/index.html"
        "#!/server/details?key=%2Flibrary%2Fcollections%2F456"
    )


def test_plex_connection_normalization_rejects_lookalikes_and_url_content(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER = ServerType.PLEX

    assert (
        app_config.plex_direct_origin("https://server.example.plex.direct:32400/")
        == "https://server.example.plex.direct:32400"
    )
    assert (
        app_config.plex_direct_origin("http://server.example.plex.direct:32400") == ""
    )
    assert app_config.plex_direct_origin("https://plex.direct:32400") == ""
    assert (
        app_config.plex_direct_origin("https://server.plex.direct.attacker.test:32400")
        == ""
    )
    assert app_config.plex_direct_origin("https://server.plex.direct:32400/path") == ""
    assert (
        app_config.plex_direct_origin("https://server.plex.direct:32400?token=x") == ""
    )


async def test_plex_secure_origin_is_machine_verified_before_it_is_trusted(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    configured = "http://plex.test:32400"
    secure = "https://server.example.plex.direct:32400"
    app_config.MEDIA_SERVER = ServerType.PLEX
    app_config.MEDIA_SERVER_URL = configured
    app_config.MEDIA_SERVER_API_KEY = SecretStr("plex-token")

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url).rstrip("/")
        if url == f"{configured}/identity":
            return httpx2.Response(
                200,
                json={"MediaContainer": {"machineIdentifier": "machine-1"}},
            )
        if url == "https://plex.tv/api/v2/resources?includeHttps=1":
            return httpx2.Response(
                200,
                json=[
                    {
                        "provides": "server",
                        "clientIdentifier": "other-machine",
                        "connections": [{"uri": secure}],
                    },
                    {
                        "provides": "server,client",
                        "clientIdentifier": "machine-1",
                        "connections": [
                            {"uri": "https://server.plex.direct.attacker.test:32400"},
                            {"uri": secure},
                        ],
                    },
                ],
            )
        if url == f"{secure}/identity":
            assert "X-Plex-Token" not in request.headers
            return httpx2.Response(
                200,
                json={"MediaContainer": {"machineIdentifier": "machine-1"}},
            )
        return httpx2.Response(404)

    factory, transport = mock_client_factory(handler)

    resolved = await PlexClient(
        app_config=app_config,
        client_factory=factory,
    ).resolve_secure_url()

    assert resolved == secure
    assert transport.called
    assert app_config.is_trusted_media_server_url(f"{secure}/library/metadata/1")
    assert not app_config.is_trusted_media_server_url(
        "https://another.example.plex.direct:32400/library/metadata/1"
    )


@pytest.mark.parametrize("candidate_status", [200, 302])
async def test_plex_secure_origin_rejects_a_machine_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch, candidate_status: int, *, app_config: Settings
) -> None:
    configured = "http://plex.test:32400"
    secure = "https://server.example.plex.direct:32400"
    app_config.MEDIA_SERVER = ServerType.PLEX
    app_config.MEDIA_SERVER_URL = configured
    app_config.MEDIA_SERVER_API_KEY = SecretStr("plex-token")

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.host != "attacker.test"
        url = str(request.url).rstrip("/")
        if url == f"{configured}/identity":
            machine = "machine-1"
            return httpx2.Response(
                200, json={"MediaContainer": {"machineIdentifier": machine}}
            )
        if url == "https://plex.tv/api/v2/resources?includeHttps=1":
            return httpx2.Response(
                200,
                json=[
                    {
                        "provides": "server",
                        "clientIdentifier": "machine-1",
                        "connections": [{"uri": secure}],
                    }
                ],
            )
        if url == f"{secure}/identity":
            assert "X-Plex-Token" not in request.headers
            return httpx2.Response(
                candidate_status,
                headers={"Location": "https://attacker.test/identity"},
                json={"MediaContainer": {"machineIdentifier": "machine-2"}},
            )
        return httpx2.Response(404)

    factory, transport = mock_client_factory(handler)

    assert (
        await PlexClient(
            app_config=app_config,
            client_factory=factory,
        ).resolve_secure_url()
        is None
    )
    assert transport.called
    assert not app_config.is_trusted_media_server_url(f"{secure}/library/metadata/1")


def test_tmdb_extract_art_sorts_by_area_and_builds_preview_urls(
    *, app_config: Settings
) -> None:
    art = extract_art(
        {
            "posters": [
                {"file_path": "/small.jpg", "width": 100, "height": 150},
                {"file_path": "/large.jpg", "width": 1000, "height": 1500},
            ]
        },
        ArtType.POSTER,
    )

    assert [item.url for item in art] == [
        "https://image.tmdb.org/t/p/original/large.jpg",
        "https://image.tmdb.org/t/p/original/small.jpg",
    ]
    assert art[0].preview_url == "https://image.tmdb.org/t/p/w342/large.jpg"
    assert art[0].source == "tmdb"


async def test_jellyfin_client_builds_auth_headers(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER_URL = "http://jellyfin.test"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("jf-token")

    client = JellyfinClient(app_config=app_config)
    http_client = await client.get_client()
    try:
        assert _normalised_base_url(http_client) == "http://jellyfin.test/"
        assert http_client.headers["Authorization"] == 'MediaBrowser Token="jf-token"'
        assert "X-Emby-Token" not in http_client.headers
        assert http_client.headers["Accept"] == "application/json"
    finally:
        await client.close()


async def test_emby_client_builds_prefixed_api_url_and_auth_headers(
    *,
    app_config: Settings,
) -> None:
    app_config.MEDIA_SERVER_URL = "http://emby.test:8096"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("emby-token")

    client = EmbyClient(app_config=app_config)
    http_client = await client.get_client()
    try:
        assert _normalised_base_url(http_client) == "http://emby.test:8096/emby/"
        assert http_client.headers["X-Emby-Token"] == "emby-token"
        assert "Authorization" not in http_client.headers
        assert http_client.headers["Accept"] == "application/json"
    finally:
        await client.close()

    app_config.MEDIA_SERVER_URL = "http://emby.test:8096/emby"
    prefixed = EmbyClient(app_config=app_config)
    assert prefixed.api_base_url == "http://emby.test:8096/emby"
    assert prefixed.web_base_url == "http://emby.test:8096"


async def test_emby_client_supports_health_art_refresh_and_themes(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER = ServerType.EMBY
    app_config.MEDIA_SERVER_URL = "http://emby.test:8096"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("emby-token")

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["X-Emby-Token"] == "emby-token"
        if request.url.path == "/emby/System/Info":
            return httpx2.Response(200, json={"Id": "server-1", "ServerName": "Emby"})
        if request.url.path == "/emby/Items/item/Images/Primary":
            return httpx2.Response(200)
        if request.url.path == "/emby/Items/item/RemoteImages":
            return httpx2.Response(
                200,
                json={
                    "Images": [
                        {
                            "Url": "https://images.example/poster.jpg",
                            "Width": 1000,
                            "Height": 1500,
                            "ProviderName": "Emby",
                        }
                    ]
                },
            )
        if request.url.path == "/emby/Items/item/ThemeSongs":
            # Emby leaves the file path out unless it is asked for.
            assert request.url.params["Fields"] == "Path"
            return httpx2.Response(
                200,
                json={
                    "Items": [
                        {
                            "Id": "theme",
                            "Name": "Theme",
                            "Path": "/media/Movie/theme.mp3",
                            "RunTimeTicks": 300_000_000,
                        }
                    ]
                },
            )
        if request.url.path == "/emby/Items/item/Refresh":
            return httpx2.Response(204)
        if request.url.path == "/emby/Items/theme":
            return httpx2.Response(204)
        return httpx2.Response(404)

    factory, transport = mock_client_factory(handler)

    client = EmbyClient(
        app_config=app_config,
        client_factory=factory,
    )
    try:
        assert await client.test_connection() is True
        assert await client.get_server_id() == "server-1"
        assert await client.get_active_image_url("item", ArtType.POSTER) == (
            "http://emby.test:8096/emby/Items/item/Images/Primary"
        )
        assert await client.get_art_candidates("item", ArtType.POSTER) == [
            ArtCandidate(
                url="https://images.example/poster.jpg",
                preview_url="https://images.example/poster.jpg",
                width=1000,
                height=1500,
                source="images",
            )
        ]
        assert await client.get_theme_songs("item") == [
            ServerTheme(
                id="theme",
                title="Theme",
                path="/media/Movie/theme.mp3",
                duration=30.0,
            )
        ]
        await client.refresh_item("item")
        await client.delete_item("theme")
    finally:
        await client.close()

    recorded = [(r.method, r.url.path) for r in transport.requests]
    assert ("POST", "/emby/Items/item/Refresh") in recorded
    assert ("DELETE", "/emby/Items/theme") in recorded


async def test_proxy_client_reuses_and_closes_shared_client(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER = ServerType.JELLYFIN
    manager = ProxyClientManager(app_config=app_config)

    first = await manager.get_client()
    second = await manager.get_client()
    assert first is second
    assert first.follow_redirects is False

    await manager.close()
    assert first.is_closed
    with pytest.raises(RuntimeError, match="closed"):
        await manager.get_client()


def test_active_provider_tracks_configured_media_server(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    registry = ProviderRegistry(app_config=app_config)

    app_config.MEDIA_SERVER = ServerType.PLEX
    assert isinstance(registry.provider, PlexProvider)
    assert registry.collections is registry.provider

    app_config.MEDIA_SERVER = ServerType.JELLYFIN
    assert isinstance(registry.provider, JellyfinProvider)
    assert registry.collections is None

    app_config.MEDIA_SERVER = ServerType.EMBY
    assert isinstance(registry.provider, EmbyProvider)
    assert registry.collections is None


def test_registry_reuses_one_provider_instance_per_media_server(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    """The registry owns its providers; callers must not get a fresh one each time."""
    registry = ProviderRegistry(app_config=app_config)
    app_config.MEDIA_SERVER = ServerType.PLEX

    assert registry.provider is registry.provider


def test_provider_download_headers_are_limited_to_trusted_origins(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    app_config.MEDIA_SERVER_URL = "https://media.internal:32400"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("server-token")

    assert PlexProvider(app_config=app_config).get_download_headers(
        "https://media.internal:32400/poster"
    ) == {"X-Plex-Token": "server-token"}
    assert JellyfinProvider(app_config=app_config).get_download_headers(
        "https://media.internal:32400/poster"
    ) == {"Authorization": 'MediaBrowser Token="server-token"'}
    assert EmbyProvider(app_config=app_config).get_download_headers(
        "https://media.internal:32400/poster"
    ) == {"X-Emby-Token": "server-token"}
    external = "https://example.test/?next=https://media.internal:32400/poster"
    assert PlexProvider(app_config=app_config).get_download_headers(external) == {}
    assert JellyfinProvider(app_config=app_config).get_download_headers(external) == {}
    assert EmbyProvider(app_config=app_config).get_download_headers(external) == {}


def test_server_item_defaults_are_safe_for_mapping() -> None:
    item = ServerItem(
        id="1",
        title="Movie",
        year=None,
        guids={"tmdb": "123"},
        media_type=MediaType.MOVIE,
        poster_url=None,
        background_url=None,
        server_link="http://server/item/1",
    )

    assert item.id == "1"
    assert item.media_type == "movie"
    assert item.year is None
    assert item.guids == {"tmdb": "123"}
    assert item.seasons == []


async def test_plex_client_uses_configured_headers_without_resolved_url(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER_URL = "http://plex.test:32400"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("plex-token")
    async with httpx2.AsyncClient(
        base_url=app_config.MEDIA_SERVER_URL,
        headers={
            "X-Plex-Client-Identifier": "overture-server",
            "X-Plex-Token": app_config.MEDIA_SERVER_API_KEY.get_secret_value(),
            "Accept": "application/json",
        },
    ) as client:
        assert _normalised_base_url(client) == "http://plex.test:32400/"
        assert client.headers["X-Plex-Token"] == "plex-token"
        assert client.headers["X-Plex-Client-Identifier"] == "overture-server"


async def test_plex_image_requests_go_through_the_transcoder_only_when_sized(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    async def no_secure_url(_: PlexClient) -> None:
        return None

    monkeypatch.setattr(PlexClient, "resolve_secure_url", no_secure_url)
    app_config.MEDIA_SERVER_URL = "http://plex.local:32400"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("server-token")
    provider = PlexProvider(app_config=app_config)

    original = await provider.build_provider_art_request("7", ArtType.BACKGROUND, None)
    poster = await provider.build_provider_art_request(
        "7", ArtType.POSTER, ImageSize.DISPLAY
    )
    backdrop = await provider.build_collection_image_request(
        "9", ArtType.BACKGROUND, ImageSize.DISPLAY
    )

    assert original.url == "http://plex.local:32400/library/metadata/7/art"
    assert original.params is None
    assert poster.url == "http://plex.local:32400/photo/:/transcode"
    assert poster.headers == {"X-Plex-Token": "server-token"}
    assert poster.params == {
        "url": "/library/metadata/7/thumb",
        "width": "600",
        "height": "900",
        "minSize": "1",
        "upscale": "0",
    }
    assert backdrop.params is not None
    assert backdrop.params["url"] == "/library/metadata/9/art"
    assert (backdrop.params["width"], backdrop.params["height"]) == ("1280", "720")


async def test_media_browser_image_requests_ask_for_a_max_width_only_when_sized(
    *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER_URL = "http://jellyfin.local:8096"
    provider = JellyfinProvider(app_config=app_config)

    original = await provider.build_provider_art_request("7", ArtType.BACKGROUND, None)
    display = await provider.build_provider_art_request(
        "7", ArtType.POSTER, ImageSize.DISPLAY
    )

    assert original.url == "http://jellyfin.local:8096/Items/7/Images/Backdrop"
    assert display.url == (
        "http://jellyfin.local:8096/Items/7/Images/Primary?maxWidth=600&quality=90"
    )


async def test_plex_refresh_reads_posters_then_unlocks_only_the_fields_replaced(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER_URL = "http://plex.local:32400"
    # A listing Plex has no candidates for answers 404; the refresh still runs.
    factory, transport = mock_client_factory(
        lambda request: httpx2.Response(
            404 if request.url.path == "/library/metadata/9/posters" else 200
        )
    )
    client = PlexClient(app_config=app_config, client_factory=factory)
    monkeypatch.setattr(client, "_resolved_url", app_config.MEDIA_SERVER_URL)
    provider = PlexProvider(app_config=app_config, client=client)

    try:
        await provider.refresh_item("7", unlock={ServerAsset.SEASON_POSTER})
        await provider.refresh_item(
            "8", unlock={ServerAsset.BACKGROUND, ServerAsset.THEME}
        )
        await provider.refresh_item("9", unlock=())
    finally:
        await client.close()

    assert [
        (request.method, request.url.path, dict(request.url.params))
        for request in transport.requests
    ] == [
        ("GET", "/library/metadata/7/posters", {}),
        ("PUT", "/library/metadata/7", {"thumb.locked": "0"}),
        ("PUT", "/library/metadata/7/refresh", {}),
        ("GET", "/library/metadata/8/posters", {}),
        ("PUT", "/library/metadata/8", {"art.locked": "0", "theme.locked": "0"}),
        ("PUT", "/library/metadata/8/refresh", {}),
        ("GET", "/library/metadata/9/posters", {}),
        ("PUT", "/library/metadata/9/refresh", {}),
    ]


async def test_plex_serves_a_theme_without_its_version_and_unlocks_only_collections(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER_URL = "http://plex.local:32400"
    metadata = {"ratingKey": "7", "theme": "/library/metadata/7/theme/1791710511"}
    factory, transport = mock_client_factory(
        lambda request: httpx2.Response(
            200,
            json={"MediaContainer": {"size": 1, "Metadata": [metadata]}}
            if request.method == "GET"
            else None,
        )
    )
    client = PlexClient(app_config=app_config, client_factory=factory)
    monkeypatch.setattr(client, "_resolved_url", app_config.MEDIA_SERVER_URL)

    try:
        themes = await client.get_theme_songs("7")
        # A fix deletes an item's theme, then its refresh unlocks the field.
        await client.delete_theme("7")
        await client.delete_collection_theme("8")
    finally:
        await client.close()

    assert themes == [
        ServerTheme(id="7", url="http://plex.local:32400/library/metadata/7/theme")
    ]
    assert [
        (request.method, request.url.path, dict(request.url.params))
        for request in transport.requests
        if request.method != "GET"
    ] == [
        ("DELETE", "/library/metadata/7/theme", {}),
        ("DELETE", "/library/metadata/8/theme", {}),
        ("PUT", "/library/metadata/8", {"theme.locked": "0"}),
    ]
