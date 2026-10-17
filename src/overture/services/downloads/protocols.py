"""What a finished download hands over to be saved and recorded."""

lazy from dataclasses import dataclass
lazy from typing import Protocol

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.models.media_item import MediaItem
lazy from ..storage.assets import AssetStorage, StoredFile


class DownloadResult(Protocol):
    """What a finished download still has to record against the library.

    Downloading and recording are separated on purpose: the fetch, the file
    write and the hashing take as long as they take, while recording is a few
    rows. Only the recording runs inside a transaction, so a slow download
    never holds SQLite's single write lock against the rest of the app.
    """

    async def record(
        self, session: AsyncSession, item: MediaItem, stored: StoredFile
    ) -> None:
        """Apply this download to the item, or the season, that owns it."""
        ...


@dataclass(slots=True, frozen=True)
class PreparedDownload:
    """Complete bytes and metadata, ready for the uncancellable save phase."""

    storage: AssetStorage
    target_path: str
    trusted_root: str
    data: bytes
    result: DownloadResult
