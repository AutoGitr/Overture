"""HTTP client retry and timeout contracts."""

lazy import httpx2
lazy import pytest

lazy from overture.config import Settings
lazy from overture.domain import MediaType
lazy from overture.integrations.http import create_client, request_with_retry
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.media_servers.plex.client import PlexClient
lazy from overture.utils.cache import TimedRegistry
lazy from tests.http_mock import RecordingMockTransport


async def test_create_client_applies_standard_timeout() -> None:
    client = create_client()
    try:
        assert client.timeout.connect == 10.0
        assert client.timeout.read == 30.0
        assert client.timeout.write == 30.0
        assert client.timeout.pool == 30.0
    finally:
        await client.aclose()


async def test_http_client_owners_reject_reuse_after_close(
    app_config: Settings,
) -> None:
    tmdb = TMDBClient(app_config=app_config)
    proxy = ProxyClientManager(app_config=app_config)
    plex = PlexClient(app_config=app_config)
    await tmdb.close()
    await proxy.close()
    await plex.close()
    with pytest.raises(RuntimeError, match="closed"):
        await tmdb.get_details(MediaType.MOVIE, 1)
    with pytest.raises(RuntimeError, match="closed"):
        await proxy.get_client()
    with pytest.raises(RuntimeError, match="closed"):
        await plex.get_client()


async def test_request_with_retry_retries_transient_5xx() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        if transport.call_count == 1:
            return httpx2.Response(503)
        return httpx2.Response(200, json={"ok": True})

    transport = RecordingMockTransport(handler)
    async with httpx2.AsyncClient(transport=transport) as client:
        response = await request_with_retry(
            client,
            "GET",
            "https://upstream.test/resource",
            retry_delays=(0,),
        )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert transport.call_count == 2


async def test_request_with_retry_does_not_retry_terminal_4xx() -> None:
    transport = RecordingMockTransport(
        lambda _: httpx2.Response(404, json={"detail": "missing"})
    )
    async with httpx2.AsyncClient(transport=transport) as client:
        response = await request_with_retry(
            client,
            "GET",
            "https://upstream.test/missing",
            retry_delays=(0,),
        )

    assert response.status_code == 404
    assert transport.call_count == 1


async def test_request_with_retry_raises_last_transient_exception() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectTimeout("api_key=super-secret")

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(httpx2.ConnectTimeout):
            await request_with_retry(
                client,
                "GET",
                "https://upstream.test/timeout",
                retry_delays=(0,),
            )


def test_host_rate_limit_tracking_stays_bounded() -> None:
    """Per-host pacing must not grow without limit across arbitrary URLs."""
    registry: TimedRegistry[str, float] = TimedRegistry(
        maxsize=1000,
        ttl_seconds=300.0,
    )

    for index in range(1000 * 2):
        registry.set(f"host-{index}.example.test", float(index), float(index))

    assert len(registry) <= 1000


def test_idle_hosts_are_forgotten_once_past_the_window() -> None:
    registry: TimedRegistry[str, float] = TimedRegistry(maxsize=10, ttl_seconds=300.0)
    registry.set("stale.example.test", 1.0, now=0.0)

    assert registry.get("stale.example.test", now=100.0) == 1.0
    assert registry.get("stale.example.test", now=1_000.0) is None
