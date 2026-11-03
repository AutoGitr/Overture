"""Image utility functions."""

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
lazy from io import BytesIO
lazy from pathlib import Path
lazy from urllib.parse import urljoin, urlsplit

lazy import httpx2
lazy from PIL import Image, ImageFile, ImageOps, UnidentifiedImageError

lazy from ..domain import ArtType, AspectRatioTolerance
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
#: AVIF is the most compact format every current browser decodes, and a
#: thumbnail is encoded once per image and then kept.
THUMB_MEDIA_TYPE = "image/avif"
THUMB_EXTENSION = ".avif"
#: AVIF quality of thumbnails: visually close to the original at a fraction of
#: the size of a JPEG.
_THUMB_QUALITY = 60
#: Most pixels Overture decodes from one image.
MAX_IMAGE_PIXELS = 50_000_000
MAX_REMOTE_IMAGE_BYTES = 20 * 1024 * 1024
MAX_SNIFF_BYTES = 256 * 1024
MAX_IMAGE_REDIRECTS = 5
IMAGE_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


class RemoteImageError(ValueError):
    """Raised when a remote image cannot be fetched or fails validation."""


class RateLimitedError(RemoteImageError):
    """Raised when an image host is rate-limiting Overture."""


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


class UnsupportedImageFormatError(ValueError):
    """Raised when local image bytes use an unsupported encoded format."""


#: The encoded formats Overture saves, with the extension each is saved under.
SAVED_IMAGE_EXTENSIONS = frozendict({"JPEG": ".jpg", "PNG": ".png"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub
#: The media type each saved extension is served as.
SAVED_MEDIA_TYPES = frozendict({".jpg": "image/jpeg", ".png": "image/png"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub


@dataclass(frozen=True, slots=True)
class FetchedImage:
    """Validated remote image payload and the media type its bytes encode."""

    data: bytes
    media_type: str


def get_local_image_size(path: Path) -> tuple[int, int]:
    """Return local image dimensions, or ``(0, 0)`` when unreadable."""
    try:
        with Image.open(path) as image:
            return image.size
    except UnidentifiedImageError, OSError, ValueError:
        return 0, 0


def render_thumb(path: Path, bounds: tuple[int, int]) -> bytes:
    """Return the image at *path* shrunk to fit *bounds*, as AVIF.

    The shown orientation is kept. An image already inside *bounds* is only
    re-encoded, never enlarged.

    Raises:
        UnsupportedImageFormatError: When the file is not a readable image
            within the pixel limit.
    """
    try:
        with Image.open(path) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise UnsupportedImageFormatError(
                    "Image dimensions exceed safety limit"
                )
            # A JPEG decodes straight to a reduced scale, far cheaper than in
            # full. Its reduction never leaves less than the thumbnail needs,
            # whichever way an EXIF orientation turns it.
            image.draft("RGB", bounds)
            rendition = ImageOps.exif_transpose(image)
            rendition.thumbnail(bounds)
            if rendition.mode not in {"RGB", "RGBA"}:
                alpha = rendition.has_transparency_data
                rendition = rendition.convert("RGBA" if alpha else "RGB")
            buffer = BytesIO()
            rendition.save(buffer, "AVIF", quality=_THUMB_QUALITY, speed=8)
            return buffer.getvalue()
    except UnsupportedImageFormatError:
        raise
    except (
        Image.DecompressionBombError,
        UnidentifiedImageError,
        OSError,
        ValueError,
    ) as exc:
        raise UnsupportedImageFormatError("Unreadable image file") from exc


def _inspect_image(source: Path | BytesIO, unreadable: str) -> tuple[str, int, int]:
    """Return the Pillow format name and dimensions of a readable image."""
    try:
        with Image.open(source) as image:
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise UnsupportedImageFormatError(
                    "Image dimensions exceed safety limit"
                )
            image_format = image.format
            width, height = image.size
    except UnsupportedImageFormatError:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise UnsupportedImageFormatError(unreadable) from exc
    if image_format is None:
        raise UnsupportedImageFormatError(unreadable)
    if image_format not in Image.MIME:
        raise UnsupportedImageFormatError(f"Unsupported image format: {image_format}")
    return image_format, width, height


def encoded_image_format(image_data: bytes) -> str:
    """Return the Pillow format name, such as ``WEBP``, of readable image bytes."""
    return _inspect_image(BytesIO(image_data), "Unreadable image bytes")[0]


def saved_image_extension(image_format: str) -> str:
    """Return the extension an image in *image_format* is saved under.

    Raises:
        UnsupportedImageFormatError: When Overture does not save that format.
    """
    extension = SAVED_IMAGE_EXTENSIONS.get(image_format)
    if extension is None:
        raise UnsupportedImageFormatError(
            f"Unsupported image format: {image_format}. Only JPEG and PNG are allowed."
        )
    return extension


def inspect_saved_image(source: Path | bytes) -> tuple[str, int, int]:
    """Return the saved extension and dimensions of a readable JPEG or PNG.

    Raises:
        UnsupportedImageFormatError: When *source* is not a readable JPEG or PNG
            within the pixel limit.
    """
    if isinstance(source, bytes):
        image_format, width, height = _inspect_image(
            BytesIO(source), "Unreadable image bytes"
        )
    else:
        image_format, width, height = _inspect_image(source, "Unreadable image file")
    return saved_image_extension(image_format), width, height


def encoded_image_extension(image_data: bytes) -> str:
    """Return the extension readable JPEG or PNG bytes are saved under."""
    return inspect_saved_image(image_data)[0]


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


def is_valid_aspect_ratio(
    width: int,
    height: int,
    art_type: ArtType,
    tolerance: AspectRatioTolerance,
) -> bool:
    """Check if an image matches the expected aspect ratio for its slot.

    Unmeasured images are rejected unless the check is off.
    """
    if tolerance.fraction is None:
        return True
    if not width or not height:
        return False
    expected = art_type.aspect_ratio
    return abs(width / height - expected) / expected <= tolerance.fraction


def has_incorrect_aspect_ratio(
    width: int | None,
    height: int | None,
    art_type: ArtType,
    tolerance: AspectRatioTolerance,
) -> bool:
    """Return whether known dimensions break the expected ratio for *art_type*.

    Unlike :func:`is_valid_aspect_ratio`, missing dimensions are not a fault:
    artwork that has not been measured is not reported as misshapen.
    """
    return bool(
        width
        and height
        and not is_valid_aspect_ratio(width, height, art_type, tolerance)
    )


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
            _response_size(response, MAX_REMOTE_IMAGE_BYTES)
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


async def fetch_image_bytes(
    url: str,
    client: httpx2.AsyncClient,
    *,
    allow_generic_image: bool = False,
    allow_private: bool = False,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    max_bytes: int = MAX_REMOTE_IMAGE_BYTES,
    on_progress: BytesProgress | None = None,
    transfer_slots: asyncio.Semaphore | None = SHARED_IMAGE_TRANSFERS,
) -> bytes:
    """Download an image with response-type and size limits enforced."""
    return (
        await fetch_image(
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
    ).data


async def fetch_image(
    url: str,
    client: httpx2.AsyncClient,
    *,
    allow_generic_image: bool = False,
    allow_private: bool = False,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
    max_bytes: int = MAX_REMOTE_IMAGE_BYTES,
    on_progress: BytesProgress | None = None,
    transfer_slots: asyncio.Semaphore | None = SHARED_IMAGE_TRANSFERS,
) -> FetchedImage:
    """Download and validate one bounded image payload.

    Only JPEG and PNG are accepted unless *allow_generic_image* is set, in
    which case any raster format Pillow decodes is, for images that are only
    shown or compared and never saved. The transfer waits for one of
    *transfer_slots*; a caller that bounds its own concurrency passes ``None``.
    """
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
