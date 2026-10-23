"""Artwork download handling."""

lazy from urllib.parse import urlsplit

lazy import httpx2

lazy from ...config import Settings
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...repositories.seasons import SeasonRepository
lazy from ...utils.art_urls import public_art_url
lazy from ...utils.errors import public_error_message
lazy from ...utils.image import (
    RemoteImageError,
    UnsupportedImageFormatError,
    encoded_image_extension,
    fetch_image_bytes,
    get_image_size_from_bytes,
)
lazy from ...utils.progress import ProgressCallback, StepProgress
lazy from ...utils.security import remove_sensitive_url_params
lazy from ...utils.ssrf import is_private_url
lazy from ...utils.threads import owned_thread
lazy from ..art.phash import PhashService
lazy from ..storage.assets import AssetStorage, require_folder_path
lazy from ..themes.youtube_resolver import DownloadError
lazy from .results import DownloadedArt, PreparedDownload


class DownloadArtHandler:
    """Fetch remote artwork, write local files, and update normalized assets."""

    def __init__(
        self,
        *,
        provider_registry: ProviderRegistry,
        asset_storage: AssetStorage,
        phash: PhashService,
        image_clients: ProxyClientManager,
        app_config: Settings,
        database: Database,
    ) -> None:
        self._app_config = app_config
        self._database = database
        self.provider_registry = provider_registry
        self.asset_storage = asset_storage
        self.phash = phash
        self._image_clients = image_clients

    async def _fetch_source_image(
        self,
        target_url: str,
        *,
        trusted_media_server: bool,
        progress: StepProgress,
    ) -> bytes:
        """Download the chosen artwork, reporting the bytes as they arrive.

        Raises:
            DownloadError: When the URL is private, or the fetch fails.
        """
        if not trusted_media_server and await is_private_url(target_url):
            raise DownloadError(
                "Download blocked: target URL resolves to a private address"
            )

        headers = self.provider_registry.provider.get_download_headers(target_url)
        await progress.enter("downloading")
        try:
            return await fetch_image_bytes(
                target_url,
                await self._image_clients.get_client(target_url),
                allow_private=trusted_media_server,
                headers=headers,
                on_progress=progress.report_bytes,
                # ART_DOWNLOAD_WORKERS bounds the art lane; a bulk match's
                # comparisons must not hold its downloads back.
                transfer_slots=None,
            )
        except RemoteImageError as exc:
            raise DownloadError(str(exc)) from exc
        except httpx2.HTTPError as exc:
            detail = public_error_message(exc) or type(exc).__name__
            raise DownloadError(
                f"Could not reach {urlsplit(target_url).hostname}: {detail}"
            ) from exc

    async def _season(self, job: DownloadJob, item: MediaItem) -> Season | None:
        """Return the season a season poster belongs to.

        Raises:
            DownloadError: When the job names a season that is not the item's.
        """
        if job.art_type is None or not job.art_type.owned_by_season:
            return None
        async with self._database.read_session() as session:
            owner = await SeasonRepository(session).art_owner(
                item, job.art_type, job.season_id
            )
        if not isinstance(owner, Season):
            raise DownloadError("Season not found")
        return owner

    async def download(
        self,
        job: DownloadJob,
        item: MediaItem,
        progress_cb: ProgressCallback,
    ) -> PreparedDownload:
        """Fetch and validate artwork without modifying the destination.

        Nothing here writes to the database: the caller records the result in
        a transaction of its own once the slow part is over.

        Raises:
            DownloadError: When the job is incomplete or the download fails.
        """
        if not job.target_url:
            raise DownloadError("No target URL specified")
        if not job.art_type:
            raise DownloadError("No art type specified")

        target_url = remove_sensitive_url_params(job.target_url)
        trusted_media_server = self._app_config.is_trusted_media_server_url(target_url)
        folder_path = require_folder_path(item)
        art_type = job.art_type

        season = await self._season(job, item)
        progress = StepProgress(progress_cb, ("downloading", "hashing", "writing"))
        image_data = await self._fetch_source_image(
            target_url,
            trusted_media_server=trusted_media_server,
            progress=progress,
        )
        await progress.enter("hashing")
        phash = await self.phash.compute_from_bytes(image_data)

        await progress.enter("writing")
        try:
            ext = encoded_image_extension(image_data)
        except UnsupportedImageFormatError as exc:
            raise DownloadError(str(exc)) from exc
        width, height = get_image_size_from_bytes(image_data)
        target_path = await owned_thread(
            self.asset_storage.resolve_art_path,
            folder_path=folder_path,
            art_type=art_type,
            ext=ext,
            season_folder_path=season.folder_path if season else None,
            season_num=season.season_num if season else None,
        )
        return PreparedDownload(
            target_path=target_path,
            trusted_root=folder_path,
            data=image_data,
            result=DownloadedArt(
                art_type=art_type,
                season_id=season.id if season else None,
                url=await public_art_url(
                    target_url,
                    fetched_publicly=not trusted_media_server,
                    app_config=self._app_config,
                ),
                phash=phash,
                width=width or None,
                height=height or None,
            ),
        )
