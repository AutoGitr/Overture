"""What a finished download hands over to be saved and recorded."""

lazy from dataclasses import dataclass

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.art_slots import (
    ArtFileFacts,
    clear_art_selection,
    record_art_file,
    select_art,
    select_upload,
)
lazy from ...db.models.media_item import MediaItem
lazy from ...db.theme_file import ThemeFileFacts, record_theme_file, select_theme
lazy from ...domain import ArtType, ThemeIdSource
lazy from ...repositories.seasons import SeasonRepository
lazy from ...utils.art_urls import PublicArtUrl
lazy from ..storage.assets import StoredFile
lazy from ..themes.youtube_resolver import DownloadError


@dataclass(slots=True, frozen=True)
class DownloadedArt:
    """One finished artwork download, ready to be written to its slot."""

    art_type: ArtType
    season_id: int | None
    url: PublicArtUrl | None
    phash: str | None
    width: int | None
    height: int | None
    #: The uploaded image the file holds, selected in place of a link.
    upload_hash: str | None = None

    async def record(
        self, session: AsyncSession, item: MediaItem, stored: StoredFile
    ) -> None:
        """Record the file and the selection it came from, together.

        A source that is neither an upload nor a storable public URL (a
        media-server image) leaves the slot without a selection: the old one
        no longer describes the file.

        Raises:
            DownloadError: When a season poster names an unrecorded season.
        """
        owner = await SeasonRepository(session).art_owner(
            item, self.art_type, self.season_id
        )
        if owner is None:
            raise DownloadError("Season not found")

        if self.upload_hash:
            select_upload(owner, self.art_type, self.upload_hash)
        elif self.url:
            select_art(owner, self.art_type, self.url)
        else:
            clear_art_selection(owner, self.art_type)
        record_art_file(
            owner,
            self.art_type,
            ArtFileFacts(
                file_hash=stored.file_hash,
                file_mtime_ns=stored.mtime_ns,
                file_size=stored.size,
                width=self.width,
                height=self.height,
                phash=self.phash,
            ),
        )
        session.add(owner)


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
                duration=self.duration,
            ),
        )
        session.add(item)


@dataclass(slots=True, frozen=True)
class DownloadedCollectionTheme:
    """One finished collection theme download, ready for the media server."""

    youtube_id: str
    title: str | None
    duration: int | None
    audio_bytes: bytes


type DownloadResult = DownloadedArt | DownloadedTheme


@dataclass(slots=True, frozen=True)
class PreparedDownload:
    """Complete bytes and metadata, ready for the uncancellable save phase."""

    target_path: str
    trusted_root: str
    data: bytes
    result: DownloadResult
    file_hash: str | None = None
