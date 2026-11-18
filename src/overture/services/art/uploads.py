"""Artwork people upload, kept for good apart from the image cache."""

lazy import logging
lazy import os

lazy from sqlmodel import col, select

lazy from ...db.art_slots import ArtFileFacts
lazy from ...db.models.art import ArtSlot
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.session import Database
lazy from ...schemas.art import ArtUploadResponse
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.image import UnsupportedImageFormatError, inspect_saved_image
lazy from ...utils.threads import owned_thread
lazy from ..storage.image_cache import CachedOriginal, ImageCache
lazy from .phash import PhashService

logger = logging.getLogger(__name__)

#: Why a selection names an upload Overture does not hold.
UPLOAD_GONE = "The uploaded image is no longer kept; upload it again"


class ArtUploads:
    """Keep uploaded images and describe kept images to the slots that select them.

    An upload is kept under the hash of its bytes in the uploads folder, which
    Overture never prunes: it holds the only copy. Generated art is described
    the same way but kept in the cache, since it can be drawn again.
    """

    def __init__(
        self, *, database: Database, image_cache: ImageCache, phash: PhashService
    ) -> None:
        self._database = database
        self._image_cache = image_cache
        self._phash = phash

    async def adopt_from_cache(self) -> None:
        """Move the uploads a slot or queued download selects out of the cache."""
        async with self._database.read_session() as session:
            slots = await session.exec(
                select(ArtSlot.upload_hash).where(
                    col(ArtSlot.upload_hash).is_not(None),
                    col(ArtSlot.generated_style).is_(None),
                )
            )
            queued = await session.exec(
                select(DownloadJob.upload_hash).where(
                    col(DownloadJob.upload_hash).is_not(None)
                )
            )
            hashes = {upload for upload in (*slots, *queued) if upload}
        if moved := await self._image_cache.adopt_uploads(hashes):
            logger.info("Moved %d uploaded images out of the image cache", moved)

    async def store(self, data: bytes) -> ArtUploadResponse:
        """Keep an uploaded JPEG or PNG and render its thumbnail.

        Raises:
            PublicServiceError: 415 when the bytes are not a readable JPEG or
                PNG within the pixel limit.
        """
        try:
            original = await self._image_cache.store_upload(data)
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
        """Describe a kept upload or generated image as the file a slot records.

        Raises:
            PublicServiceError: 409 when Overture does not hold it.
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
        """Return a kept upload's or generated image's bytes and media type.

        Raises:
            PublicServiceError: 409 when Overture does not hold it.
        """
        original, _ = await self._original(upload_hash)
        return await owned_thread(original.path.read_bytes), original.media_type
