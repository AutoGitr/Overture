"""Store collection themes through the provider's declared capability."""

lazy from pathlib import Path

lazy from ... import protocols
lazy from ...config import Settings
lazy from ...db.completion import collection_theme_status
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.session import Database
lazy from ...db.theme_file import ThemeFileFacts, record_theme_file
lazy from ...domain import JobStatus, ThemeBulkSource
lazy from ...media_servers.adapters import (
    FolderThemes,
    NoCollectionThemes,
    UploadThemes,
)
lazy from ...media_servers.registry import CollectionProvider
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...utils.assets import THEME_FILENAME
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..collections.theme_files import collection_folder
lazy from ..storage.assets import AssetStorage
lazy from ..themes.youtube_resolver import DownloadError
lazy from .results import DownloadedCollectionTheme


def collection_themes_unavailable(
    provider: CollectionProvider | None, app_config: Settings
) -> str | None:
    """Return why this provider cannot store a collection theme."""
    if provider is None or provider.collections is None:
        return "The media server has no collections Overture can manage"
    if isinstance(provider.collections, NoCollectionThemes):
        return "Emby does not support collection themes"
    if (
        isinstance(provider.collections, FolderThemes)
        and app_config.JELLYFIN_COLLECTIONS_PATH is None
    ):
        return "Set JELLYFIN_COLLECTIONS_PATH to store collection themes"
    return None


async def theme_folder(
    collection_id: int, *, app_config: Settings, database: Database
) -> Path:
    """Resolve a stored collection's trusted theme folder."""
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(collection_id)
    root = app_config.JELLYFIN_COLLECTIONS_PATH
    if row is None or row.server_path is None or root is None:
        raise DownloadError("The collection has no folder for its theme")
    try:
        return await owned_thread(collection_folder, root, row.server_path)
    except ValueError as exc:
        raise DownloadError(str(exc)) from exc


async def collection_theme_unavailable(
    row: MediaCollection, *, provider: CollectionProvider | None, app_config: Settings
) -> str | None:
    """Check the configured capability and this collection's mounted folder."""
    if reason := collection_themes_unavailable(provider, app_config):
        return reason
    if provider and isinstance(provider.collections, FolderThemes):
        root = app_config.JELLYFIN_COLLECTIONS_PATH
        if root is None or not row.server_path:
            return "The collection has no folder for its theme"
        try:
            await owned_thread(collection_folder, root, row.server_path)
        except (OSError, ValueError) as exc:
            return str(exc)
    return None


async def store_collection_theme(
    job: DownloadJob,
    downloaded: DownloadedCollectionTheme,
    *,
    provider: CollectionProvider | None,
    asset_storage: AssetStorage,
    app_config: Settings,
    publisher: protocols.EventPublisher,
    database: Database,
) -> None:
    """Write the collection's theme, then record the file and its provenance."""
    reason = collection_themes_unavailable(provider, app_config)
    if provider is None or job.collection_id is None or reason is not None:
        raise DownloadError(reason or "The job names no collection")
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(job.collection_id)
    if row is None or row.server_type is not provider.server_type:
        raise DownloadError("Collection no longer exists on the configured server")
    server_theme_id = None
    facts = None
    if isinstance(provider.collections, UploadThemes):
        server_theme_id = await provider.upload_collection_theme(
            row.server_item_id, downloaded.audio_bytes
        )
    else:
        folder = await theme_folder(
            job.collection_id, app_config=app_config, database=database
        )
        stored = await asset_storage.write_file_async(
            str(folder / THEME_FILENAME), downloaded.audio_bytes, str(folder)
        )
        facts = ThemeFileFacts(
            stored.file_hash, stored.mtime_ns, stored.size, downloaded.duration
        )
        await provider.refresh_item(row.server_item_id, unlock=())
    await record_collection_theme(
        job,
        title=downloaded.title,
        duration=downloaded.duration,
        server_theme_id=server_theme_id,
        facts=facts,
        publisher=publisher,
        database=database,
    )


async def record_collection_theme(
    job: DownloadJob,
    *,
    title: str | None,
    duration: int | None,
    server_theme_id: str | None,
    facts: ThemeFileFacts | None = None,
    publisher: protocols.EventPublisher,
    database: Database,
) -> None:
    """Record a running download's committed collection theme."""
    now = utc_now()
    async with database.write_session() as session:
        stored_job = await DownloadJobRepository(session).get(job.id)
        row = await session.get(MediaCollection, job.collection_id)
        if not stored_job or stored_job.status is not JobStatus.RUNNING or row is None:
            return
        catalog = await PublicDatasetRepository(session).collections_by_tmdb_id(
            {row.tmdb_collection_id} if row.tmdb_collection_id else set()
        )
        entry = catalog.get(row.tmdb_collection_id or 0)
        source = ThemeBulkSource.YOUTUBE_SEARCH
        if entry and job.target_url == entry.youtube_id_themerrdb:
            source = ThemeBulkSource.THEMERRDB
        elif entry and job.target_url == entry.youtube_id_overturedb:
            source = ThemeBulkSource.OVERTUREDB
        row.sqlmodel_update(
            {
                "youtube_id": job.target_url,
                "youtube_id_source": source,
                "youtube_title": title,
                "youtube_duration": duration,
                "server_theme_id": server_theme_id,
                "updated_at": now,
            }
        )
        record_theme_file(row, facts)
        session.add(row)
        stored_job.sqlmodel_update(
            {
                "status": JobStatus.DONE,
                "error_message": None,
                "progress_percent": 100,
                "completed_at": now,
            }
        )
        session.add(stored_job)
    job.sqlmodel_update(
        {
            "status": JobStatus.DONE,
            "error_message": None,
            "progress_percent": 100,
            "completed_at": now,
        }
    )
    await publisher.broadcast(
        "collection.theme.updated",
        {
            "collection_id": job.collection_id,
            "media_type": row.media_type,
            "has_theme": True,
            "youtube_id": job.target_url,
            "youtube_title": title,
            "youtube_duration": duration,
            "theme_status": collection_theme_status(
                server_has_theme=True, youtube_id=job.target_url
            ),
        },
    )
