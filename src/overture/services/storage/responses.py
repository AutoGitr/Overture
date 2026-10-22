"""FastAPI responses for trusted local asset files."""

lazy import stat
lazy from pathlib import Path

lazy from fastapi import Response
lazy from fastapi.responses import FileResponse

lazy from ...db.art_slots import art_file_facts
lazy from ...db.models.art import ArtSlot
lazy from ...domain import ArtType, ImageSize
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import UnsupportedImageFormatError, downscaled_webp
lazy from ...utils.path import is_within_roots
lazy from ...utils.threads import owned_thread

_NO_CACHE = frozendict({"Cache-Control": "no-cache"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub
#: For a URL naming the exact file on disk: those bytes never change.
_IMMUTABLE = frozendict({"Cache-Control": "private, max-age=31536000, immutable"})  # pyright: ignore[reportCallIssue] -- stale frozendict stub
_EXT_MIME = frozendict(
    {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)


def asset_mime_type(path: Path) -> str:
    """Infer a MIME type from an asset filename."""
    return _EXT_MIME.get(path.suffix.lower(), "image/jpeg")


async def local_image_response(
    path: Path,
    root: Path,
    *,
    slot: ArtSlot | None,
    art_type: ArtType,
    size: ImageSize | None,
    version: str | None,
) -> Response | None:
    """Return the image at *path*, or ``None`` when it is not a file under *root*.

    With *size* the image is downscaled in memory; nothing is written. The
    browser may keep the response for good only while *version* is the slot's
    hash and the file on disk is still the one that hash was taken from, so a
    file replaced outside Overture is never shown stale.
    """
    if not is_within_roots(path, [root]):
        return None
    try:
        file_stat = await owned_thread(path.stat)
    except FileNotFoundError, NotADirectoryError:
        return None
    if not stat.S_ISREG(file_stat.st_mode):
        return None
    facts = art_file_facts(slot) if slot is not None else None
    current = (
        facts is not None
        and version == facts.file_hash
        and (file_stat.st_mtime_ns, file_stat.st_size)
        == (facts.file_mtime_ns, facts.file_size)
    )
    headers = _IMMUTABLE if current else _NO_CACHE
    if size is not None:
        try:
            rendition = await downscaled_webp(path, art_type.display_width)
        except UnsupportedImageFormatError as exc:
            raise PublicServiceError(422, "Unreadable image file") from exc
        if rendition is not None:
            return Response(rendition, media_type="image/webp", headers=headers)
    return FileResponse(
        path, media_type=asset_mime_type(path), headers=headers, stat_result=file_stat
    )
