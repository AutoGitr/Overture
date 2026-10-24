"""FastAPI responses for the cached images of local artwork."""

lazy from fastapi.responses import FileResponse

lazy from ...domain import ImageSize
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import THUMB_MEDIA_TYPE, UnsupportedImageFormatError
lazy from .image_cache import CachedOriginal, ImageCache

_NO_CACHE = frozendict({"Cache-Control": "no-cache"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub
#: For a URL that names the hash of the image it serves: those bytes never change.
_IMMUTABLE = frozendict({"Cache-Control": "private, max-age=31536000, immutable"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub


async def cached_image_response(
    cache: ImageCache,
    original: CachedOriginal,
    *,
    size: ImageSize | None,
    current: bool,
) -> FileResponse:
    """Return *original*, or its thumbnail when a *size* is asked for.

    The browser may keep the response for good only when *current*: the URL
    named the very image served, so a slot whose image changed since is never
    shown stale.

    Raises:
        PublicServiceError: When the thumbnail cannot be rendered from the image.
    """
    headers = _IMMUTABLE if current else _NO_CACHE
    if size is None:
        return FileResponse(
            original.path, media_type=original.media_type, headers=headers
        )
    try:
        thumb = await cache.thumb(original)
    except UnsupportedImageFormatError as exc:
        raise PublicServiceError(422, "Unreadable image file") from exc
    return FileResponse(thumb, media_type=THUMB_MEDIA_TYPE, headers=headers)
