"""Coverage for the bounded media-server image proxy."""

lazy from typing import Any, cast

lazy import httpx2
lazy import pytest

lazy from overture.media_servers.adapters import ProviderImageRequest
lazy from overture.services import provider_images as module
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.image import FetchedImage, RemoteImageError


class FakeProxyClients:
    def __init__(self, client: Any) -> None:
        self._client = client
        self.requested_urls: list[str] = []

    async def get_client(self, url: str | None = None) -> Any:
        self.requested_urls.append(url or "")
        return self._client


async def test_proxy_provider_image_fetches_with_resolved_client_and_auth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = httpx2.AsyncClient()
    proxy_clients = FakeProxyClients(client)
    request = ProviderImageRequest(
        url="https://plex.example/img",
        headers={"X-Plex-Token": "secret"},
        params={"width": "300"},
    )
    captured: dict[str, Any] = {}

    async def fake_fetch_image(
        url: str, passed_client: httpx2.AsyncClient, **kwargs: Any
    ) -> FetchedImage:
        captured.update(url=url, client=passed_client, **kwargs)
        return FetchedImage(data=b"pixel-data", media_type="image/png")

    monkeypatch.setattr(module, "fetch_image", fake_fetch_image)

    response = await module.proxy_provider_image(
        request, proxy_clients=cast("Any", proxy_clients)
    )

    assert response.body == b"pixel-data"
    assert response.media_type == "image/png"
    assert response.headers["cache-control"] == "max-age=604800"
    assert proxy_clients.requested_urls == ["https://plex.example/img"]
    assert captured["client"] is client
    assert captured["url"] == "https://plex.example/img"
    assert captured["headers"] == {"X-Plex-Token": "secret"}
    assert captured["params"] == {"width": "300"}
    assert captured["allow_private"] is True


async def test_proxy_provider_image_wraps_remote_image_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch_image(*_args: object, **_kwargs: object):
        raise RemoteImageError("upstream refused")

    monkeypatch.setattr(module, "fetch_image", fake_fetch_image)

    with pytest.raises(PublicServiceError) as exc_info:
        await module.proxy_provider_image(
            ProviderImageRequest(url="https://plex.example/img", headers={}),
            proxy_clients=cast("Any", FakeProxyClients(httpx2.AsyncClient())),
        )

    assert exc_info.value.status_code == 502
