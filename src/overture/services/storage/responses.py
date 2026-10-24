"""FastAPI responses for the cached images of local artwork."""

lazy from collections.abc import Awaitable, Callable

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
    file_hash: str,
    *,
    restore: Callable[[], Awaitable[CachedOriginal]],
    size: ImageSize | None,
    current: bool,
) -> FileResponse:
    """Return the cached image for *file_hash*, or its thumbnail when *size* is set.

    A kept thumbnail is served directly without looking up the original; *restore*
    is called only when the original is needed and missing from the cache.
    The browser may keep the response for good only when *current*: the URL
    named the very image served, so a slot whose image changed since is never
    shown stale.

    Raises:
        PublicServiceError: When the thumbnail cannot be rendered from the image.
    """
    headers = _IMMUTABLE if current else _NO_CACHE
    if size is not None and (existing := await cache.existing_thumb(file_hash)):
        path, stat_result = existing
        return FileResponse(
            path, media_type=THUMB_MEDIA_TYPE, headers=headers, stat_result=stat_result
        )
    original = await cache.original(file_hash)
    if original is None:
        original = await restore()
    if size is None:
        return FileResponse(
            original.path,
            media_type=original.media_type,
            headers=headers,
            stat_result=original.stat,
        )
    try:
        thumb = await cache.thumb(original)
    except UnsupportedImageFormatError as exc:
        raise PublicServiceError(422, "Unreadable image file") from exc
    return FileResponse(thumb, media_type=THUMB_MEDIA_TYPE, headers=headers)
