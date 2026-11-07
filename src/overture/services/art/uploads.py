"""Artwork people upload, kept in the image cache until a slot selects it."""

lazy import os

lazy from ...db.art_slots import ArtFileFacts
lazy from ...schemas.art import ArtUploadResponse
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import UnsupportedImageFormatError, inspect_saved_image
lazy from ...utils.threads import owned_thread
lazy from ..storage.image_cache import CachedOriginal, ImageCache
lazy from .phash import PhashService

#: Why a selection names an upload the cache no longer keeps.
UPLOAD_GONE = "The uploaded image is no longer kept; upload it again"


class ArtUploads:
    """Keep uploaded images and describe them to the slots that select them.

    An upload is kept under the hash of its bytes like every cached image, so
    the slot that selects it, and the retention pass, treat it like any other.
    """

    def __init__(self, *, image_cache: ImageCache, phash: PhashService) -> None:
        self._image_cache = image_cache
        self._phash = phash

    async def store(self, data: bytes) -> ArtUploadResponse:
        """Keep an uploaded JPEG or PNG and render its thumbnail.

        Raises:
            PublicServiceError: 415 when the bytes are not a readable JPEG or
                PNG within the pixel limit.
        """
        try:
            original = await self._image_cache.store_original(data)
            await self._image_cache.thumb(original)
        except UnsupportedImageFormatError as exc:
            raise PublicServiceError(415, "Upload a JPEG or PNG image") from exc
        return ArtUploadResponse(
            upload_hash=original.file_hash,
            width=original.width or 0,
            height=original.height or 0,
        )

    async def _original(
        self, upload_hash: str
    ) -> tuple[CachedOriginal, os.stat_result]:
        original = await self._image_cache.original(upload_hash)
        if original is None or original.stat is None:
            raise PublicServiceError(409, UPLOAD_GONE)
        return original, original.stat

    async def facts(self, upload_hash: str) -> ArtFileFacts:
        """Describe a kept upload as the file a slot records.

        Raises:
            PublicServiceError: 409 when the cache no longer keeps it.
        """
        original, stat = await self._original(upload_hash)
        _, width, height = await owned_thread(inspect_saved_image, original.path)
        return ArtFileFacts(
            file_hash=original.file_hash,
            phash=await self._phash.compute_from_file(str(original.path)),
            width=width,
            height=height,
            file_mtime_ns=stat.st_mtime_ns,
            file_size=stat.st_size,
        )

    async def read(self, upload_hash: str) -> tuple[bytes, str]:
        """Return a kept upload's bytes and media type.

        Raises:
            PublicServiceError: 409 when the cache no longer keeps it.
        """
        original, _ = await self._original(upload_hash)
        return await owned_thread(original.path.read_bytes), original.media_type
