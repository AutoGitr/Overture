"""FastAPI dependency helpers."""

lazy from typing import Annotated

lazy from fastapi import Depends
lazy from starlette.requests import HTTPConnection

lazy from . import protocols
lazy from .config import Settings
lazy from .db.session import Database
lazy from .integrations.tmdb import TMDBClient
lazy from .jobs.kinds import JobKind
lazy from .jobs.slot import ManagedBackgroundJob
lazy from .media_servers.registry import NO_MEDIA_SERVER, ProviderRegistry
lazy from .runtime import RuntimeServices
lazy from .services.art.collection_art import CollectionArtService
lazy from .services.art.service import ArtService
lazy from .services.asset_manager.service import AssetManagerService
lazy from .services.assets import AssetsService
lazy from .services.auth import AuthService
lazy from .services.backup.service import BackupService
lazy from .services.collections.arr_requests import CollectionArr
lazy from .services.collections.bulk import CollectionBulk
lazy from .services.collections.discovery import CollectionDiscovery
lazy from .services.collections.editor import CollectionEditor
lazy from .services.collections.groups import CollectionGroups
lazy from .services.collections.reader import CollectionReader
lazy from .services.collections.rule_sync import RuleSync
lazy from .services.collections.set_runner import CollectionSets
lazy from .services.collections.themes import CollectionThemes
lazy from .services.library.service import LibraryService
lazy from .services.public_dataset.service import PublicDatasetService
lazy from .services.realtime import RealtimeSnapshotBuilder
lazy from .services.server_audit.service import ServerAuditService
lazy from .services.stats.service import StatsService
lazy from .services.sync.engine import SyncEngine
lazy from .services.themes.service import ThemesService
lazy from .services.tmdb_items import TmdbItemsService
lazy from .utils.errors import PublicServiceError
lazy from .ws.connection_manager import ConnectionManager


def get_runtime(connection: HTTPConnection) -> RuntimeServices:
    """Return the runtime container attached by the app factory.

    Typed as ``HTTPConnection``, the shared base of ``Request`` and
    ``WebSocket``, so one dependency resolves on both the HTTP routes and the
    ``/ws`` endpoint.
    """
    runtime = getattr(connection.app.state, "runtime", None)
    if not isinstance(runtime, RuntimeServices):
        raise RuntimeError("RuntimeServices is not attached to the FastAPI app state")
    return runtime


RuntimeDep = Annotated[RuntimeServices, Depends(get_runtime)]


def get_settings(runtime: RuntimeDep) -> Settings:
    """Resolve application configuration for HTTP and WebSocket dependencies."""
    return runtime.app_settings


def get_database(runtime: RuntimeDep) -> Database:
    """Resolve this application's database owner."""
    return runtime.database


def get_auth(runtime: RuntimeDep) -> AuthService:
    """Resolve this application's authentication service."""
    return runtime.auth


SettingsDep = Annotated[Settings, Depends(get_settings)]
DatabaseDep = Annotated[Database, Depends(get_database)]
AuthDep = Annotated[AuthService, Depends(get_auth)]


def get_art(runtime: RuntimeDep) -> ArtService:
    """Resolve the artwork domain service."""
    return runtime.art


def get_collection_art(runtime: RuntimeDep) -> CollectionArtService:
    """Resolve the collection artwork service."""
    return runtime.art.collections


def get_library(runtime: RuntimeDep) -> LibraryService:
    """Resolve the library domain service."""
    return runtime.library


def get_sync(runtime: RuntimeDep) -> SyncEngine:
    """Resolve the sync engine service."""
    return runtime.sync


def get_server_audit(runtime: RuntimeDep) -> ServerAuditService:
    """Resolve the server audit domain service."""
    return runtime.server_audit


def get_collection_reader(runtime: RuntimeDep) -> CollectionReader:
    """Resolve the collections' reader component."""
    return runtime.collections.reader


def get_collection_discovery(runtime: RuntimeDep) -> CollectionDiscovery:
    """Resolve the collections' discovery component."""
    return runtime.collections.discovery


def get_collection_editor(runtime: RuntimeDep) -> CollectionEditor:
    """Resolve the collections' editor component."""
    return runtime.collections.editor


def get_collection_rules(runtime: RuntimeDep) -> RuleSync:
    """Resolve the collections' rules component."""
    return runtime.collections.rules


def get_collection_groups(runtime: RuntimeDep) -> CollectionGroups:
    """Resolve the collections' groups component."""
    return runtime.collections.groups


def get_collection_sets(runtime: RuntimeDep) -> CollectionSets:
    """Resolve the collections' sets component."""
    return runtime.collections.sets


def get_collection_bulk(runtime: RuntimeDep) -> CollectionBulk:
    """Resolve the collections' bulk component."""
    return runtime.collections.bulk


def get_collection_themes(runtime: RuntimeDep) -> CollectionThemes:
    """Resolve the collections' themes component."""
    return runtime.collections.themes


def get_collection_arr(runtime: RuntimeDep) -> CollectionArr:
    """Resolve the collections' arr component."""
    return runtime.collections.arr


def get_themes(runtime: RuntimeDep) -> ThemesService:
    """Resolve the themes domain service."""
    return runtime.themes


def get_tmdb_items(runtime: RuntimeDep) -> TmdbItemsService:
    """Resolve the TMDB search and unsaved-item service."""
    return runtime.tmdb_items


def get_backups(runtime: RuntimeDep) -> BackupService:
    """Resolve the backup service."""
    return runtime.backups


def get_public_dataset(runtime: RuntimeDep) -> PublicDatasetService:
    """Resolve the public dataset domain service."""
    return runtime.public_dataset


def get_assets(runtime: RuntimeDep) -> AssetsService:
    """Resolve the bulk schedule domain service."""
    return runtime.assets


def get_asset_manager(runtime: RuntimeDep) -> AssetManagerService:
    """Resolve the asset manager domain service."""
    return runtime.asset_manager


def get_stats(runtime: RuntimeDep) -> StatsService:
    """Resolve the application statistics service."""
    return runtime.stats


def get_provider_registry(runtime: RuntimeDep) -> ProviderRegistry:
    """Resolve the media server provider registry."""
    return runtime.provider_registry


def get_tmdb(runtime: RuntimeDep) -> TMDBClient:
    """Resolve the TMDB client."""
    return runtime.tmdb


def get_events(runtime: RuntimeDep) -> protocols.EventPublisher:
    """Resolve the event publisher."""
    return runtime.events


def get_websockets(runtime: RuntimeDep) -> ConnectionManager:
    """Resolve the WebSocket connection manager."""
    return runtime.websockets


def get_job_slots(runtime: RuntimeDep) -> dict[JobKind, ManagedBackgroundJob]:
    """Resolve every managed job slot, by the kind of job it runs."""
    return runtime.job_slots


def get_realtime_snapshot(runtime: RuntimeDep) -> RealtimeSnapshotBuilder:
    """Resolve a builder of one realtime snapshot."""
    return runtime.realtime_snapshot()


ArtDep = Annotated[ArtService, Depends(get_art)]
CollectionArtDep = Annotated[CollectionArtService, Depends(get_collection_art)]
LibraryDep = Annotated[LibraryService, Depends(get_library)]
SyncDep = Annotated[SyncEngine, Depends(get_sync)]
AuditDep = Annotated[ServerAuditService, Depends(get_server_audit)]
CollectionReaderDep = Annotated[CollectionReader, Depends(get_collection_reader)]
CollectionDiscoveryDep = Annotated[
    CollectionDiscovery, Depends(get_collection_discovery)
]
CollectionEditorDep = Annotated[CollectionEditor, Depends(get_collection_editor)]
CollectionRulesDep = Annotated[RuleSync, Depends(get_collection_rules)]
CollectionGroupsDep = Annotated[CollectionGroups, Depends(get_collection_groups)]
CollectionSetsDep = Annotated[CollectionSets, Depends(get_collection_sets)]
CollectionBulkDep = Annotated[CollectionBulk, Depends(get_collection_bulk)]
CollectionThemesDep = Annotated[CollectionThemes, Depends(get_collection_themes)]
CollectionArrDep = Annotated[CollectionArr, Depends(get_collection_arr)]
ThemesDep = Annotated[ThemesService, Depends(get_themes)]
TmdbItemsDep = Annotated[TmdbItemsService, Depends(get_tmdb_items)]
BackupsDep = Annotated[BackupService, Depends(get_backups)]
PublicDatasetDep = Annotated[PublicDatasetService, Depends(get_public_dataset)]
AssetsDep = Annotated[AssetsService, Depends(get_assets)]
AssetManagerDep = Annotated[AssetManagerService, Depends(get_asset_manager)]
StatsDep = Annotated[StatsService, Depends(get_stats)]
ProviderRegistryDep = Annotated[ProviderRegistry, Depends(get_provider_registry)]
TmdbDep = Annotated[TMDBClient, Depends(get_tmdb)]
EventsDep = Annotated[protocols.EventPublisher, Depends(get_events)]
WebSocketsDep = Annotated[ConnectionManager, Depends(get_websockets)]
JobSlotsDep = Annotated[dict[JobKind, ManagedBackgroundJob], Depends(get_job_slots)]
RealtimeSnapshotDep = Annotated[RealtimeSnapshotBuilder, Depends(get_realtime_snapshot)]


def require_media_server(runtime: RuntimeDep) -> None:
    """Refuse server-bound routes while MEDIA_SERVER=none.

    Raises:
        PublicServiceError: 409 when no media server is configured.
    """
    if not runtime.provider_registry.configured:
        raise PublicServiceError(409, NO_MEDIA_SERVER)
