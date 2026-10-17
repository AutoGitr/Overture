"""Uploading a downloaded theme to a media-server collection."""

lazy import logging

lazy from ... import protocols
lazy from ...db.completion import collection_theme_status
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.session import Database
lazy from ...domain import JobStatus, MediaType, ServerType
lazy from ...media_servers.plex import PlexProvider
lazy from ...protocols import ProgressCallback
lazy from ...repositories.collection_themes import CollectionThemeRepository
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...utils.file import compute_bytes_hash
lazy from ...utils.time import utc_now
lazy from ..themes.youtube_resolver import DownloadError
lazy from .recovery import CollectionUploadIntent
lazy from .theme import DownloadThemeHandler

logger = logging.getLogger(__name__)


async def upload_collection_theme(
    job: DownloadJob,
    *,
    provider: PlexProvider | None,
    theme_handler: DownloadThemeHandler,
    progress: ProgressCallback,
    publisher: protocols.EventPublisher,
    database: Database,
) -> None:
    """Download a collection's theme, upload it, and record the result.

    What the upload will be is recorded first, so a restart after an
    interrupted upload can check whether the server already holds it.

    Raises:
        DownloadError: When the server cannot hold collection themes, or the
            upload did not take.
    """
    if provider is None or job.collection_server_id is None:
        raise DownloadError("The media server does not support collection themes")
    downloaded = await theme_handler.download_collection_theme(job, progress)
    await progress(85, "uploading")
    intent = CollectionUploadIntent(
        file_hash=compute_bytes_hash(downloaded.audio_bytes),
        title=downloaded.title,
        duration=downloaded.duration,
    )
    async with database.write_session() as session:
        stored = await session.get(DownloadJob, job.id)
        if stored is None:
            raise DownloadError("Job went away before upload")
        stored.write_intent = intent.model_dump_json()
        session.add(stored)
    server_theme_id = await provider.upload_collection_theme(
        job.collection_server_id, downloaded.audio_bytes
    )
    await record_collection_theme(
        job,
        intent,
        server_theme_id,
        server_type=provider.server_type,
        publisher=publisher,
        database=database,
    )


async def verify_collection_upload(
    job: DownloadJob,
    *,
    provider: PlexProvider | None,
    publisher: protocols.EventPublisher,
    database: Database,
) -> None:
    """Finish an interrupted upload once the server proves it holds the bytes.

    Raises:
        DownloadError: When the upload cannot be shown to have completed.
    """
    if job.write_intent is None:
        raise DownloadError("Upload did not reach remote commit")
    if provider is None or job.collection_server_id is None:
        raise DownloadError("Remote collection theme cannot be verified")
    intent = CollectionUploadIntent.model_validate_json(job.write_intent)
    theme_id = await provider.verify_collection_theme(
        job.collection_server_id, intent.file_hash
    )
    if theme_id is None:
        raise DownloadError("Remote collection theme does not match upload")
    await record_collection_theme(
        job,
        intent,
        theme_id,
        server_type=provider.server_type,
        publisher=publisher,
        database=database,
    )


async def record_collection_theme(
    job: DownloadJob,
    intent: CollectionUploadIntent,
    server_theme_id: str,
    *,
    server_type: ServerType,
    publisher: protocols.EventPublisher,
    database: Database,
) -> None:
    """Persist an uploaded or verified collection theme and mark the job done."""
    now = utc_now()
    media_type = MediaType(job.collection_media_type or MediaType.MOVIE)
    async with database.write_session() as session:
        stored_job = await DownloadJobRepository(session).get(job.id)
        if not stored_job:
            raise DownloadError("Job went away mid-download")
        await CollectionThemeRepository(session).upsert_uploaded_theme(
            server_item_id=job.collection_server_id or "",
            media_type=media_type,
            server_type=server_type,
            youtube_id=job.target_url or "",
            youtube_title=intent.title,
            youtube_duration=intent.duration,
            server_theme_id=server_theme_id,
            timestamp=now,
        )
        stored_job.status = JobStatus.DONE
        stored_job.progress_percent = 100
        stored_job.completed_at = now
        stored_job.write_intent = None
        session.add(stored_job)

    job.status = JobStatus.DONE
    job.progress_percent = 100
    job.completed_at = now

    try:
        await publisher.broadcast(
            "collection.theme.updated",
            {
                "server_id": job.collection_server_id,
                "media_type": media_type,
                "has_theme": True,
                "youtube_id": job.target_url,
                "youtube_title": intent.title,
                "youtube_duration": intent.duration,
                "theme_status": collection_theme_status(
                    server_has_theme=True, youtube_id=job.target_url
                ),
            },
        )
    except Exception:
        logger.exception("Could not announce collection theme download %s", job.id)
