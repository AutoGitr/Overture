"""Unavailable providers and incomplete snapshots are explicit failures."""

lazy from collections.abc import Callable
lazy from functools import partial
lazy from typing import Any

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.domain import ArtType
lazy from overture.integrations.http import request_with_retry
lazy from overture.media_servers.emby.client import EmbyClient
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.jellyfin.client import JellyfinClient
lazy from overture.media_servers.plex.client import PlexClient
lazy from tests.http_mock import keep_configured_plex_url, mock_client_factory


@pytest.fixture(params=[PlexClient, JellyfinClient, EmbyClient])
def provider_factory(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
) -> Callable[
    [Callable[[httpx2.Request], httpx2.Response]], PlexClient | JellyfinClient
]:
    app_config.MEDIA_SERVER_URL = "https://server.test/reverse"
    app_config.MEDIA_SERVER_API_KEY = SecretStr("test-secret")
    monkeypatch.setattr(
        "overture.media_servers.http_client.request_with_retry",
        partial(request_with_retry, retry_delays=(0, 0)),
    )

    def factory(**kwargs: Any) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(
            transport=httpx2.MockTransport(active_handler), **kwargs
        )

    active_handler: Callable[[httpx2.Request], httpx2.Response]

    def build(
        handler: Callable[[httpx2.Request], httpx2.Response],
    ) -> PlexClient | JellyfinClient:
        nonlocal active_handler
        active_handler = handler
        client = request.param(app_config=app_config, client_factory=factory)
        if isinstance(client, PlexClient):
            monkeypatch.setattr(
                PlexClient, "resolve_secure_url", keep_configured_plex_url
            )
        return client

    return build


async def listing(client: PlexClient | JellyfinClient) -> object:
    pages = (
        client.iter_section_items("1")
        if isinstance(client, PlexClient)
        else client.iter_section_items("1", "Movie")
    )
    return [item async for page in pages for item in page]


@pytest.mark.parametrize(
    ("status", "expected"), [(401, 502), (403, 502), (302, 502), (503, 503)]
)
async def test_failed_reads_are_safe_errors_without_following_redirects(
    provider_factory: Callable[
        [Callable[[httpx2.Request], httpx2.Response]], PlexClient | JellyfinClient
    ],
    status: int,
    expected: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        assert request.url.host == "server.test"
        return httpx2.Response(
            status,
            headers={"Location": "https://attacker.test/"},
            text="test-secret provider internals",
        )

    provider_client = provider_factory(handler)
    try:
        with pytest.raises(MediaServerError) as exc:
            await listing(provider_client)
        assert exc.value.status_code == expected
        assert "test-secret" not in str(exc.value)
        assert calls == (3 if status == 503 else 1)
    finally:
        await provider_client.close()


async def test_timeout_is_unavailable_after_bounded_retries(
    provider_factory: Callable[
        [Callable[[httpx2.Request], httpx2.Response]], PlexClient | JellyfinClient
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        raise httpx2.ReadTimeout("test-secret", request=request)

    provider_client = provider_factory(handler)
    try:
        with pytest.raises(MediaServerError) as exc:
            await listing(provider_client)
        assert exc.value.status_code == 503
        assert calls == 3
    finally:
        await provider_client.close()


async def test_failed_mutation_is_not_retried_or_reported_as_success(
    provider_factory: Callable[
        [Callable[[httpx2.Request], httpx2.Response]], PlexClient | JellyfinClient
    ],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        return httpx2.Response(503)

    provider_client = provider_factory(handler)
    try:
        mutation = (
            provider_client.upload_collection_theme("1", b"mp3")
            if isinstance(provider_client, PlexClient)
            else provider_client.delete_item("1")
        )
        with pytest.raises(MediaServerError):
            await mutation
        assert calls == 1
    finally:
        await provider_client.close()


@pytest.mark.parametrize(
    "failure",
    [
        "invalid_json",
        "missing_items",
        "missing_id",
        "empty_id",
        "early_end",
        "changed_total",
        "wrong_offset",
        "negative_total",
    ],
)
async def test_incomplete_or_malformed_snapshot_cannot_be_reconciled(
    provider_factory: Callable[
        [Callable[[httpx2.Request], httpx2.Response]], PlexClient | JellyfinClient
    ],
    failure: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    plex = False

    def handler(_request: httpx2.Request) -> httpx2.Response:
        nonlocal calls
        calls += 1
        if failure == "invalid_json":
            return httpx2.Response(200, text="<html>Bad gateway</html>")
        if failure == "missing_items":
            return httpx2.Response(200, json={"MediaContainer": {}} if plex else {})
        items: list[dict[str, Any]] = [{"ratingKey" if plex else "Id": str(calls)}]
        total, offset = 2, calls - 1
        if failure == "missing_id":
            items = [{"title": "Unknown"}]
        elif failure == "empty_id":
            items = [{"ratingKey" if plex else "Id": ""}]
        elif failure == "negative_total":
            total = -1
        elif calls > 1:
            match failure:
                case "early_end":
                    items = []
                case "changed_total":
                    total = 3
                case "wrong_offset":
                    offset = 0
                case _:
                    pytest.fail("Expected the first page to be rejected")
        payload = (
            {
                "MediaContainer": {
                    "Metadata": items,
                    "totalSize": total,
                    "offset": offset,
                }
            }
            if plex
            else {"Items": items, "TotalRecordCount": total, "StartIndex": offset}
        )
        return httpx2.Response(200, json=payload)

    provider_client = provider_factory(handler)
    plex = isinstance(provider_client, PlexClient)

    try:
        with pytest.raises(MediaServerError):
            await listing(provider_client)
    finally:
        await provider_client.close()


@pytest.mark.parametrize("status", [200, 404, 401])
async def test_active_art_is_absent_only_on_not_found(
    status: int, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER_URL = "https://server.test"

    factory, transport = mock_client_factory(lambda _: httpx2.Response(status))
    client = JellyfinClient(app_config=app_config, client_factory=factory)
    try:
        if status == 401:
            with pytest.raises(MediaServerError):
                await client.get_active_image_url("1", ArtType.POSTER)
        else:
            assert bool(await client.get_active_image_url("1", ArtType.POSTER)) is (
                status == 200
            )
    finally:
        await client.close()

    assert transport.called


def _plex_rows(request: httpx2.Request, total: int, size: int) -> httpx2.Response:
    """Serve *size* rows of a *total*-row Plex section from the requested offset."""
    offset = int(request.url.params["X-Plex-Container-Start"])
    keys = range(offset, min(total, offset + size))
    return httpx2.Response(
        200,
        json={
            "MediaContainer": {
                "Metadata": [{"ratingKey": str(key)} for key in keys],
                "totalSize": total,
                "offset": offset,
            }
        },
    )


async def test_plex_prefetched_pages_arrive_complete_and_in_order(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER_URL = "https://server.test"
    factory, transport = mock_client_factory(lambda r: _plex_rows(r, 10, 3))
    client = PlexClient(app_config=app_config, client_factory=factory)
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    try:
        pages = [
            [item["ratingKey"] for item in page]
            async for page in client.iter_section_items("1")
        ]
    finally:
        await client.close()

    assert pages == [["0", "1", "2"], ["3", "4", "5"], ["6", "7", "8"], ["9"]]
    offsets = [r.url.params["X-Plex-Container-Start"] for r in transport.requests]
    assert sorted(offsets, key=int) == ["0", "3", "6", "9"]


async def test_plex_prefetch_rejects_a_short_page_before_the_end(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER_URL = "https://server.test"

    def handler(request: httpx2.Request) -> httpx2.Response:
        offset = int(request.url.params["X-Plex-Container-Start"])
        return _plex_rows(request, 10, 3 if offset == 0 else 2)

    factory, _ = mock_client_factory(handler)
    client = PlexClient(app_config=app_config, client_factory=factory)
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    try:
        with pytest.raises(MediaServerError, match="inconsistent page size"):
            await listing(client)
    finally:
        await client.close()
