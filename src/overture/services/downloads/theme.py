"""Theme-song download handling."""

lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.settings import get_app_settings
lazy from ...db.session import Database
lazy from ...utils.progress import ProgressCallback
lazy from ..storage.assets import AssetStorage, require_folder_path
lazy from ..themes.youtube_resolver import DownloadError, YouTubeResolver
lazy from .results import (
    DownloadedTheme,
    DownloadTarget,
    PreparedDownload,
)


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

    def target(self, item: MediaItem) -> DownloadTarget:
        """Return where the item's theme goes, in its folder as it is now.

        Raises:
            DownloadError: When the item has no folder.
        """
        folder_path = require_folder_path(item)
        return DownloadTarget(
            paths=(self.asset_storage.resolve_theme_path(folder_path),),
            trusted_root=folder_path,
        )

    async def download_youtube(
        self,
        youtube_id: str,
        progress_cb: ProgressCallback | None = None,
    ) -> tuple[bytes, DownloadedTheme]:
        """Download and transcode *youtube_id*, returning audio bytes and metadata.

        Raises:
            DownloadError: When *youtube_id* is empty or the download fails.
        """
        if not youtube_id:
            raise DownloadError("No YouTube ID specified")

        async with self._database.read_session() as session:
            app_settings = await get_app_settings(session)
        result = await self.youtube_resolver.download_audio(
            youtube_id=youtube_id,
            min_duration=app_settings.min_duration_seconds,
            max_duration=app_settings.max_duration_seconds,
            progress_callback=progress_cb,
            normalize_loudness=app_settings.normalize_theme_loudness,
        )
        return (
            result.audio_bytes,
            DownloadedTheme(
                youtube_id=youtube_id,
                title=result.title,
                duration=result.duration or None,
                fingerprint=result.fingerprint,
            ),
        )

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
            DownloadError: When the job names no YouTube ID or an item lacks a folder.
        """
        require_folder_path(item)
        audio_bytes, downloaded = await self.download_youtube(
            job.target_url or "", progress_cb
        )
        return PreparedDownload(data=audio_bytes, result=downloaded)
