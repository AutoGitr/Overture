"""Artwork download handling."""

lazy from dataclasses import dataclass

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...config import Settings
lazy from ...db.art_slots import (
    ArtFileFacts,
    clear_art_selection,
    record_art_file,
    select_art,
)
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.season import Season
lazy from ...db.session import Database
lazy from ...domain import ArtType
lazy from ...integrations.proxy import ProxyClientManager
lazy from ...media_servers.registry import ProviderRegistry
lazy from ...protocols import ProgressCallback
lazy from ...repositories.seasons import SeasonRepository
lazy from ...utils.art_urls import public_art_url
lazy from ...utils.image import (
    RemoteImageError,
    UnsupportedImageFormatError,
    encoded_image_extension,
    fetch_image_bytes,
    get_image_size_from_bytes,
)
lazy from ...utils.progress import StageProgress
lazy from ...utils.security import remove_sensitive_url_params
lazy from ...utils.ssrf import is_private_url
lazy from ...utils.threads import owned_thread
lazy from ..art.phash import PhashService
lazy from ..storage.assets import AssetStorage, StoredFile, require_folder_path
lazy from ..themes.youtube_resolver import DownloadError
lazy from .protocols import PreparedDownload


@dataclass(slots=True, frozen=True)
class DownloadedArt:
    """One finished artwork download, ready to be written to its slot."""

    art_type: ArtType
    season_id: int | None
    url: str | None
    phash: str | None
    width: int | None
    height: int | None

    async def record(
        self, session: AsyncSession, item: MediaItem, stored: StoredFile
    ) -> None:
        """Record the file and the selection it came from, together.

        A source with no storable public URL (a media-server image) leaves the
        slot without a selection: the old URL no longer describes the file.

        Raises:
            DownloadError: When the season this art belonged to is gone.
        """
        owner = await SeasonRepository(session).art_owner(
            item, self.art_type, self.season_id
        )
        if owner is None:
            raise DownloadError("Season not found")
        if self.url is None:
            clear_art_selection(owner, self.art_type)
        else:
            select_art(owner, self.art_type, self.url)
        record_art_file(
            owner,
            self.art_type,
            ArtFileFacts(
                file_hash=stored.file_hash,
                phash=self.phash,
                width=self.width,
                height=self.height,
                file_mtime_ns=stored.mtime_ns,
                file_size=stored.size,
            ),
        )
        session.add(owner)


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
        progress_cb: ProgressCallback,
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
        stage = StageProgress(progress_cb, stage="downloading", start=10, end=70)
        await stage.report(0)
        try:
            return await fetch_image_bytes(
                target_url,
                await self._image_clients.get_client(target_url),
                allow_private=trusted_media_server,
                headers=headers,
                on_progress=stage.report_bytes,
                # ART_DOWNLOAD_WORKERS bounds the art lane; a bulk match's
                # comparisons must not hold its downloads back.
                transfer_slots=None,
            )
        except RemoteImageError as exc:
            raise DownloadError(str(exc)) from exc

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
        image_data = await self._fetch_source_image(
            target_url,
            trusted_media_server=trusted_media_server,
            progress_cb=progress_cb,
        )
        await progress_cb(70, "hashing")
        phash = await self.phash.compute_from_bytes(image_data)

        await progress_cb(85, "writing")
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
            storage=self.asset_storage,
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
