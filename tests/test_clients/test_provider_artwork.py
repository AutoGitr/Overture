"""Artwork metadata and credentials stay within provider trust boundaries."""

lazy import asyncio
lazy from collections import Counter
lazy from typing import Any

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.domain import ArtType, ServerType
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.jellyfin.client import JellyfinClient
lazy from overture.media_servers.plex.client import PlexClient
lazy from tests.http_mock import keep_configured_plex_url, mock_client_factory


@pytest.mark.parametrize(
    "server_url",
    ["https://plex.test/reverse", "https://192-168-1-2.server.plex.direct:32400"],
)
async def test_plex_offers_only_deduplicated_public_artwork(
    monkeypatch: pytest.MonkeyPatch, server_url: str, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER = ServerType.PLEX
    app_config.MEDIA_SERVER_URL = server_url
    app_config.MEDIA_SERVER_API_KEY = SecretStr("test-token")

    local = "/library/metadata/1/thumb/2"
    external = "https://public.test/art.jpg"
    sniffed: dict[str, dict[str, Any]] = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path.endswith("/library/metadata/1/posters")
        assert request.headers["X-Plex-Token"] == "test-token"
        return httpx2.Response(
            200,
            json={
                "MediaContainer": {
                    "Metadata": [
                        {"key": local},
                        {"key": local},
                        {"key": external},
                        {"key": external},
                        {"key": server_url + local},
                        {"key": "https://unverified.plex.direct/art.jpg"},
                        {"key": "http://127.0.0.1/art.jpg"},
                        {"key": "https://private.test/art.jpg"},
                    ],
                    "totalSize": 8,
                }
            },
        )

    factory, transport = mock_client_factory(handler)
    client = PlexClient(app_config=app_config, client_factory=factory)
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)

    async def resolve(host: str, *_args: Any, **_kwargs: Any) -> list[Any]:
        ip = "192.168.1.2" if host == "private.test" else "93.184.216.34"
        return [(2, 1, 6, "", (ip, 0))]

    async def sniff(
        url: str, _http: httpx2.AsyncClient, **kwargs: Any
    ) -> tuple[int, int]:
        assert "X-Plex-Token" not in _http.headers
        sniffed[url] = kwargs
        return 100, 150

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr("overture.media_servers.plex.client.sniff_image_size", sniff)
    try:
        candidates = await client.get_art_candidates("1", ArtType.POSTER)
        assert [item.url for item in candidates] == [external]
        assert sniffed == {external: {}}
        assert candidates[0].width == 100
        assert candidates[0].height == 150
    finally:
        await client.close()

    assert transport.called


async def test_plex_size_probes_share_a_client_and_bounded_concurrency(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER_URL = "https://plex.test"

    factory, _transport = mock_client_factory(
        lambda _: httpx2.Response(
            200,
            json={"MediaContainer": {"Metadata": rows, "totalSize": len(rows)}},
        )
    )

    client = PlexClient(app_config=app_config, client_factory=factory)
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    dns: Counter[str] = Counter()
    clients: list[httpx2.AsyncClient] = []
    active = peak = 0
    rows: list[dict[str, Any]] = [
        {"key": f"https://public.test/{index}.jpg"} for index in range(20)
    ]
    rows.append({"key": "https://public.test/known.jpg", "width": 100, "height": 150})

    async def resolve(host: str, *_args: Any, **_kwargs: Any) -> list[Any]:
        dns[host] += 1
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    async def sniff(url: str, http: httpx2.AsyncClient) -> tuple[int, int]:
        nonlocal active, peak
        assert not url.endswith("known.jpg")
        clients.append(http)
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0)
        active -= 1
        return 100, 150

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    monkeypatch.setattr("overture.media_servers.plex.client.sniff_image_size", sniff)
    try:
        candidates = await client.get_art_candidates("1", ArtType.POSTER)
        assert len(candidates) == 21
        assert len(clients) == 20
        assert all(http is clients[0] for http in clients)
        assert 1 < peak <= 16
        assert dns == {"public.test": 1}
        assert await client.get_art_candidates("1", ArtType.POSTER) == candidates
        assert len(clients) == 20
        await client.get_art_candidates("2", ArtType.POSTER)
        assert len(clients) == 40
        assert all(http is clients[0] for http in clients)
    finally:
        await client.close()


async def test_library_sections_require_unique_ids(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    client = JellyfinClient(app_config=app_config)

    async def response(*_args: Any, **_kwargs: Any) -> object:
        return [{"ItemId": "1"}, {"ItemId": "1"}]

    monkeypatch.setattr(client, "_get", response)
    with pytest.raises(MediaServerError):
        await client.get_sections()
