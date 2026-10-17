"""Theme-song download handling."""

lazy from dataclasses import dataclass

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...db.theme_file import ThemeFileFacts, record_theme_file, select_theme
lazy from ...domain import ThemeIdSource
lazy from ...protocols import ProgressCallback
lazy from ..storage.assets import AssetStorage, StoredFile, require_folder_path
lazy from ..themes.youtube_resolver import DownloadError, YouTubeResolver
lazy from .protocols import PreparedDownload


@dataclass(slots=True, frozen=True)
class DownloadedTheme:
    """One finished theme download, ready to be written to its item."""

    youtube_id: str
    title: str | None
    duration: int | None

    async def record(
        self, session: AsyncSession, item: MediaItem, stored: StoredFile
    ) -> None:
        """Record the file and the video it came from, together."""
        select_theme(
            item,
            self.youtube_id,
            source=ThemeIdSource.DOWNLOAD,
            title=self.title,
            duration=self.duration,
        )
        record_theme_file(
            item,
            ThemeFileFacts(
                file_hash=stored.file_hash,
                file_mtime_ns=stored.mtime_ns,
                file_size=stored.size,
            ),
        )
        session.add(item)


@dataclass(slots=True, frozen=True)
class DownloadedCollectionTheme:
    """One finished collection theme download, ready to be uploaded to Plex."""

    youtube_id: str
    title: str | None
    duration: int | None
    audio_bytes: bytes


class DownloadThemeHandler:
    """Resolve and download theme-song audio, and write it to disk."""

    def __init__(
        self,
        *,
        asset_storage: AssetStorage,
        youtube_resolver: YouTubeResolver,
        database: Database,
    ) -> None:
        self._database = database
        self.asset_storage = asset_storage
        self.youtube_resolver = youtube_resolver

    async def download(
        self,
        job: DownloadJob,
        item: MediaItem,
        progress_cb: ProgressCallback,
    ) -> PreparedDownload:
        """Download and transcode a theme without modifying the destination.

        Nothing here writes to the database: a YouTube download and an ffmpeg
        transcode take as long as they take, and the caller records the result
        in a transaction of its own once they are over.

        Raises:
            DownloadError: When the job names no YouTube ID.
        """
        folder_path = require_folder_path(item)
        youtube_id = job.target_url
        if not youtube_id:
            raise DownloadError("No YouTube ID specified")

        async with self._database.read_session() as session:
            app_settings = await get_app_settings(session)
        min_duration = app_settings.min_duration_seconds
        max_duration = app_settings.max_duration_seconds

        result = await self.youtube_resolver.download_audio(
            youtube_id=youtube_id,
            min_duration=min_duration,
            max_duration=max_duration,
            progress_callback=progress_cb,
            normalize_loudness=app_settings.normalize_theme_loudness,
        )

        target_path = self.asset_storage.resolve_theme_path(folder_path)
        return PreparedDownload(
            storage=self.asset_storage,
            target_path=target_path,
            trusted_root=folder_path,
            data=result.audio_bytes,
            result=DownloadedTheme(
                youtube_id=youtube_id,
                title=result.title,
                duration=result.duration or None,
            ),
        )

    async def download_collection_theme(
        self,
        job: DownloadJob,
        progress_cb: ProgressCallback,
    ) -> DownloadedCollectionTheme:
        """Download one collection theme, returning its audio bytes and metadata."""
        youtube_id = job.target_url
        if not youtube_id:
            raise DownloadError("No YouTube ID specified")

        async with self._database.read_session() as session:
            app_settings = await get_app_settings(session)
        min_duration = app_settings.min_duration_seconds
        max_duration = app_settings.max_duration_seconds

        result = await self.youtube_resolver.download_audio(
            youtube_id=youtube_id,
            min_duration=min_duration,
            max_duration=max_duration,
            progress_callback=progress_cb,
            normalize_loudness=app_settings.normalize_theme_loudness,
        )

        return DownloadedCollectionTheme(
            youtube_id=youtube_id,
            title=result.title,
            duration=result.duration or None,
            audio_bytes=result.audio_bytes,
        )
