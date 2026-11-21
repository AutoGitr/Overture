"""Store collection themes through the provider's declared capability."""

lazy from collections.abc import Sequence
lazy from dataclasses import dataclass
lazy from pathlib import Path

lazy from ... import protocols
lazy from ...db.ledger import (
    ContentFacts,
    Destination,
    FileFacts,
    confirm_delivery,
    record_content,
    record_file,
    select_theme,
)
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_collection import CollectionLibrary, MediaCollection
lazy from ...db.session import Database
lazy from ...domain import DeliveryChannel, JobStatus, ServerAsset, ThemeIdSource
lazy from ...media_servers.adapters import FolderThemes, NoCollectionThemes
lazy from ...media_servers.registry import CollectionProvider, ProviderRegistry
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...utils.assets import THEME_FILENAME
lazy from ...utils.hashing import compute_bytes_hash
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
lazy from ..collections.destinations import collection_destinations
lazy from ..collections.theme_files import collection_folder
lazy from ..storage.assets import AssetStorage
lazy from ..themes.youtube_resolver import DownloadError
lazy from .results import DownloadedCollectionTheme


def _storage_unavailable(provider: CollectionProvider) -> str | None:
    """Why one server cannot store a collection theme, or ``None`` when it can."""
    if isinstance(provider.collections, NoCollectionThemes):
        return f"{provider.server.title} does not support collection themes"
    if (
        isinstance(provider.collections, FolderThemes)
        and provider.server.collections_path is None
    ):
        setting = provider.server.variable("collections_path")
        return f"Set {setting} to store collection themes"
    return None


def collection_themes_unavailable(
    providers: Sequence[CollectionProvider],
) -> str | None:
    """Return why none of the servers *providers* names can store a collection theme."""
    if not providers:
        return "No media server has collections Overture can manage"
    reasons = [_storage_unavailable(provider) for provider in providers]
    return None if None in reasons else reasons[0]


def _part(row: MediaCollection, destination: Destination) -> CollectionLibrary:
    """Return the copy of *row* a server-copy destination names."""
    return next(
        part
        for part in row.copies
        if (part.server_id, part.server_item_id) == destination.key
    )


async def theme_folders(
    row: MediaCollection, provider_registry: ProviderRegistry
) -> list[tuple[Destination, CollectionProvider, CollectionLibrary, Path]]:
    """Resolve the trusted folder each Jellyfin server keeps the collection in.

    Raises:
        DownloadError: When a server's folder cannot be used.
    """
    folders: list[tuple[Destination, CollectionProvider, CollectionLibrary, Path]] = []
    for destination in collection_destinations(
        row, ServerAsset.THEME, provider_registry
    ):
        if destination.channel is not DeliveryChannel.FILE:
            continue
        provider = provider_registry.get(destination.server_id or 0)
        part = _part(row, destination)
        try:
            folder = await owned_thread(
                collection_folder, provider.server, part.server_path
            )
        except ValueError as exc:
            raise DownloadError(str(exc)) from exc
        folders.append((destination, provider, part, folder))
    return folders


async def folder_lacks_theme(
    row: MediaCollection, provider_registry: ProviderRegistry
) -> bool:
    """Whether a Jellyfin folder of the collection holds no theme file.

    A folder Overture cannot use is reported when a theme is stored, not here.
    """
    try:
        folders = await theme_folders(row, provider_registry)
    except DownloadError:
        return False
    for _, _, _, folder in folders:
        if not await owned_thread((folder / THEME_FILENAME).is_file):
            return True
    return False


async def collection_theme_unavailable(
    row: MediaCollection, *, provider_registry: ProviderRegistry
) -> str | None:
    """Check the servers' capability and this collection's mounted folders.

    An inactive collection keeps a chosen theme until a sync puts it back on
    a server, so only the capability applies to it.
    """
    if reason := collection_themes_unavailable(
        provider_registry.collection_providers()
    ):
        return reason
    if not row.copies:
        return None
    if not collection_destinations(row, ServerAsset.THEME, provider_registry):
        return "None of the servers holding the collection can store its theme"
    try:
        await theme_folders(row, provider_registry)
    except DownloadError as exc:
        return str(exc)
    return None


async def store_collection_theme(
    job: DownloadJob,
    downloaded: DownloadedCollectionTheme,
    *,
    provider_registry: ProviderRegistry,
    asset_storage: AssetStorage,
    publisher: protocols.EventPublisher,
    database: Database,
) -> None:
    """Send the collection's theme to every server copy, then record it."""
    if job.collection_id is None:
        raise DownloadError("The job names no collection")
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(job.collection_id)
    if row is None:
        raise DownloadError("Collection no longer exists")
    if reason := await collection_theme_unavailable(
        row, provider_registry=provider_registry
    ):
        raise DownloadError(reason)
    if not row.copies:
        raise DownloadError("The collection is inactive and has no server copy")
    delivered: list[Delivered] = []
    for destination in collection_destinations(
        row, ServerAsset.THEME, provider_registry
    ):
        if destination.channel is DeliveryChannel.UPLOAD:
            theme_id = await provider_registry.get(
                destination.server_id or 0
            ).upload_collection_theme(
                destination.server_item_id or "", downloaded.audio_bytes
            )
            delivered.append(Delivered(destination, ref=theme_id))
    for destination, provider, part, folder in await theme_folders(
        row, provider_registry
    ):
        stored = await asset_storage.write_file_async(
            str(folder / THEME_FILENAME), downloaded.audio_bytes, str(folder)
        )
        delivered.append(
            Delivered(
                destination,
                file=FileFacts(
                    stored.file_hash,
                    stored.mtime_ns,
                    stored.size,
                    duration=downloaded.duration,
                ),
            )
        )
        await provider.refresh_item(part.server_item_id or "", unlock=())
    await record_collection_theme(
        job,
        content=ContentFacts(
            compute_bytes_hash(downloaded.audio_bytes),
            fingerprint=downloaded.fingerprint,
            duration=downloaded.duration,
        ),
        title=downloaded.title,
        duration=downloaded.duration,
        delivered=delivered,
        publisher=publisher,
        database=database,
    )


@dataclass(frozen=True, slots=True)
class Delivered:
    """One server copy a collection theme reached: its theme ID, or its file."""

    destination: Destination
    ref: str | None = None
    file: FileFacts | None = None


async def record_collection_theme(
    job: DownloadJob,
    *,
    content: ContentFacts,
    title: str | None,
    duration: int | None,
    delivered: Sequence[Delivered],
    publisher: protocols.EventPublisher,
    database: Database,
) -> None:
    """Record a running download's collection theme and the copies it reached."""
    now = utc_now()
    async with database.write_session() as session:
        stored_job = await DownloadJobRepository(session).get(job.id)
        row = await session.get(MediaCollection, job.collection_id)
        if not stored_job or stored_job.status is not JobStatus.RUNNING or row is None:
            return
        select_theme(
            row,
            job.target_url or "",
            source=ThemeIdSource.DOWNLOAD,
            title=title,
            duration=duration,
        )
        record_content(row, ServerAsset.THEME, content)
        for each in delivered:
            if each.file is not None:
                record_file(
                    row,
                    ServerAsset.THEME,
                    each.file,
                    destination=each.destination,
                    at=now,
                )
            else:
                confirm_delivery(
                    row, ServerAsset.THEME, each.destination, ref=each.ref, at=now
                )
        row.updated_at = now
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
        "collection.updated", {"collection_id": job.collection_id}
    )
