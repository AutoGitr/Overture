"""Store collection themes through the provider's declared capability."""

lazy from collections.abc import Sequence
lazy from pathlib import Path

lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ... import protocols
lazy from ...db.models.download_job import DownloadJob
lazy from ...db.models.media_collection import CollectionLibrary, MediaCollection
lazy from ...db.session import Database
lazy from ...db.theme_file import ThemeFileFacts, record_theme_file
lazy from ...domain import AssetStatus, JobStatus, ThemeBulkSource
lazy from ...media_servers.adapters import (
    FolderThemes,
    NoCollectionThemes,
    UploadThemes,
)
lazy from ...media_servers.registry import CollectionProvider, ProviderRegistry
lazy from ...repositories.catalog import CatalogRepository
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.downloads import DownloadJobRepository
lazy from ...utils.assets import THEME_FILENAME
lazy from ...utils.threads import owned_thread
lazy from ...utils.time import utc_now
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


def _theme_copies(
    row: MediaCollection, provider_registry: ProviderRegistry
) -> list[tuple[CollectionProvider, CollectionLibrary]]:
    """The copies a collection's theme goes to, on servers that store themes.

    Plex keeps a theme with each copy; Jellyfin reads one from its BoxSet's
    folder, which every library's part on that server names.
    """
    copies: list[tuple[CollectionProvider, CollectionLibrary]] = []
    folders: set[int] = set()
    for part in row.copies:
        if not provider_registry.configured_server_id(part.server_id):
            continue
        provider = provider_registry.get(part.server_id)
        if _storage_unavailable(provider) is not None or provider.collections is None:
            continue
        if isinstance(provider.collections, FolderThemes):
            if part.server_id in folders:
                continue
            folders.add(part.server_id)
        copies.append((provider, part))
    return copies


async def theme_folders(
    row: MediaCollection, provider_registry: ProviderRegistry
) -> list[tuple[CollectionProvider, CollectionLibrary, Path]]:
    """Resolve the trusted folder each Jellyfin server keeps the collection in.

    Raises:
        DownloadError: When a server's folder cannot be used.
    """
    folders: list[tuple[CollectionProvider, CollectionLibrary, Path]] = []
    for provider, part in _theme_copies(row, provider_registry):
        if not isinstance(provider.collections, FolderThemes):
            continue
        try:
            folder = await owned_thread(
                collection_folder, provider.server, part.server_path
            )
        except ValueError as exc:
            raise DownloadError(str(exc)) from exc
        folders.append((provider, part, folder))
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
    for _, _, folder in folders:
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
    if not _theme_copies(row, provider_registry):
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
    # The lead Plex copy's ID stands for them all: each holds the same theme.
    uploaded = [
        await provider.upload_collection_theme(
            part.server_item_id or "", downloaded.audio_bytes
        )
        for provider, part in _theme_copies(row, provider_registry)
        if isinstance(provider.collections, UploadThemes)
    ]
    facts = None
    for provider, part, folder in await theme_folders(row, provider_registry):
        stored = await asset_storage.write_file_async(
            str(folder / THEME_FILENAME), downloaded.audio_bytes, str(folder)
        )
        facts = facts or ThemeFileFacts(
            stored.file_hash, stored.mtime_ns, stored.size, downloaded.duration
        )
        await provider.refresh_item(part.server_item_id or "", unlock=())
    await record_collection_theme(
        job,
        title=downloaded.title,
        duration=downloaded.duration,
        server_theme_id=next(iter(uploaded), None),
        facts=facts,
        publisher=publisher,
        database=database,
    )


async def collection_theme_source(
    session: AsyncSession, row: MediaCollection, youtube_id: str | None
) -> ThemeBulkSource:
    """Return where a collection's theme video comes from: a catalog, else a search."""
    catalog = await CatalogRepository(session).collections_by_tmdb_id(
        {row.tmdb_collection_id} if row.tmdb_collection_id else set()
    )
    entry = catalog.get(row.tmdb_collection_id or 0)
    if entry and youtube_id == entry.youtube_id_themerrdb:
        return ThemeBulkSource.THEMERRDB
    if entry and youtube_id == entry.youtube_id_overturedb:
        return ThemeBulkSource.OVERTUREDB
    return ThemeBulkSource.YOUTUBE_SEARCH


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
        row.sqlmodel_update(
            {
                "youtube_id": job.target_url,
                "youtube_id_source": await collection_theme_source(
                    session, row, job.target_url
                ),
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
            "has_theme": True,
            "youtube_id": job.target_url,
            "youtube_title": title,
            "youtube_duration": duration,
            # Downloaded onto the server, the theme is complete.
            "theme_status": AssetStatus.COMPLETE,
        },
    )
