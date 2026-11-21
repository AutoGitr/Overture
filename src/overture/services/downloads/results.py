"""What a finished download hands over to be saved and recorded."""

lazy from dataclasses import dataclass

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.ledger import (
    FileFacts,
    clear_selection,
    record_file,
    record_written,
    select_art,
    select_theme,
    select_upload,
)
lazy from ...db.models.media_item import MediaItem
lazy from ...domain import ArtType, ServerAsset, ThemeIdSource
lazy from ...repositories.seasons import SeasonRepository
lazy from ...utils.art_urls import PublicArtUrl
lazy from ...utils.time import utc_now
lazy from ..storage.assets import StoredFile
lazy from ..themes.youtube_resolver import DownloadError


@dataclass(slots=True, frozen=True)
class DownloadedArt:
    """One finished artwork download, ready to be written to its slot."""

    art_type: ArtType
    season_id: int | None
    url: PublicArtUrl | None
    fingerprint: str | None
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

        kind = self.art_type.server_asset
        facts = FileFacts(
            file_hash=stored.file_hash,
            file_mtime_ns=stored.mtime_ns,
            file_size=stored.size,
            fingerprint=self.fingerprint,
            width=self.width,
            height=self.height,
        )
        if self.upload_hash:
            select_upload(owner, kind, self.upload_hash)
            record_written(owner, kind, facts, at=utc_now())
        elif self.url:
            select_art(owner, kind, self.url)
            record_written(owner, kind, facts, at=utc_now())
        else:
            clear_selection(owner, kind)
            record_file(owner, kind, facts, at=utc_now())
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
        record_written(
            item,
            ServerAsset.THEME,
            FileFacts(
                file_hash=stored.file_hash,
                file_mtime_ns=stored.mtime_ns,
                file_size=stored.size,
                duration=self.duration,
            ),
            at=utc_now(),
        )
        session.add(item)


@dataclass(slots=True, frozen=True)
class DownloadedCollectionTheme:
    """One finished collection theme download, ready for the media server."""

    youtube_id: str
    title: str | None
    duration: int | None
    audio_bytes: bytes
    #: The audio stream's hash without tags, which a server's copy is compared by.
    fingerprint: str | None = None


type DownloadResult = DownloadedArt | DownloadedTheme


@dataclass(slots=True, frozen=True)
class PreparedDownload:
    """Complete bytes and metadata, ready for the uncancellable save phase.

    Where they go is decided only when they are saved, under the item's lock,
    as a sync can move the item's folder while they download.
    """

    data: bytes
    result: DownloadResult
    file_hash: str | None = None
    #: The image's file extension; themes are always MP3.
    extension: str | None = None


@dataclass(slots=True, frozen=True)
class DownloadTarget:
    """Where a download is written, inside the folder it may write in."""

    #: Each name the servers holding the item read it under; the first is the
    #: one recorded.
    paths: tuple[str, ...]
    trusted_root: str
