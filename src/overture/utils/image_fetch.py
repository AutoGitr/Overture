"""Fetching images from the network, within the size, type and address limits.

Every remote image is fetched here: redirects are followed only to public
addresses unless a caller trusts the host, a host that rate-limits is paused,
and the bytes are checked to be the image they claim before anything keeps
them.
"""

lazy import asyncio
lazy import math
lazy from collections.abc import AsyncGenerator
lazy from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
    nullcontext,
)
lazy from dataclasses import dataclass
lazy from http import HTTPStatus
lazy from urllib.parse import urljoin, urlsplit

lazy import httpx2
lazy from PIL import Image, ImageFile

lazy from .image import (
    UnsupportedImageFormatError,
    encoded_image_format,
    saved_image_extension,
)
lazy from .progress import BytesProgress
lazy from .rate_limit import RateLimitPause, retry_after_seconds
lazy from .ssrf import is_private_url

SUPPORTED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
}


#: Content types that say nothing about what the bytes are.
_UNTYPED_CONTENT_TYPES = frozenset({"application/octet-stream", "binary/octet-stream"})


REMOTE_IMAGE_REQUEST_HEADERS = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "Accept": "image/jpeg,image/png,image/*;q=0.8,*/*;q=0.5",
        "User-Agent": "Overture/1.0",
    }
)


#: Remote images read for comparison or display at once. Candidate matching
#: and audits fan out per slot, so this bounds the memory they hold together.
#: Downloads are bounded by their own lane's worker count instead.
SHARED_IMAGE_TRANSFERS = asyncio.Semaphore(8)


#: Image hosts paused while they rate-limit Overture, by host name.
IMAGE_HOST_PAUSES = RateLimitPause[str]()


MAX_IMAGE_BYTES = 20 * 1024 * 1024


MAX_SNIFF_BYTES = 256 * 1024


MAX_IMAGE_REDIRECTS = 5


IMAGE_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class RemoteImageError(ValueError):
    """Raised when a remote image cannot be fetched or fails validation."""


class RateLimitedError(RemoteImageError):
    """Raised when an image host is rate-limiting Overture."""


#: How often background work asks a rate-limiting host again, each time after
#: the pause the limit started: the pause doubles, so the last wait is long.
RATE_LIMIT_RETRIES = 3


def _host(url: str) -> str:
    return urlsplit(url).hostname or ""


def raise_if_rate_limited(url: str | None = None) -> None:
    """Refuse at once while *url*'s host, or any host without one, is paused.

    For work someone is waiting on; background fetches wait the pause out.

    Raises:
        RateLimitedError: While the host is paused.
    """
    if url is None:
        paused = IMAGE_HOST_PAUSES.longest()
    elif delay := IMAGE_HOST_PAUSES.remaining(host := _host(url)):
        paused = host, delay
    else:
        paused = None
    if paused is not None:
        host, delay = paused
        raise RateLimitedError(
            f"{host} is rate limiting requests; try again in {math.ceil(delay)}s"
        )


@dataclass(frozen=True, slots=True)
class FetchedImage:
    """Validated remote image payload and the media type its bytes encode."""

    data: bytes
    media_type: str


def _url_origin(url: str) -> tuple[str, str, int | None]:
    """Return a normalized URL origin for redirect policy decisions."""
    parsed = urlsplit(url)
    try:
        port = parsed.port
    except ValueError:
        port = None
    if port is None:
        port = {"http": 80, "https": 443}.get(parsed.scheme.lower())
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), port


async def _is_allowed_image_url(
    url: str,
    *,
    allowed_private_origin: tuple[str, str, int | None] | None,
) -> bool:
    """Return whether a public or explicitly trusted private URL may be fetched."""
    return not await is_private_url(url) or (
        allowed_private_origin is not None
        and _url_origin(url) == allowed_private_origin
    )


async def _safe_redirect_url(
    current_url: str,
    response: httpx2.Response,
    *,
    allowed_private_origin: tuple[str, str, int | None] | None = None,
) -> str | None:
    """Return a validated redirect target, or None when redirecting is unsafe."""
    location = response.headers.get("location")
    if not location:
        return None

    next_url = urljoin(str(response.url) or current_url, location)

    if not await _is_allowed_image_url(
        next_url,
        allowed_private_origin=allowed_private_origin,
    ):
        return None
    return next_url


def is_valid_image_format(url: str) -> bool:
    """
    Check whether an image URL has a supported extension.

    URLs without a recognizable extension are accepted so the caller can verify
    them later by sniffing the response bytes.
    """
    filename = urlsplit(url).path.rsplit("/", 1)[-1].lower()
    return "." not in filename or filename.endswith((".jpg", ".jpeg", ".png"))


@asynccontextmanager
async def _image_response(
    url: str,
    client: httpx2.AsyncClient,
    *,
    request_timeout: float,
    allow_private: bool,
    headers: dict[str, str] | None,
    params: dict[str, str] | None = None,
) -> AsyncGenerator[httpx2.Response]:
    """Keep redirects manual so every hop is checked before credentials are sent."""
    allowed_private_origin = _url_origin(url) if allow_private else None
    if not await _is_allowed_image_url(
        url, allowed_private_origin=allowed_private_origin
    ):
        raise RemoteImageError("Private image URLs are not allowed")

    request_headers = {**REMOTE_IMAGE_REQUEST_HEADERS, **(headers or {})}
    for _ in range(MAX_IMAGE_REDIRECTS + 1):
        host = _host(url)
        await IMAGE_HOST_PAUSES.wait(host)
        async with client.stream(
            "GET",
            url,
            timeout=request_timeout,
            headers=request_headers,
            params=params,
            follow_redirects=False,
        ) as response:
            status = response.status_code
            if status == HTTPStatus.TOO_MANY_REQUESTS:
                pause = IMAGE_HOST_PAUSES.limited(
                    host, retry_after=retry_after_seconds(response)
                )
                raise RateLimitedError(
                    f"{host} is rate limiting requests; pausing them for {pause}s"
                )
            if response.is_error:
                raise RemoteImageError(f"{host} returned HTTP {status}")
            IMAGE_HOST_PAUSES.succeeded(host)
            if status not in IMAGE_REDIRECT_STATUSES:
                yield response
                return
            next_url = await _safe_redirect_url(
                url, response, allowed_private_origin=allowed_private_origin
            )
            if not next_url:
                raise RemoteImageError("Unsafe image redirect")
            if _url_origin(next_url) != _url_origin(str(response.url)):
                request_headers = dict(REMOTE_IMAGE_REQUEST_HEADERS)
                params = None
            url = next_url
    raise RemoteImageError("Too many image redirects")


def _check_image_size(size: int, max_bytes: int) -> None:
    if size > max_bytes:
        raise RemoteImageError(
            f"Remote image exceeds {max_bytes // (1024 * 1024)} MiB limit"
        )


def _response_size(
    response: httpx2.Response, max_bytes: int, *, allow_generic_image: bool = False
) -> int | None:
    content_type = response.headers.get("content-type", "")
    if not is_supported_remote_image_type(
        content_type, allow_generic_image=allow_generic_image
    ):
        raise RemoteImageError(
            "The server returned "
            f"{normalise_content_type(content_type)} instead of a JPG or PNG image"
        )
    raw_length = response.headers.get("content-length")
    if raw_length is None:
        return None
    try:
        length = int(raw_length)
    except ValueError as exc:
        raise RemoteImageError("Invalid Content-Length header") from exc
    if length < 0:
        raise RemoteImageError("Invalid Content-Length header")
    _check_image_size(length, max_bytes)
    return length


async def sniff_image_size(
    url: str,
    client: httpx2.AsyncClient,
    *,
    allow_private: bool = False,
    headers: dict[str, str] | None = None,
) -> tuple[int, int]:
    """Close the stream as soon as dimensions are available, within the sniff limit.

    Returns ``(0, 0)`` when the image cannot be measured.

    Raises:
        RateLimitedError: When the image host is rate-limiting Overture.
    """
    try:
        async with _image_response(
            url,
            client,
            request_timeout=5.0,
            allow_private=allow_private,
            headers=headers,
        ) as response:
            _response_size(response, MAX_IMAGE_BYTES)
            parser = ImageFile.Parser()
            consumed = 0
            async for chunk in response.aiter_bytes(chunk_size=1024):
                consumed += len(chunk)
                if consumed > MAX_SNIFF_BYTES:
                    return 0, 0
                parser.feed(chunk)
                if parser.image:
                    return parser.image.size
    except RateLimitedError:
        raise
    except httpx2.HTTPError, OSError, ValueError:
        return 0, 0
    return 0, 0


def normalise_content_type(content_type: str) -> str:
    """Return a lower-cased MIME type without charset metadata."""
    return content_type.split(";", 1)[0].strip().lower()


def is_supported_remote_image_type(
    content_type: str, *, allow_generic_image: bool = False
) -> bool:
    """Return whether a response's declared type may be an image Overture takes.

    A response that names no type, or only a generic binary one, passes: some
    hosts serve images that way, and the bytes are checked once they arrive.
    """
    mime = normalise_content_type(content_type)
    if not mime or mime in _UNTYPED_CONTENT_TYPES:
        return True
    if mime in SUPPORTED_IMAGE_CONTENT_TYPES:
        return True
    return allow_generic_image and mime.startswith("image/")


async def fetch_image(
    url: str,
    client: httpx2.AsyncClient,
    *,
    allow_generic_image: bool = False,
    allow_private: bool = False,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    max_bytes: int = MAX_IMAGE_BYTES,
    on_progress: BytesProgress | None = None,
    transfer_slots: asyncio.Semaphore | None = SHARED_IMAGE_TRANSFERS,
    rate_limit_retries: int = 0,
) -> FetchedImage:
    """Download and validate one bounded image payload.

    Only JPEG and PNG are accepted unless *allow_generic_image* is set, in
    which case any raster format Pillow decodes is, for images that are only
    shown or compared and never saved. The transfer waits for one of
    *transfer_slots*; a caller that bounds its own concurrency passes ``None``.
    Background work passes *rate_limit_retries* (:data:`RATE_LIMIT_RETRIES`)
    to wait out the pause a rate limit starts and ask again, so a slow host
    delays its work instead of failing it.

    Raises:
        RateLimitedError: When the host still rate-limits after the retries.
    """
    retries_left = rate_limit_retries
    while True:
        try:
            return await _fetch_image_once(
                url,
                client,
                allow_generic_image=allow_generic_image,
                allow_private=allow_private,
                headers=headers,
                params=params,
                max_bytes=max_bytes,
                on_progress=on_progress,
                transfer_slots=transfer_slots,
            )
        except RateLimitedError:
            if not retries_left:
                raise
            retries_left -= 1


async def _fetch_image_once(
    url: str,
    client: httpx2.AsyncClient,
    *,
    allow_generic_image: bool,
    allow_private: bool,
    headers: dict[str, str] | None,
    params: dict[str, str] | None,
    max_bytes: int,
    on_progress: BytesProgress | None,
    transfer_slots: asyncio.Semaphore | None,
) -> FetchedImage:
    slot: AbstractAsyncContextManager[object] = (
        nullcontext() if transfer_slots is None else transfer_slots
    )
    # Wait before taking a slot, so a paused host never holds the slots that
    # fetches from other hosts need.
    await IMAGE_HOST_PAUSES.wait(_host(url))
    async with slot:
        async with _image_response(
            url,
            client,
            request_timeout=30.0,
            allow_private=allow_private,
            headers=headers,
            params=params,
        ) as response:
            expected = _response_size(
                response, max_bytes, allow_generic_image=allow_generic_image
            )
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                total += len(chunk)
                _check_image_size(total, max_bytes)
                chunks.append(chunk)
                if on_progress:
                    await on_progress(total, expected)

        data = b"".join(chunks)
        try:
            image_format = encoded_image_format(data)
            if not allow_generic_image:
                saved_image_extension(image_format)
        except UnsupportedImageFormatError as exc:
            raise RemoteImageError(str(exc)) from exc
        return FetchedImage(data=data, media_type=Image.MIME[image_format])
