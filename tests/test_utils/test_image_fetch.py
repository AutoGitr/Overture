"""Remote image fetch and sniffing safety tests."""

lazy import asyncio
lazy import base64
lazy from io import BytesIO

lazy import httpx2
lazy import pytest
lazy from PIL import Image

lazy import overture.utils.image as image_mod
lazy from overture.utils.image import (
    MAX_REMOTE_IMAGE_BYTES,
    FetchedImage,
    RemoteImageError,
    fetch_image,
    fetch_image_bytes,
    is_supported_remote_image_type,
    normalise_content_type,
    sniff_image_size,
)

PNG_DATA = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "YAAAAAYAAjCB0C8AAAAASUVORK5CYII="
)


@pytest.fixture(autouse=True)
def resolve_test_hosts_as_public(monkeypatch: pytest.MonkeyPatch) -> None:
    """Avoid DNS dependence while preserving explicit private-host test overrides."""

    async def public_url(_: str) -> bool:
        return False

    monkeypatch.setattr(image_mod, "is_private_url", public_url)


def test_content_type_and_tmdb_preview_helpers() -> None:
    assert normalise_content_type("Image/JPEG; charset=binary") == "image/jpeg"
    assert is_supported_remote_image_type("image/png") is True
    assert is_supported_remote_image_type("image/webp") is False
    assert (
        is_supported_remote_image_type("image/webp", allow_generic_image=True) is True
    )


async def test_fetch_image_bytes_rejects_unsupported_content_type() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html></html>",
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(RemoteImageError, match="Unsupported content type"):
            await fetch_image_bytes("https://images.test/poster.jpg", client)


async def test_fetch_image_bytes_enforces_content_length_limit() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={
                "content-type": "image/jpeg",
                "content-length": str(MAX_REMOTE_IMAGE_BYTES + 1),
            },
            content=b"",
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(RemoteImageError, match="exceeds"):
            await fetch_image_bytes("https://images.test/huge.jpg", client)


async def test_fetch_image_bytes_allows_valid_png() -> None:

    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"content-type": "image/png"},
            content=PNG_DATA,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        assert (
            await fetch_image_bytes("https://images.test/one.png", client) == PNG_DATA
        )


def _webp() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 4)).save(buffer, format="WEBP")
    return buffer.getvalue()


async def test_fetch_image_names_any_decodable_format_only_when_asked() -> None:
    webp = _webp()

    def handler(_: httpx2.Request) -> httpx2.Response:
        # Mislabelled: the media type is read from the bytes, not the header.
        return httpx2.Response(
            200, headers={"content-type": "image/jpeg"}, content=webp
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        image = await fetch_image(
            "https://images.test/one.webp", client, allow_generic_image=True
        )
        assert image == FetchedImage(data=webp, media_type="image/webp")

        # Saved images stay JPEG or PNG, and the refusal names what was served.
        with pytest.raises(RemoteImageError, match="Unsupported image format: WEBP"):
            await fetch_image(
                "https://images.test/one.webp",
                client,
                allow_generic_image=False,
            )


async def test_fetch_image_refuses_undecodable_bytes_even_when_generic() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, headers={"content-type": "image/svg+xml"}, content=b"<svg/>"
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(RemoteImageError, match="Unreadable image bytes"):
            await fetch_image(
                "https://images.test/one.svg", client, allow_generic_image=True
            )


async def test_fetch_image_bytes_reports_the_bytes_it_receives() -> None:
    reports: list[tuple[int, int | None]] = []

    async def on_progress(received: int, total: int | None) -> None:
        reports.append((received, total))

    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"content-type": "image/png"},
            content=PNG_DATA,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        await fetch_image_bytes(
            "https://images.test/one.png",
            client,
            on_progress=on_progress,
        )

    assert reports == [(len(PNG_DATA), len(PNG_DATA))]


async def test_fetch_image_bytes_strips_credentials_on_cross_origin_redirect() -> None:

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "images.test":
            assert request.headers["x-api-key"] == "secret"
            assert request.url.params["credential"] == "secret"
            return httpx2.Response(
                302,
                headers={"location": "https://cdn.test/one.png"},
                request=request,
            )
        assert request.url.host == "cdn.test"
        assert "x-api-key" not in request.headers
        assert "credential" not in request.url.params
        return httpx2.Response(
            200,
            headers={"content-type": "image/png"},
            content=PNG_DATA,
            request=request,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        result = await fetch_image_bytes(
            "https://images.test/one.png",
            client,
            headers={"X-Api-Key": "secret"},
            params={"credential": "secret"},
        )

    assert result == PNG_DATA


@pytest.mark.parametrize("sniff", [False, True])
async def test_image_request_rejects_untrusted_private_redirect(
    monkeypatch: pytest.MonkeyPatch,
    sniff: bool,
) -> None:
    async def private_url(url: str) -> bool:
        return "private.test" in url

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "images.test":
            return httpx2.Response(
                302,
                headers={"location": "http://private.test/one.png"},
                request=request,
            )
        raise AssertionError("private redirect should be rejected before dispatch")

    monkeypatch.setattr(image_mod, "is_private_url", private_url)
    async with httpx2.AsyncClient(
        transport=httpx2.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        if sniff:
            assert await sniff_image_size(
                "https://images.test/one.png",
                client,
                allow_private=True,
            ) == (0, 0)
        else:
            with pytest.raises(RemoteImageError, match="Unsafe image redirect"):
                await fetch_image_bytes(
                    "https://images.test/one.png",
                    client,
                    allow_private=True,
                )


async def test_sniff_image_size_rejects_a_private_initial_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def private_url(_: str) -> bool:
        return True

    def handler(_: httpx2.Request) -> httpx2.Response:
        raise AssertionError("private URL should be rejected before request dispatch")

    monkeypatch.setattr(image_mod, "is_private_url", private_url)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        assert await sniff_image_size("http://127.0.0.1/poster.jpg", client) == (0, 0)


async def test_sniff_strips_cross_origin_credentials_and_closes_response() -> None:
    responses: list[httpx2.Response] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.host == "images.test":
            assert request.headers["x-api-key"] == "secret"
            response = httpx2.Response(
                302,
                headers={"location": "https://cdn.test/one.png"},
            )
        else:
            assert "x-api-key" not in request.headers
            response = httpx2.Response(
                200,
                headers={"content-type": "image/png"},
                content=PNG_DATA,
            )
        responses.append(response)
        return response

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        assert await sniff_image_size(
            "https://images.test/one.png",
            client,
            headers={"X-Api-Key": "secret"},
        ) == (1, 1)

    assert len(responses) == 2
    assert all(response.is_closed for response in responses)


@pytest.mark.parametrize("sniff", [False, True])
async def test_image_request_bounds_redirect_loops(
    monkeypatch: pytest.MonkeyPatch,
    sniff: bool,
) -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(302, headers={"location": "/again.png"})

    monkeypatch.setattr(image_mod, "MAX_IMAGE_REDIRECTS", 2)
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        if sniff:
            assert await sniff_image_size("https://images.test/one.png", client) == (
                0,
                0,
            )
        else:
            with pytest.raises(RemoteImageError, match="Too many image redirects"):
                await fetch_image_bytes("https://images.test/one.png", client)

    assert len(requests) == 3


@pytest.mark.parametrize("length", ["-1", "invalid"])
async def test_fetch_rejects_invalid_content_length(length: str) -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"content-type": "image/png", "content-length": length},
            content=PNG_DATA,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(RemoteImageError, match="Invalid Content-Length"):
            await fetch_image_bytes("https://images.test/one.png", client)


async def test_fetch_enforces_limit_on_received_bytes() -> None:
    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200,
            headers={"content-type": "image/png", "content-length": "1"},
            content=PNG_DATA,
        )

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(RemoteImageError, match="exceeds"):
            await fetch_image_bytes("https://images.test/one.png", client, max_bytes=10)


async def test_a_transfer_without_slots_does_not_wait_for_shared_transfers() -> None:
    """Art downloads are bounded by their lane, never by bulk comparisons."""

    def handler(_: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(
            200, headers={"content-type": "image/png"}, content=PNG_DATA
        )

    slots = asyncio.Semaphore(1)
    await slots.acquire()
    async with httpx2.AsyncClient(transport=httpx2.MockTransport(handler)) as client:
        data = await asyncio.wait_for(
            fetch_image_bytes(
                "https://images.test/poster.png", client, transfer_slots=None
            ),
            timeout=1,
        )
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(
                fetch_image_bytes(
                    "https://images.test/poster.png", client, transfer_slots=slots
                ),
                timeout=0.05,
            )

    assert data == PNG_DATA
