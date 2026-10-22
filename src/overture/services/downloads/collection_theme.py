"""Uploading a downloaded theme to a media-server collection."""

lazy from ... import protocols
lazy from ...db.completion import collection_theme_status
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.session import Database
lazy from ...domain import JobStatus, MediaType, ServerType
lazy from ...media_servers.plex import PlexProvider
lazy from ...repositories.collection_themes import CollectionThemeRepository
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...utils.time import utc_now
lazy from ..themes.youtube_resolver import DownloadError
lazy from .results import DownloadedCollectionTheme


async def upload_collection_theme(
    job: DownloadJob,
    downloaded: DownloadedCollectionTheme,
    *,
    provider: PlexProvider | None,
    publisher: protocols.EventPublisher,
    database: Database,
) -> None:
    """Upload a downloaded collection theme and record the result.

    Raises:
        DownloadError: When the server cannot hold collection themes, or the
            upload did not take.
    """
    if provider is None or job.collection_server_id is None:
        raise DownloadError("The media server does not support collection themes")
    server_theme_id = await provider.upload_collection_theme(
        job.collection_server_id, downloaded.audio_bytes
    )
    await record_collection_theme(
        job,
        title=downloaded.title,
        duration=downloaded.duration,
        server_theme_id=server_theme_id,
        server_type=provider.server_type,
        publisher=publisher,
        database=database,
    )


async def record_collection_theme(
    job: DownloadJob,
    *,
    title: str | None,
    duration: int | None,
    server_theme_id: str,
    server_type: ServerType,
    publisher: protocols.EventPublisher,
    database: Database,
) -> None:
    """Persist an uploaded collection theme and mark the job done, if it runs."""
    now = utc_now()
    media_type = MediaType(job.collection_media_type or MediaType.MOVIE)
    async with database.write_session() as session:
        stored_job = await DownloadJobRepository(session).get(job.id)
        if not stored_job or stored_job.status is not JobStatus.RUNNING:
            return
        await CollectionThemeRepository(session).upsert_uploaded_theme(
            server_item_id=job.collection_server_id or "",
            media_type=media_type,
            server_type=server_type,
            youtube_id=job.target_url or "",
            youtube_title=title,
            youtube_duration=duration,
            server_theme_id=server_theme_id,
            timestamp=now,
        )
        stored_job.status = JobStatus.DONE
        stored_job.error_message = None
        stored_job.progress_percent = 100
        stored_job.completed_at = now
        session.add(stored_job)

    job.status = JobStatus.DONE
    job.error_message = None
    job.progress_percent = 100
    job.completed_at = now

    await publisher.broadcast(
        "collection.theme.updated",
        {
            "server_id": job.collection_server_id,
            "media_type": media_type,
            "has_theme": True,
            "youtube_id": job.target_url,
            "youtube_title": title,
            "youtube_duration": duration,
            "theme_status": collection_theme_status(
                server_has_theme=True, youtube_id=job.target_url
            ),
        },
    )
