"""Persist the precise intent of an atomic local asset replacement."""

lazy import json

lazy from pydantic import BaseModel, ConfigDict
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...db.art_slots import read_art_slot
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_item import MediaItem
lazy from ...domain import ArtType, JobType
lazy from ...repositories.seasons import SeasonRepository
lazy from ...utils.threads import owned_thread
lazy from ..storage.assets import AssetStorage, StoredFile
lazy from .art import DownloadedArt
lazy from .theme import DownloadedTheme


class WriteIntent(BaseModel):
    """Enough metadata to record a verified file without fetching it again."""

    model_config = ConfigDict(extra="forbid")

    target: str
    root: str
    file_hash: str
    result: DownloadedArt | DownloadedTheme


# The downloaded results are dataclasses whose modules import their field types
# for type checking only; validating them needs those types at runtime.
WriteIntent.model_rebuild(_types_namespace={"ArtType": ArtType})


class CollectionUploadIntent(BaseModel):
    """Expected bytes and metadata for an ambiguous remote upload."""

    model_config = ConfigDict(extra="forbid")

    file_hash: str
    title: str | None
    duration: int | None


#: The selection state of a job whose item or season no longer exists.
_GONE = json.dumps(None)


async def selection_state(session: AsyncSession, job: DownloadJob) -> str:
    """Capture the selection and identity that a queued job may replace."""
    item = await session.get(MediaItem, job.media_item_id)
    if item is None:
        return _GONE
    state: dict[str, object] = {
        "folder": item.folder_path,
        "server_id": item.server_item_id,
    }
    if job.job_type is JobType.ART and job.art_type is not None:
        owner = await SeasonRepository(session).art_owner(
            item, job.art_type, job.season_id
        )
        if owner is None:
            return _GONE
        state["art"] = read_art_slot(owner, job.art_type).model_dump(mode="json")
        state["asset_folder"] = owner.folder_path
    else:
        state.update(
            youtube_id=item.youtube_id,
            file_hash=item.theme_file_hash,
            cleared=item.theme_provenance_cleared,
        )
    return json.dumps(state, sort_keys=True)


async def verified_write(
    storage: AssetStorage, intent: WriteIntent
) -> StoredFile | None:
    """Return the file an interrupted write left, if it holds the intended bytes.

    A different file may be a newer external edit, so it is never taken for
    the download's own.

    Raises:
        PathTraversalError: When the target left its trusted root.
        TargetDirectoryMissingError: When the target's folder is gone.
    """
    await owned_thread(storage.validate_target, intent.target, intent.root)
    found = await owned_thread(storage.stored_file, intent.target)
    return found if found is not None and found.file_hash == intent.file_hash else None
