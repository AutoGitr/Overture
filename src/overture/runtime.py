"""Application runtime service container."""

lazy import asyncio
lazy import faulthandler
lazy import inspect
lazy import logging
lazy import os
lazy import sys
lazy from collections.abc import Awaitable, Callable
lazy from dataclasses import dataclass, field
lazy from pathlib import Path

lazy from pydantic import SecretStr
lazy from sqlmodel import text

lazy from . import protocols
lazy from .config import Settings, load_configuration
lazy from .db.session import Database
lazy from .integrations.mdblist import MDBListClient
lazy from .integrations.proxy import ProxyClientManager
lazy from .integrations.tmdb import TMDBClient
lazy from .jobs.kinds import JobKind
lazy from .jobs.slot import ManagedBackgroundJob
lazy from .media_servers.health import MediaServerHealth
lazy from .media_servers.registry import ProviderRegistry
lazy from .runtime_paths import database_path, database_url, image_cache_path
lazy from .schemas.media_server import media_server_status
lazy from .schemas.settings import ConnectivityStatusResponse
lazy from .services.art.candidates import ArtCandidates
lazy from .services.art.matcher import ArtMatcher
lazy from .services.art.phash import PhashService
lazy from .services.art.service import ArtService
lazy from .services.asset_manager.service import AssetManagerService
lazy from .services.assets import AssetsService
lazy from .services.auth import AuthService
lazy from .services.backup.events import BackupEvents
lazy from .services.backup.files import BackupStore
lazy from .services.backup.service import BackupService
lazy from .services.collections.service import CollectionsService
lazy from .services.downloads import DownloadService
lazy from .services.downloads.art import DownloadArtHandler
lazy from .services.downloads.events import DownloadEventPublisher
lazy from .services.downloads.theme import DownloadThemeHandler
lazy from .services.health import get_service_status
lazy from .services.job_results import interrupt_unfinished, latest_runs
lazy from .services.library.service import LibraryService
lazy from .services.local_assets.service import LocalAssets
lazy from .services.public_dataset.service import PublicDatasetService
lazy from .services.scheduler import SchedulerService
lazy from .services.server_audit.service import ServerAuditService
lazy from .services.stats.service import StatsService
lazy from .services.storage.assets import AssetStorage
lazy from .services.storage.image_cache import ImageCache
lazy from .services.sync.engine import SyncEngine
lazy from .services.themes.service import ThemesService
lazy from .services.themes.youtube_resolver import (
    YouTubeResolver,
    theme_runtime_available,
)
lazy from .services.tmdb_items import TmdbItemsService
lazy from .utils.security import Redactor, is_sensitive_field
lazy from .utils.temporary import clean_abandoned_operations
lazy from .utils.threads import owned_thread
lazy from .ws.connection_manager import ConnectionManager
lazy from .ws.emitter import WebSocketEventEmitter
lazy from .ws.state import BackgroundJobRegistry

logger = logging.getLogger(__name__)

type LifecycleOperation = Callable[[], Awaitable[None] | None]


@dataclass(slots=True, frozen=True)
class LifecycleService:
    """One runtime service and the operations that own its lifetime."""

    name: str
    start: LifecycleOperation
    stop: LifecycleOperation


@dataclass(slots=True)
class RuntimeServices:
    """Own long-lived services and their startup/shutdown order.

    This holds *what services exist*; :func:`build_runtime` holds *how the
    production ones are wired*. Tests construct this directly with fakes
    instead of threading overrides through a constructor.
    """

    app_settings: Settings
    database: Database
    auth: AuthService
    redactor: Redactor
    scheduler: SchedulerService
    websockets: ConnectionManager
    events: protocols.EventPublisher
    background_jobs: BackgroundJobRegistry
    phash: PhashService
    asset_storage: AssetStorage
    tmdb: TMDBClient
    youtube: YouTubeResolver
    provider_registry: ProviderRegistry
    art_matcher: ArtMatcher
    proxy_clients: ProxyClientManager
    downloads: DownloadService
    sync: SyncEngine
    backups: BackupService
    assets: AssetsService
    public_dataset: PublicDatasetService
    art: ArtService
    library: LibraryService
    server_audit: ServerAuditService
    collections: CollectionsService
    themes: ThemesService
    tmdb_items: TmdbItemsService
    asset_manager: AssetManagerService
    stats: StatsService
    config_dir: Path
    connectivity_probe: Callable[
        [ProviderRegistry, TMDBClient], Awaitable[ConnectivityStatusResponse]
    ] = get_service_status

    _ping_task: asyncio.Task[None] | None = field(default=None, init=False)
    _connectivity_task: asyncio.Task[None] | None = field(default=None, init=False)
    _started: set[str] = field(default_factory=set[str], init=False)
    _shutdown_task: asyncio.Task[None] | None = field(default=None, init=False)
    _shutdown_errors: list[str] = field(default_factory=list[str], init=False)
    _announcements: set[asyncio.Task[None]] = field(
        default_factory=set[asyncio.Task[None]], init=False
    )

    @property
    def job_slots(self) -> dict[JobKind, ManagedBackgroundJob]:
        """Return every job slot, by the kind of job it runs."""
        slots = [
            self.sync.job,
            *self.background_jobs.values(),
            self.public_dataset.job,
            self.backups.events.job,
        ]
        return {slot.lifecycle.kind: slot for slot in slots}

    def _lifecycle(self) -> tuple[LifecycleService, ...]:
        """Return services in dependency-safe startup order."""
        return (
            LifecycleService("downloads", self.downloads.start, self.downloads.stop),
            LifecycleService("sync", self.sync.start, self.sync.stop),
            LifecycleService("backups", self.backups.start, self.backups.stop),
            LifecycleService(
                "asset schedules",
                self.assets.start,
                self.assets.stop,
            ),
            LifecycleService(
                "public dataset",
                self.public_dataset.start,
                self.public_dataset.stop,
            ),
            LifecycleService(
                "collection rules", self.collections.start, self.collections.stop
            ),
            LifecycleService("scheduler", self.scheduler.start, self.scheduler.stop),
        )

    async def start(self, *, app_version: str) -> None:
        """Start runtime services in dependency order."""
        config = self.app_settings
        logger.info(
            "Overture %s starting (Python %s, UID %d, GID %d, timezone %s)",
            app_version,
            sys.version.split()[0],
            getattr(os, "getuid", lambda: -1)(),
            getattr(os, "getgid", lambda: -1)(),
            config.TZ,
        )
        if config.MEDIA_SERVER is None:
            logger.info("Media server: none; running on OvertureDB and TMDB")
        else:
            logger.info(
                "Media server: %s at %s",
                config.MEDIA_SERVER.display_name,
                config.MEDIA_SERVER_URL,
            )
        logger.info(
            "App URL: %s",
            config.APP_URL or "not set; using the request host and HTTP cookies",
        )
        if config.AUTH_MODE == "none":
            logger.warning(
                "Running with AUTH_MODE=none disables all authentication and leaves "
                "your instance open to anyone who can reach its port. Never expose an "
                "unprotected instance to the internet."
            )
        self._ensure_config_dir()

        await owned_thread(clean_abandoned_operations, self.config_dir)
        faulthandler.enable()
        await self.database.initialize(self.backups.backup_before_upgrade)
        await interrupt_unfinished(self.database)
        runs = await latest_runs(self.database)
        for kind, job in self.job_slots.items():
            if latest := runs.get(kind):
                job.save_snapshot(latest.event, latest.summary)

        for service in self._lifecycle():
            self._started.add(service.name)
            result = service.start()
            if inspect.isawaitable(result):
                await result
        self.provider_registry.health.listen(self._announce_media_server)
        self._ping_task = asyncio.create_task(self.websockets.start_ping_loop())
        self._connectivity_task = asyncio.create_task(self._log_connectivity())
        self._ping_task.add_done_callback(self._observe_task)
        self._connectivity_task.add_done_callback(self._observe_task)

        logger.info("Overture ready on port %d", config.OVERTURE_PORT)

    async def stop(self) -> None:
        """Allow thirty seconds for owned teardown, reporting unfinished work."""
        if self._shutdown_task is None:
            self._shutdown_task = asyncio.create_task(self._stop())
            self._shutdown_task.add_done_callback(self._observe_task)
        completed, _ = await asyncio.wait({self._shutdown_task}, timeout=30)
        if not completed:
            logger.error(
                "Shutdown exceeded 30 seconds; still stopping: %s",
                ", ".join(sorted(self._started)),
            )
            raise TimeoutError("Application teardown incomplete")
        self._shutdown_task.result()

    def _announce_media_server(self, health: MediaServerHealth) -> None:
        """Tell clients the media server went down or came back."""
        task = asyncio.create_task(
            self.events.broadcast(
                "media-server.status",
                media_server_status(health).model_dump(mode="json"),
            )
        )
        self._announcements.add(task)
        task.add_done_callback(self._announcements.discard)
        task.add_done_callback(self._observe_task)

    @staticmethod
    def _observe_task(task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (failure := task.exception()) is not None:
            logger.error("Runtime task failed: %s", task.get_name(), exc_info=failure)

    async def _stop(self) -> None:
        """Stop runtime services in reverse dependency order."""
        logger.info("Overture shutting down")
        await self._cancel_background_task("websocket ping", self._ping_task)
        self._ping_task = None
        await self._cancel_background_task(
            "connectivity check", self._connectivity_task
        )
        self._connectivity_task = None
        await self._shutdown_step("scheduler", self.scheduler.stop)
        self._started.discard("scheduler")
        await self._shutdown_step("background jobs", self.background_jobs.stop)
        for service in reversed(self._lifecycle()):
            if service.name in self._started:
                await self._shutdown_step(service.name, service.stop)
                self._started.discard(service.name)
        await self._shutdown_step("websockets", self.websockets.close)
        await self._shutdown_step("authentication", self.auth.close)
        await self._shutdown_step("art matcher", self.art_matcher.close)
        await self._shutdown_step("provider registry", self.provider_registry.close)
        await self._shutdown_step("proxy clients", self.proxy_clients.close)
        await self._shutdown_step("tmdb client", self.tmdb.close)
        await self._shutdown_step("phash service", self.phash.close)
        await self._shutdown_step("database engine", self.database.close)
        self._started.clear()
        if self._shutdown_errors:
            logger.error(
                "Overture stopped, but these failed to stop: %s",
                ", ".join(self._shutdown_errors),
            )
            raise RuntimeError("Application teardown failed")
        logger.info("Overture stopped")

    async def _cancel_background_task(
        self,
        name: str,
        task: asyncio.Task[None] | None,
    ) -> None:
        """Cancel one runtime-owned task and log unexpected shutdown failures."""
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            return
        except Exception as exc:
            self._shutdown_errors.append(name)
            logger.warning("The %s task failed during shutdown: %s", name, exc)

    async def _shutdown_step(
        self,
        name: str,
        operation: Callable[[], Awaitable[None] | None],
    ) -> None:
        """Run one shutdown operation while preserving visibility into failures."""
        try:
            result = operation()
            if inspect.isawaitable(result):
                await result
        except Exception:
            self._shutdown_errors.append(name)
            logger.exception("Stopping the %s failed", name)

    async def readiness_checks(self) -> dict[str, bool]:
        """Return dependency readiness checks for authenticated traffic."""
        checks = {
            "config": True,
            "database": False,
            "theme_runtime": theme_runtime_available(),
            "downloads": self.downloads.healthy,
            "phash": self.phash.healthy,
            "asset_schedules": self.assets.healthy,
            "sync_schedules": self.sync.schedules.healthy,
            "scheduler": self.scheduler.running,
            "websocket_ping": self._ping_task is not None
            and not self._ping_task.done(),
        }

        try:
            async with asyncio.timeout(2):
                async with self.database.engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            checks["database"] = True
        except Exception as exc:
            logger.warning("Readiness check could not reach the database: %s", exc)
        return checks

    def _ensure_config_dir(self) -> None:
        """Create and validate the persistent config directory."""
        try:
            self.config_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise RuntimeError(
                f"Could not create persistent config directory {self.config_dir}"
            ) from exc
        if not self.config_dir.is_dir() or not os.access(self.config_dir, os.W_OK):
            current_uid = os.getuid() if hasattr(os, "getuid") else "unknown"
            raise RuntimeError(
                f"Persistent config directory {self.config_dir} is not writable "
                f"by the current user (uid={current_uid})"
            )

    async def _log_connectivity(self) -> None:
        """Report once, after startup, which external services answer."""
        config = self.app_settings
        try:
            status = await self.connectivity_probe(self.provider_registry, self.tmdb)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Connectivity check failed: %s", exc)
            return
        # Without a media server, its health stays unknown and no notice shows.
        services = (
            {
                config.MEDIA_SERVER.display_name: (
                    status.media_server,
                    "MEDIA_SERVER_URL and MEDIA_SERVER_API_KEY",
                ),
            }
            if config.MEDIA_SERVER is not None
            else {}
        )
        if config.tmdb_configured:
            services["TMDB"] = (status.tmdb, "TMDB_API_KEY")
        for name, (reachable, settings) in services.items():
            if reachable:
                logger.info("Connected to %s", name)
            else:
                logger.warning("%s is not reachable; check %s", name, settings)


def build_runtime(
    *,
    app_settings: Settings | None = None,
    database: Database | None = None,
    config_dir: Path | None = None,
) -> RuntimeServices:
    """Construct the production runtime with its real service wiring."""
    app_config = (
        app_settings if app_settings is not None else load_configuration(Settings)
    )
    config_dir = (
        config_dir if config_dir is not None else app_config.OVERTURE_CONFIG_DIR
    )
    database = database if database is not None else Database(database_url(config_dir))
    redactor = Redactor(
        value.get_secret_value() if isinstance(value, SecretStr) else value
        for name, value in app_config.model_dump().items()
        if is_sensitive_field(name) and isinstance(value, str | SecretStr)
    )
    websockets = ConnectionManager()
    events: protocols.EventPublisher = WebSocketEventEmitter(websockets)
    phash = PhashService(app_config=app_config)
    asset_storage = AssetStorage(app_config=app_config)
    image_cache = ImageCache(image_cache_path(config_dir))
    local_assets = LocalAssets(
        asset_storage=asset_storage,
        phash=phash,
        image_cache=image_cache,
        database=database,
        publisher=events,
    )
    tmdb = TMDBClient(app_config=app_config)
    youtube = YouTubeResolver(
        config_dir, download_workers=app_config.THEME_DOWNLOAD_WORKERS
    )
    proxy_clients = ProxyClientManager(app_config=app_config)
    provider_registry = ProviderRegistry(app_config=app_config)
    candidates = ArtCandidates(
        database=database,
        provider_registry=provider_registry,
        tmdb_client=tmdb,
        app_config=app_config,
    )
    art_matcher = ArtMatcher(
        app_config=app_config,
        database=database,
        phash=phash,
        local_assets=local_assets,
        provider_registry=provider_registry,
        candidates=candidates,
        image_clients=proxy_clients,
        # Twice the hash workers keeps the process pool fed while one batch is
        # still downloading, without flooding the image hosts.
        compare_concurrency=max(2, app_config.PHASH_WORKERS * 2),
    )
    background_jobs = BackgroundJobRegistry(events, database=database)
    downloads = DownloadService(
        art_handler=DownloadArtHandler(
            provider_registry=provider_registry,
            asset_storage=asset_storage,
            image_cache=image_cache,
            phash=phash,
            image_clients=proxy_clients,
            app_config=app_config,
            database=database,
        ),
        theme_handler=DownloadThemeHandler(
            asset_storage=asset_storage,
            youtube_resolver=youtube,
            database=database,
        ),
        provider_registry=provider_registry,
        events=DownloadEventPublisher(events),
        publisher=events,
        asset_storage=asset_storage,
        app_config=app_config,
        database=database,
        library_gate=background_jobs.library_gate,
    )
    scheduler = SchedulerService(app_config=app_config)
    backup_events = BackupEvents(events)
    backup_store = BackupStore(
        database_path(config_dir),
        config_dir / "backups",
        timezone=app_config.tzinfo,
    )
    backups = BackupService(
        scheduler=scheduler,
        events=backup_events,
        store=backup_store,
        image_cache=image_cache,
        app_config=app_config,
        database=database,
    )
    sync = SyncEngine(
        tmdb_client=tmdb,
        library_gate=background_jobs.library_gate,
        app_config=app_config,
        database=database,
        downloads=downloads,
        provider_registry=provider_registry,
        scheduler=scheduler,
        publisher=events,
        local_assets=local_assets,
        config_dir=config_dir,
    )
    art = ArtService(
        app_config=app_config,
        database=database,
        asset_storage=asset_storage,
        matcher=art_matcher,
        downloads=downloads,
        publisher=events,
        provider_registry=provider_registry,
        candidates=candidates,
        image_clients=proxy_clients,
        image_cache=image_cache,
    )
    library = LibraryService(
        database=database,
        downloads=downloads,
        publisher=events,
        asset_storage=asset_storage,
        image_cache=image_cache,
        provider_registry=provider_registry,
        proxy_clients=proxy_clients,
    )
    server_audit = ServerAuditService(
        background_jobs=background_jobs,
        provider_registry=provider_registry,
        local_assets=local_assets,
        phash=phash,
        image_clients=proxy_clients,
        publisher=events,
        app_config=app_config,
        database=database,
        config_dir=config_dir,
    )
    collections = CollectionsService(
        tmdb=tmdb,
        mdblist=MDBListClient(app_config=app_config),
        art=art,
        scheduler=scheduler,
        database=database,
        provider_registry=provider_registry,
        publisher=events,
        downloads=downloads,
        proxy_clients=proxy_clients,
        app_config=app_config,
        library_gate=background_jobs.library_gate,
    )
    themes = ThemesService(
        database=database,
        asset_storage=asset_storage,
        downloads=downloads,
        publisher=events,
        youtube_resolver=youtube,
    )
    asset_manager = AssetManagerService(
        background_jobs=background_jobs,
        publisher=events,
        app_config=app_config,
        local_assets=local_assets,
        provider_registry=provider_registry,
        database=database,
        config_dir=config_dir,
    )
    stats = StatsService(
        database=database,
        backups=backups,
        collections=collections,
    )
    public_dataset = PublicDatasetService(
        scheduler=scheduler,
        publisher=events,
        app_config=app_config,
        database=database,
        config_dir=config_dir,
    )

    return RuntimeServices(
        app_settings=app_config,
        database=database,
        auth=AuthService(app_config, database),
        redactor=redactor,
        config_dir=config_dir,
        scheduler=scheduler,
        websockets=websockets,
        events=events,
        background_jobs=background_jobs,
        phash=phash,
        asset_storage=asset_storage,
        tmdb=tmdb,
        youtube=youtube,
        provider_registry=provider_registry,
        art_matcher=art_matcher,
        proxy_clients=proxy_clients,
        downloads=downloads,
        sync=sync,
        backups=backups,
        assets=AssetsService(
            background_jobs=background_jobs,
            downloads=downloads,
            art_matcher=art_matcher,
            art=art,
            youtube_resolver=youtube,
            scheduler=scheduler,
            publisher=events,
            app_config=app_config,
            local_assets=local_assets,
            database=database,
        ),
        public_dataset=public_dataset,
        art=art,
        library=library,
        server_audit=server_audit,
        collections=collections,
        themes=themes,
        tmdb_items=TmdbItemsService(
            app_config=app_config,
            database=database,
            tmdb_client=tmdb,
            art=art,
            themes=themes,
            downloads=downloads,
            publisher=events,
            catalog=public_dataset.catalog,
        ),
        asset_manager=asset_manager,
        stats=stats,
    )
