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
lazy from overture.utils.errors import PublicServiceError
lazy from tests.http_mock import keep_configured_plex_url, mock_client_factory
lazy from tests.media_servers import TEST_SERVER_ID, configure, server_of


def _normalised_base_url(client: httpx2.AsyncClient) -> str:
    return f"{str(client.base_url).rstrip('/')}/"


def test_plex_deep_links_encode_metadata_and_collection_keys(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    configure(app_config, url="http://plex.local:32400")
    assert (
        plex_web_link("metadata", "machine", server=server_of(app_config))
        == "https://app.plex.tv/desktop/#!/server/machine/details?key=%2Flibrary%2Fmetadata%2F{id}"
    )
    assert (
        plex_web_link("collections", None, server=server_of(app_config))
        == "http://plex.local:32400/web/index.html"
        "#!/server/details?key=%2Flibrary%2Fcollections%2F{id}"
    )


def test_plex_connection_normalization_rejects_lookalikes_and_url_content(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    configure(app_config, type=ServerType.PLEX)
    assert (
        server_of(app_config).plex_direct_origin(
            "https://server.example.plex.direct:32400/"
        )
        == "https://server.example.plex.direct:32400"
    )
    assert (
        server_of(app_config).plex_direct_origin(
            "http://server.example.plex.direct:32400"
        )
        == ""
    )
    assert server_of(app_config).plex_direct_origin("https://plex.direct:32400") == ""
    assert (
        server_of(app_config).plex_direct_origin(
            "https://server.plex.direct.attacker.test:32400"
        )
        == ""
    )
    assert (
        server_of(app_config).plex_direct_origin(
            "https://server.plex.direct:32400/path"
        )
        == ""
    )
    assert (
        server_of(app_config).plex_direct_origin(
            "https://server.plex.direct:32400?token=x"
        )
        == ""
    )


async def test_plex_secure_origin_is_machine_verified_before_it_is_trusted(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    configured = "http://plex.test:32400"
    secure = "https://server.example.plex.direct:32400"
    configure(app_config, type=ServerType.PLEX)
    configure(app_config, url=configured)
    configure(app_config, api_key=SecretStr("plex-token"))

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
                        "owned": True,
                        "connections": [{"uri": secure}],
                    },
                    {
                        "provides": "server,client",
                        "clientIdentifier": "machine-1",
                        "owned": True,
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
        server=server_of(app_config),
        app_config=app_config,
        client_factory=factory,
    ).resolve_secure_url()

    assert resolved == secure
    assert transport.called
    assert app_config.is_trusted_media_server_url(f"{secure}/library/metadata/1")
    assert not app_config.is_trusted_media_server_url(
        "https://another.example.plex.direct:32400/library/metadata/1"
    )


_PLEX_RESOURCES = "https://plex.tv/api/v2/resources?includeHttps=1"


def _plex_identity(machine: str) -> httpx2.Response:
    return httpx2.Response(200, json={"MediaContainer": {"machineIdentifier": machine}})


def _use_plex(app_config: Settings, url: str) -> None:
    configure(app_config, type=ServerType.PLEX)
    configure(app_config, url=url)
    configure(app_config, api_key=SecretStr("plex-token"))


async def test_plex_required_secure_connections_reach_the_owned_server_by_its_ip(
    *, app_config: Settings
) -> None:
    # Plex's certificate names only plex.direct hosts, so verified TLS to the
    # configured IP fails; Docker's port mapping hides that IP from plex.tv.
    configured = "https://192.168.50.60:32401"
    secure = "https://192-168-50-60.apollo.plex.direct:32401"
    _use_plex(app_config, configured)

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url).rstrip("/")
        assert "friend" not in url
        if url.startswith(configured):
            raise httpx2.ConnectError("certificate verify failed")
        if url == _PLEX_RESOURCES:
            return httpx2.Response(
                200,
                json=[
                    {
                        "provides": "server",
                        "clientIdentifier": "machine-friend",
                        "owned": False,
                        "connections": [
                            {
                                "address": "192.168.50.60",
                                "port": 32401,
                                "uri": "https://192-168-50-60.friend.plex.direct:32401",
                                "local": True,
                            }
                        ],
                    },
                    {
                        "provides": "server",
                        "clientIdentifier": "machine-apollo",
                        "owned": True,
                        "connections": [
                            {
                                "address": "172.17.0.2",
                                "port": 32400,
                                "uri": "https://172-17-0-2.apollo.plex.direct:32400",
                                "local": True,
                            }
                        ],
                    },
                ],
            )
        if url == f"{secure}/identity":
            assert "X-Plex-Token" not in request.headers
            return _plex_identity("machine-apollo")
        if url.startswith(f"{secure}/library/sections/all?"):
            assert request.headers["X-Plex-Token"] == "plex-token"
            return httpx2.Response(
                200,
                json={"MediaContainer": {"Directory": [], "size": 0, "totalSize": 0}},
            )
        return httpx2.Response(404)

    factory, _ = mock_client_factory(handler)
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
    try:
        assert await client.base_url() == secure
        assert await client.get_sections() == []
        assert await client.get_machine_identifier() == "machine-apollo"
    finally:
        await client.close()
    assert app_config.is_trusted_media_server_url(f"{secure}/library/metadata/1")
    assert app_config.media_server_verify_tls(f"{secure}/photo")


async def test_plex_picks_the_owned_server_listed_at_the_configured_address(
    *, app_config: Settings
) -> None:
    configured = "http://192.168.1.20:32400"
    secure = "https://192-168-1-20.second.plex.direct:32400"
    _use_plex(app_config, configured)

    def server(name: str, host: int) -> dict[str, object]:
        return {
            "provides": "server",
            "clientIdentifier": f"machine-{name}",
            "owned": True,
            "connections": [
                {
                    "address": f"192.168.1.{host}",
                    "port": 32400,
                    "uri": f"https://192-168-1-{host}.{name}.plex.direct:32400",
                    "local": True,
                }
            ],
        }

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url).rstrip("/")
        if url.startswith(configured):
            # "Required" secure connections refuse plain HTTP.
            return httpx2.Response(403)
        if url == _PLEX_RESOURCES:
            return httpx2.Response(
                200,
                json=[
                    server("first", 10),
                    server("second", 20),
                ],
            )
        if url == f"{secure}/identity":
            return _plex_identity("machine-second")
        return httpx2.Response(404)

    factory, _ = mock_client_factory(handler)

    resolved = await PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    ).resolve_secure_url()

    assert resolved == secure


async def test_plex_prefers_the_first_local_address_that_proves_its_identity(
    *, app_config: Settings
) -> None:
    configured = "http://plex.test:32400"
    unreachable = "https://10-0-0-5.example.plex.direct:32400"
    local = "https://192-168-1-5.example.plex.direct:32400"
    remote = "https://203-0-113-9.example.plex.direct:32400"
    _use_plex(app_config, configured)

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url).rstrip("/")
        if url in {f"{configured}/identity", f"{local}/identity", f"{remote}/identity"}:
            return _plex_identity("machine-1")
        if url == f"{unreachable}/identity":
            raise httpx2.ConnectError("no route to host")
        if url == _PLEX_RESOURCES:
            return httpx2.Response(
                200,
                json=[
                    {
                        "provides": "server",
                        "clientIdentifier": "machine-1",
                        "owned": True,
                        "connections": [
                            {"uri": remote, "local": False},
                            {"uri": unreachable, "local": True},
                            {"uri": local, "local": True},
                        ],
                    }
                ],
            )
        return httpx2.Response(404)

    factory, _ = mock_client_factory(handler)

    resolved = await PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    ).resolve_secure_url()

    assert resolved == local


async def test_plex_keeps_a_verified_https_url_without_asking_plex_tv(
    *, app_config: Settings
) -> None:
    configured = "https://plex.example.com"
    _use_plex(app_config, configured)
    configure(app_config, verify_tls=True)

    def handler(request: httpx2.Request) -> httpx2.Response:
        if str(request.url) == f"{configured}/identity":
            return _plex_identity("machine-1")
        return httpx2.Response(404)

    factory, transport = mock_client_factory(handler)
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )

    assert await client.resolve_secure_url() is None
    assert await client.get_machine_identifier() == "machine-1"
    assert {request.url.host for request in transport.requests} == {"plex.example.com"}


async def test_plex_connects_once_a_server_that_was_down_comes_up(
    *, app_config: Settings
) -> None:
    configured = "http://plex.test:32400"
    _use_plex(app_config, configured)
    server_up = False

    def handler(request: httpx2.Request) -> httpx2.Response:
        url = str(request.url)
        if url == _PLEX_RESOURCES:
            return httpx2.Response(503)
        if url == f"{configured}/identity" and server_up:
            return _plex_identity("machine-1")
        raise httpx2.ConnectError("connection refused")

    factory, _ = mock_client_factory(handler)
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
    try:
        assert not await client.test_connection()
        server_up = True
        assert await client.test_connection()
        assert await client.base_url() == configured
    finally:
        await client.close()


@pytest.mark.parametrize("candidate_status", [200, 302])
async def test_plex_secure_origin_rejects_a_machine_identity_mismatch(
    monkeypatch: pytest.MonkeyPatch, candidate_status: int, *, app_config: Settings
) -> None:
    configured = "http://plex.test:32400"
    secure = "https://server.example.plex.direct:32400"
    configure(app_config, type=ServerType.PLEX)
    configure(app_config, url=configured)
    configure(app_config, api_key=SecretStr("plex-token"))

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
                        "owned": True,
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
            server=server_of(app_config),
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
    configure(app_config, url="http://jellyfin.test")
    configure(app_config, api_key=SecretStr("jf-token"))
    client = JellyfinClient(server=server_of(app_config, ServerType.JELLYFIN))
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
    configure(app_config, url="http://emby.test:8096")
    configure(app_config, api_key=SecretStr("emby-token"))
    client = EmbyClient(server=server_of(app_config, ServerType.EMBY))
    http_client = await client.get_client()
    try:
        assert _normalised_base_url(http_client) == "http://emby.test:8096/emby/"
        assert http_client.headers["X-Emby-Token"] == "emby-token"
        assert "Authorization" not in http_client.headers
        assert http_client.headers["Accept"] == "application/json"
    finally:
        await client.close()

    configure(app_config, url="http://emby.test:8096/emby")
    prefixed = EmbyClient(server=server_of(app_config, ServerType.EMBY))
    assert prefixed.api_base_url == "http://emby.test:8096/emby"
    assert prefixed.web_base_url == "http://emby.test:8096"


async def test_emby_client_supports_health_art_refresh_and_themes(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    configure(app_config, type=ServerType.EMBY)
    configure(app_config, url="http://emby.test:8096")
    configure(app_config, api_key=SecretStr("emby-token"))

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
        server=server_of(app_config, ServerType.EMBY),
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
    configure(app_config, type=ServerType.JELLYFIN)
    manager = ProxyClientManager(app_config=app_config)

    first = await manager.get_client()
    second = await manager.get_client()
    assert first is second
    assert first.follow_redirects is False

    await manager.close()
    assert first.is_closed
    with pytest.raises(RuntimeError, match="closed"):
        await manager.get_client()


def _three_servers(app_config: Settings) -> ProviderRegistry:
    app_config.MEDIA_SERVERS = tuple(
        server_of(app_config, server_type).model_copy(
            update={"name": f"{server_type.display_name}_{index}"}
        )
        for index, server_type in enumerate(ServerType, start=1)
    )
    registry = ProviderRegistry(app_config=app_config)
    registry.attach(
        {server.key: index for index, server in enumerate(app_config.MEDIA_SERVERS, 1)}
    )
    return registry


def test_registry_builds_each_configured_servers_provider_lead_first(
    *, app_config: Settings
) -> None:
    registry = _three_servers(app_config)

    assert [type(provider) for provider in registry.providers()] == [
        PlexProvider,
        JellyfinProvider,
        EmbyProvider,
    ]
    assert [provider.server_id for provider in registry.providers()] == [1, 2, 3]
    assert registry.collection_providers() == registry.providers()


def test_registry_refuses_a_server_no_longer_configured(
    *, app_config: Settings
) -> None:
    registry = _three_servers(app_config)

    with pytest.raises(PublicServiceError) as refused:
        registry.get(9)
    assert refused.value.status_code == 409


def test_registry_reuses_one_provider_instance_per_media_server(
    *, app_config: Settings
) -> None:
    """The registry owns its providers; callers must not get a fresh one each time."""
    registry = _three_servers(app_config)
    assert registry.get(2) is registry.get(2)
    assert registry.get(1) is not registry.get(2)


def test_provider_download_headers_are_limited_to_trusted_origins(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    configure(app_config, url="https://media.internal:32400")
    configure(app_config, api_key=SecretStr("server-token"))
    assert PlexProvider(
        server=server_of(app_config), server_id=TEST_SERVER_ID, app_config=app_config
    ).get_download_headers("https://media.internal:32400/poster") == {
        "X-Plex-Token": "server-token"
    }
    assert JellyfinProvider(
        server=server_of(app_config, ServerType.JELLYFIN),
        server_id=TEST_SERVER_ID,
        app_config=app_config,
    ).get_download_headers("https://media.internal:32400/poster") == {
        "Authorization": 'MediaBrowser Token="server-token"'
    }
    assert EmbyProvider(
        server=server_of(app_config, ServerType.EMBY),
        server_id=TEST_SERVER_ID,
        app_config=app_config,
    ).get_download_headers("https://media.internal:32400/poster") == {
        "X-Emby-Token": "server-token"
    }
    external = "https://example.test/?next=https://media.internal:32400/poster"
    assert (
        PlexProvider(
            server=server_of(app_config),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ).get_download_headers(external)
        == {}
    )
    assert (
        JellyfinProvider(
            server=server_of(app_config, ServerType.JELLYFIN),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ).get_download_headers(external)
        == {}
    )
    assert (
        EmbyProvider(
            server=server_of(app_config, ServerType.EMBY),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ).get_download_headers(external)
        == {}
    )


def test_server_item_defaults_are_safe_for_mapping() -> None:
    item = ServerItem(
        id="1",
        title="Movie",
        year=None,
        guids={"tmdb": "123"},
        media_type=MediaType.MOVIE,
        poster_url=None,
        background_url=None,
    )

    assert item.id == "1"
    assert item.media_type == "movie"
    assert item.year is None
    assert item.guids == {"tmdb": "123"}
    assert item.seasons == []


async def test_plex_client_uses_configured_headers_without_resolved_url(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    configure(app_config, url="http://plex.test:32400")
    server = configure(app_config, api_key=SecretStr("plex-token"))
    async with httpx2.AsyncClient(
        base_url=server.url,
        headers={
            "X-Plex-Client-Identifier": "overture-server",
            "X-Plex-Token": server.api_key.get_secret_value(),
            "Accept": "application/json",
        },
    ) as client:
        assert _normalised_base_url(client) == "http://plex.test:32400/"
        assert client.headers["X-Plex-Token"] == "plex-token"
        assert client.headers["X-Plex-Client-Identifier"] == "overture-server"


async def test_plex_image_requests_go_through_the_transcoder_only_when_sized(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    configure(app_config, url="http://plex.local:32400")
    configure(app_config, api_key=SecretStr("server-token"))
    provider = PlexProvider(
        server=server_of(app_config), server_id=TEST_SERVER_ID, app_config=app_config
    )

    original = await provider.build_provider_art_request("7", ArtType.BACKGROUND, None)
    poster = await provider.build_provider_art_request(
        "7", ArtType.POSTER, ImageSize.DISPLAY
    )
    backdrop = await provider.build_collection_image_request(
        "9",
        ArtType.BACKGROUND,
        ImageSize.DISPLAY,
        current_url="http://plex.local:32400/library/metadata/9/art/123",
    )
    # A generated poster exists only as a composite; the metadata thumb is 404.
    composite = await provider.build_collection_image_request(
        "9",
        ArtType.POSTER,
        None,
        current_url="http://plex.local:32400/library/collections/9/composite/5?width=400",
    )
    assert composite.url == (
        "http://plex.local:32400/library/collections/9/composite/5?width=400"
    )

    assert original.url == "http://plex.local:32400/library/metadata/7/art"
    assert original.params is None
    assert poster.url == "http://plex.local:32400/photo/:/transcode"
    assert poster.headers == {"X-Plex-Token": "server-token"}
    assert poster.params == {
        "url": "/library/metadata/7/thumb",
        "width": "400",
        "height": "600",
        "minSize": "1",
        "upscale": "0",
    }
    assert backdrop.params is not None
    assert backdrop.params["url"] == "/library/metadata/9/art/123"
    assert (backdrop.params["width"], backdrop.params["height"]) == ("960", "540")


async def test_media_browser_image_requests_ask_for_a_max_width_only_when_sized(
    *, app_config: Settings
) -> None:
    configure(app_config, url="http://jellyfin.local:8096")
    provider = JellyfinProvider(
        server=server_of(app_config, ServerType.JELLYFIN),
        server_id=TEST_SERVER_ID,
        app_config=app_config,
    )

    original = await provider.build_provider_art_request("7", ArtType.BACKGROUND, None)
    display = await provider.build_provider_art_request(
        "7", ArtType.POSTER, ImageSize.DISPLAY
    )

    assert original.url == "http://jellyfin.local:8096/Items/7/Images/Backdrop"
    assert display.url == (
        "http://jellyfin.local:8096/Items/7/Images/Primary?maxWidth=400&quality=90"
    )


async def test_plex_refresh_reads_posters_then_unlocks_only_the_fields_replaced(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    configure(app_config, url="http://plex.local:32400")
    # A listing Plex has no candidates for answers 404; the refresh still runs.
    factory, transport = mock_client_factory(
        lambda request: httpx2.Response(
            404 if request.url.path == "/library/metadata/9/posters" else 200
        )
    )
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    provider = PlexProvider(
        server=server_of(app_config),
        server_id=TEST_SERVER_ID,
        app_config=app_config,
        client=client,
    )

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
    configure(app_config, url="http://plex.local:32400")
    metadata = {"ratingKey": "7", "theme": "/library/metadata/7/theme/1791710511"}
    factory, transport = mock_client_factory(
        lambda request: httpx2.Response(
            200,
            json={"MediaContainer": {"size": 1, "Metadata": [metadata]}}
            if request.method == "GET"
            else None,
        )
    )
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)

    try:
        themes = await client.get_theme_songs("7")
        # A fix deletes an item's theme, then its refresh unlocks the field.
        await client.delete_theme("7")
        await client.delete_collection_theme("8")
    finally:
        await client.close()

    assert themes == [
        ServerTheme(
            id="/library/metadata/7/theme/1791710511",
            url="http://plex.local:32400/library/metadata/7/theme",
        )
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


async def test_media_browser_refresh_drops_downloaded_backdrops_for_a_new_background(
    *, app_config: Settings
) -> None:
    configure(app_config, url="http://jellyfin.local:8096")
    images = [
        {"ImageType": "Primary", "Path": "/config/metadata/7/poster.jpg"},
        {"ImageType": "Backdrop", "ImageIndex": 0, "Path": "/config/metadata/7/b.jpg"},
        {"ImageType": "Backdrop", "ImageIndex": 1, "Path": "/movies/Film/fanart.jpg"},
        {"ImageType": "Backdrop", "ImageIndex": 2, "Path": "/config/metadata/7/c.jpg"},
    ]

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/Items" and request.method == "GET":
            item = {"Id": "7", "Path": "/movies/Film/Film.mkv", "IsFolder": False}
            return httpx2.Response(200, json={"Items": [item], "TotalRecordCount": 1})
        if request.url.path == "/Items/7/Images":
            return httpx2.Response(200, json=images)
        return httpx2.Response(204)

    factory, transport = mock_client_factory(handle)
    server = server_of(app_config, ServerType.JELLYFIN)
    client = JellyfinClient(server=server, client_factory=factory)
    provider = JellyfinProvider(
        server=server, server_id=TEST_SERVER_ID, app_config=app_config, client=client
    )
    try:
        await provider.refresh_item("7", unlock={ServerAsset.POSTER})
        await provider.refresh_item("7", unlock={ServerAsset.BACKGROUND})
    finally:
        await client.close()

    # The backdrop beside the media stays; the downloaded ones go, last first.
    assert [
        (request.method, request.url.path)
        for request in transport.requests
        if request.method != "GET"
    ] == [
        ("POST", "/Items/7/Refresh"),
        ("DELETE", "/Items/7/Images/Backdrop/2"),
        ("DELETE", "/Items/7/Images/Backdrop/0"),
        ("POST", "/Items/7/Refresh"),
    ]
