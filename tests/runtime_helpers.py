"""Helpers for direct route tests that need a runtime dependency."""

lazy import asyncio
lazy from collections.abc import (
    AsyncGenerator,
    Awaitable,
    Callable,
    Generator,
    Sequence,
)
lazy from contextlib import asynccontextmanager, contextmanager
lazy from pathlib import Path
lazy from typing import Any, Protocol, cast, override

lazy import httpx2
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture import protocols
lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    CatalogMediaType,
    MediaType,
    TmdbLanguageFilter,
)
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.jobs.gate import LibraryGate
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import JobContext
lazy from overture.jobs.slot import ManagedBackgroundJob
lazy from overture.media_servers.registry import ProviderRegistry
lazy from overture.runtime import RuntimeServices
lazy from overture.runtime_paths import database_path
lazy from overture.schemas.art import ArtCandidate
lazy from overture.schemas.common import Status, StatusResponse
lazy from overture.schemas.downloads import DownloadJobEvent
lazy from overture.schemas.public_dataset import (
    PublicDatasetRecord,
    PublicDatasetSources,
    PublicDatasetStatus,
)
lazy from overture.schemas.schedules import ScheduleWrite
lazy from overture.schemas.settings import ConnectivityStatusResponse
lazy from overture.schemas.themes import ThemeSearchResult
lazy from overture.services.art.candidates import ArtCandidates
lazy from overture.services.art.matcher import ArtMatcher
lazy from overture.services.art.phash import PhashService
lazy from overture.services.art.service import ArtService
lazy from overture.services.asset_manager.service import AssetManagerService
lazy from overture.services.assets import AssetsService
lazy from overture.services.auth import AuthService
lazy from overture.services.backup.events import BackupEvents
lazy from overture.services.backup.files import BackupStore
lazy from overture.services.backup.service import BackupService
lazy from overture.services.collections.service import CollectionsService
lazy from overture.services.downloads.art import DownloadArtHandler
lazy from overture.services.downloads.events import DownloadEventPublisher
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.downloads.theme import DownloadThemeHandler
lazy from overture.services.downloads.watch import DownloadWatch
lazy from overture.services.health import get_service_status
lazy from overture.services.library.service import LibraryService
lazy from overture.services.local_assets.service import LocalAssets
lazy from overture.services.named_schedules import NamedSchedules
lazy from overture.services.public_dataset.service import PublicDatasetService
lazy from overture.services.scheduler import SchedulerService
lazy from overture.services.server_audit.service import ServerAuditService
lazy from overture.services.stats.service import StatsService
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.sync.engine import SyncEngine
lazy from overture.services.themes.service import ThemesService
lazy from overture.services.themes.youtube_resolver import ThemeAudio, YouTubeResolver
lazy from overture.services.tmdb_items import TmdbItemsService
lazy from overture.utils.security import Redactor, is_sensitive_field
lazy from overture.ws.connection_manager import ConnectionManager
lazy from overture.ws.state import BackgroundJobRegistry
lazy from tests.publishers import NullEventPublisher


class _PersistedRow(Protocol):
    """A model row whose primary key is optional until it is flushed."""

    id: int | None


def row_id(row: _PersistedRow) -> int:
    """Return a row's primary key, failing the test when it has none.

    Model ids are ``int | None`` because a row exists before the database
    assigns one. A test that built or flushed the row knows better, and the
    service it calls wants an ``int``.
    """
    assert row.id is not None
    return row.id


class SessionDatabase(Database):
    """Inject a controlled session factory while retaining transaction semantics."""

    def __init__(self, factory: Any) -> None:
        self._factory = factory
        self.write_lock = asyncio.Lock()
        self._engine = None
        self._write_engine = None

    @asynccontextmanager
    async def read_session(self) -> AsyncGenerator[AsyncSession]:
        async with self._factory() as session:
            yield session

    @asynccontextmanager
    async def write_session(self) -> AsyncGenerator[AsyncSession]:
        async with self.write_lock, self._factory() as session:
            try:
                yield session
            except BaseException:
                if session.in_transaction():
                    await session.rollback()
                raise
            else:
                await session.commit()


def database_for(factory: Any) -> Database:
    """Build an isolated session source for a service test."""
    return SessionDatabase(factory)


def one_session(session: AsyncSession) -> Any:
    """Return a factory that hands every caller the same open session."""

    @asynccontextmanager
    async def factory() -> AsyncGenerator[AsyncSession]:
        yield session

    return factory


class _UnusedDependency:
    """Fails loudly if a test touches a dependency it declared unused."""

    def __init__(self, label: str) -> None:
        self._label = label

    def __getattr__(self, attr: str) -> Any:
        raise AssertionError(
            f"{self._label} was declared unused by this test but {attr!r} was called"
        )


def unused[T](protocol: type[T], label: str | None = None) -> T:
    """Return a stand-in for a dependency the code path under test never uses.

    Typed as the protocol the parameter expects, so the injection seam stays
    type-checked instead of being widened to ``None`` or ``object()``. Any
    actual use raises immediately rather than failing further down.
    """
    name = label or getattr(protocol, "__name__", "dependency")
    return cast("T", _UnusedDependency(name))


class NoopProviderRegistry(ProviderRegistry):
    """A registry serving one caller-supplied provider, or none at all.

    *collections* says whether the provider stands for a server that has
    collections (Plex), as :attr:`ProviderRegistry.collections` decides.
    """

    def __init__(
        self, provider: Any | None = None, *, collections: bool = True
    ) -> None:
        self._provider = provider
        self._collections = collections

    @property
    @override
    def provider(self) -> Any:
        if self._provider is None:
            raise AssertionError("This test configured no media server provider")
        return self._provider

    @property
    @override
    def collections(self) -> Any:
        return self._provider if self._collections else None

    @override
    async def fetch_server_active_art_url(
        self, server_id: str, art_type: ArtType
    ) -> str | None:
        return None


class StaticImageClients(ProxyClientManager):
    """Return one caller-supplied client while recording requested URLs."""

    def __init__(self, client: Any | None = None) -> None:
        self.client = client if client is not None else object()
        self.requested_urls: list[str | None] = []

    @override
    async def get_client(self, url: str | None = None) -> httpx2.AsyncClient:
        self.requested_urls.append(url)
        return cast("httpx2.AsyncClient", self.client)

    @property
    def pooled_clients(self) -> int:
        return 1

    @override
    async def close(self) -> None:
        pass


class NoopDownloads(DownloadService):
    @property
    @override
    def healthy(self) -> bool:
        return True

    def __init__(self) -> None:
        pass

    @property
    def worker_count(self) -> int:
        return 1

    @override
    async def start(self) -> None:
        return None

    @override
    async def stop(self) -> None:
        return None

    @override
    async def snapshot_events(self) -> list[DownloadJobEvent]:
        return []

    @override
    async def queue_job(self, *_args: object, **_kwargs: object) -> tuple[str, bool]:
        return "noop-job", True

    @contextmanager
    def watch(self) -> Generator[DownloadWatch]:
        yield DownloadWatch()


class NoopSchedules(NamedSchedules[Any, Any]):
    """Saved schedules that register nothing and run nothing."""

    def __init__(self, *, app_config: Settings) -> None:
        self.scheduler = SchedulerService(app_config=app_config)

    @property
    @override
    def healthy(self) -> bool:
        return True

    @override
    async def start(self) -> None:
        return None

    @override
    async def stop(self) -> None:
        return None


class NoopSync(SyncEngine):
    _running = False

    @property
    def running(self) -> bool:
        return self._running

    def __init__(self, *, app_config: Settings) -> None:
        self.job = ManagedBackgroundJob(
            ManagedJobLifecycle(JobKind.SYNC), NullEventPublisher()
        )
        self.schedules = NoopSchedules(app_config=app_config)

    @override
    async def start(self) -> None:
        return None

    @override
    async def stop(self) -> None:
        self._running = False

    def request_stop(self) -> bool:
        running = self.running
        self._running = False
        return running

    @override
    def start_background_sync(self, *, library_ids: list[str] | None = None) -> bool:
        if self.running:
            return False
        self._running = True
        return True


class NoopBackgroundJobs(BackgroundJobRegistry):
    def __init__(self) -> None:
        super().__init__(NullEventPublisher())

    @override
    def values(self) -> tuple[ManagedBackgroundJob, ...]:
        return ()

    @override
    async def stop(self) -> None:
        return None


class NoopAssets(AssetsService):
    """Assets runs whose saved schedules register nothing."""

    def __init__(self, *, app_config: Settings) -> None:
        self.schedules = NoopSchedules(app_config=app_config)


class NoopPublicDataset(PublicDatasetService):
    def __init__(self, *, app_config: Settings) -> None:
        self.job = ManagedBackgroundJob(
            ManagedJobLifecycle(JobKind.PUBLIC_DATASET_SYNC), NullEventPublisher()
        )
        self.scheduler = SchedulerService(app_config=app_config)
        self._running = False

    @override
    async def start(self) -> None:
        return None

    @override
    async def stop(self) -> None:
        return None

    @override
    async def get_status(self) -> PublicDatasetStatus:
        return self._noop_status(enabled=False)

    @override
    async def set_enabled(self, enabled: bool) -> PublicDatasetStatus:
        return self._noop_status(enabled=enabled)

    @staticmethod
    def _noop_status(*, enabled: bool) -> PublicDatasetStatus:
        return PublicDatasetStatus(
            enabled=enabled,
            repo_url="https://example.invalid/repo",
            catalog_url="https://example.invalid/catalog",
            timezone="UTC",
        )

    @override
    async def get_sources_for_item(self, item_id: int) -> PublicDatasetSources:
        raise NotImplementedError("Provide a dataset service for item lookup tests")

    @override
    async def get_record_for_item(self, item_id: int) -> PublicDatasetRecord:
        raise NotImplementedError("Provide a dataset service for item lookup tests")

    @override
    def start_background_sync(self) -> bool:
        if self._running:
            return False
        self._running = True
        return True


class NoopTmdb(TMDBClient):
    def __init__(self) -> None:
        pass

    @override
    async def test_connection(self) -> bool:
        return False

    @override
    async def art_candidates(
        self,
        media_type: MediaType | CatalogMediaType,
        tmdb_id: int,
        art_type: ArtType,
        *,
        season_num: int | None = None,
        language_filter: TmdbLanguageFilter = TmdbLanguageFilter.EN_NULL,
    ) -> list[ArtCandidate]:
        return []

    @override
    async def close(self) -> None:
        return None


class NoopYoutube(YouTubeResolver):
    def __init__(self) -> None:
        pass

    @override
    async def search(
        self,
        query: str = "",
        limit: int = 10,
        video_ids: Sequence[str] | None = None,
        *,
        wait: bool = True,
    ) -> list[ThemeSearchResult]:
        return []

    @override
    async def download_audio(
        self,
        youtube_id: str,
        min_duration: int = 30,
        max_duration: int = 300,
        progress_callback: Any = None,
        *,
        normalize_loudness: bool = False,
    ) -> ThemeAudio:
        raise NotImplementedError


def make_runtime(
    *,
    app_config: Settings,
    database: Database,
    scheduler: SchedulerService | None = None,
    config_dir: Path,
    connectivity_probe: Callable[
        [ProviderRegistry, TMDBClient], Awaitable[ConnectivityStatusResponse]
    ]
    | None = None,
    websockets: ConnectionManager | None = None,
    events: protocols.EventPublisher | None = None,
    background_jobs: BackgroundJobRegistry | None = None,
    provider_registry: ProviderRegistry | None = None,
    downloads: DownloadService | None = None,
    sync: SyncEngine | None = None,
    backups: BackupService | None = None,
    assets: AssetsService | None = None,
    public_dataset: PublicDatasetService | None = None,
    phash: PhashService | None = None,
    asset_storage: AssetStorage | None = None,
    art_matcher: ArtMatcher | None = None,
    proxy_clients: ProxyClientManager | None = None,
    tmdb: TMDBClient | None = None,
    youtube: YouTubeResolver | None = None,
    art: ArtService | None = None,
    library: LibraryService | None = None,
    server_audit: ServerAuditService | None = None,
    collections: CollectionsService | None = None,
    themes: ThemesService | None = None,
    asset_manager: AssetManagerService | None = None,
    stats: StatsService | None = None,
) -> RuntimeServices:
    """Select typed collaborators before constructing the services that bind them."""
    scheduler = (
        SchedulerService(app_config=app_config) if scheduler is None else scheduler
    )
    connectivity_probe = (
        get_service_status if connectivity_probe is None else connectivity_probe
    )
    websockets = unused(ConnectionManager) if websockets is None else websockets
    events = NullEventPublisher() if events is None else events
    background_jobs = (
        BackgroundJobRegistry(events) if background_jobs is None else background_jobs
    )
    provider_registry = (
        ProviderRegistry(app_config=app_config)
        if provider_registry is None
        else provider_registry
    )
    downloads = NoopDownloads() if downloads is None else downloads
    sync = NoopSync(app_config=app_config) if sync is None else sync
    backups = (
        BackupService(
            scheduler=scheduler,
            events=BackupEvents(events),
            store=BackupStore(
                database_path(config_dir),
                config_dir / "backups",
                timezone=app_config.tzinfo,
            ),
            app_config=app_config,
            database=database,
        )
        if backups is None
        else backups
    )
    assets = unused(AssetsService) if assets is None else assets
    public_dataset = (
        NoopPublicDataset(app_config=app_config)
        if public_dataset is None
        else public_dataset
    )
    phash = unused(PhashService) if phash is None else phash
    asset_storage = (
        AssetStorage(app_config=app_config) if asset_storage is None else asset_storage
    )
    local_assets = LocalAssets(
        asset_storage=asset_storage, phash=phash, database=database, publisher=events
    )
    art_matcher = unused(ArtMatcher) if art_matcher is None else art_matcher
    proxy_clients = (
        unused(ProxyClientManager) if proxy_clients is None else proxy_clients
    )
    tmdb = NoopTmdb() if tmdb is None else tmdb
    youtube = NoopYoutube() if youtube is None else youtube
    candidates = ArtCandidates(
        database=database,
        provider_registry=provider_registry,
        tmdb_client=tmdb,
        app_config=app_config,
    )

    art = (
        ArtService(
            app_config=app_config,
            database=database,
            asset_storage=asset_storage,
            matcher=art_matcher,
            downloads=downloads,
            publisher=events,
            provider_registry=provider_registry,
            candidates=candidates,
            image_clients=proxy_clients,
        )
        if art is None
        else art
    )
    library = (
        LibraryService(
            database=database,
            downloads=downloads,
            publisher=events,
            asset_storage=asset_storage,
            provider_registry=provider_registry,
            proxy_clients=proxy_clients,
        )
        if library is None
        else library
    )
    server_audit = (
        ServerAuditService(
            config_dir=config_dir,
            background_jobs=background_jobs,
            provider_registry=provider_registry,
            local_assets=local_assets,
            phash=phash,
            image_clients=proxy_clients,
            publisher=events,
            app_config=app_config,
            database=database,
        )
        if server_audit is None
        else server_audit
    )
    collections = (
        CollectionsService(
            database=database,
            provider_registry=provider_registry,
            publisher=events,
            downloads=downloads,
            proxy_clients=proxy_clients,
            app_config=app_config,
        )
        if collections is None
        else collections
    )
    themes = (
        ThemesService(
            database=database,
            asset_storage=asset_storage,
            downloads=downloads,
            publisher=events,
            youtube_resolver=youtube,
        )
        if themes is None
        else themes
    )
    asset_manager = (
        AssetManagerService(
            config_dir=config_dir,
            background_jobs=background_jobs,
            publisher=events,
            app_config=app_config,
            local_assets=local_assets,
            provider_registry=provider_registry,
            database=database,
        )
        if asset_manager is None
        else asset_manager
    )
    stats = (
        StatsService(
            database=database,
            backups=backups,
            collections=collections,
        )
        if stats is None
        else stats
    )

    return RuntimeServices(
        app_settings=app_config,
        database=database,
        auth=AuthService(app_config, database),
        redactor=Redactor(
            value
            for name, value in app_config.model_dump().items()
            if is_sensitive_field(name) and isinstance(value, str)
        ),
        scheduler=scheduler,
        websockets=websockets,
        events=events,
        background_jobs=background_jobs,
        provider_registry=provider_registry,
        downloads=downloads,
        sync=sync,
        backups=backups,
        assets=assets,
        public_dataset=public_dataset,
        phash=phash,
        asset_storage=asset_storage,
        art_matcher=art_matcher,
        proxy_clients=proxy_clients,
        tmdb=tmdb,
        youtube=youtube,
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
        ),
        asset_manager=asset_manager,
        stats=stats,
        config_dir=config_dir,
        connectivity_probe=connectivity_probe,
    )


class RecordingPublisher(NullEventPublisher):
    """Event publisher that records everything a managed job broadcasts."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self._published = asyncio.Condition()

    @override
    async def broadcast(
        self,
        event: str,
        payload: Any = None,
        *,
        before_publish: Callable[[str, Any], None] | None = None,
    ) -> None:
        """Record one broadcast, applying projection updates first."""
        await super().broadcast(event, payload, before_publish=before_publish)
        async with self._published:
            self.events.append((event, payload))
            self._published.notify_all()

    async def wait_until(self, condition: Callable[[], Awaitable[bool]]) -> None:
        """Wait, one broadcast at a time, until *condition* holds.

        Services announce every state change, so a state the test waits for
        is reached on a broadcast rather than after some amount of time.
        """
        while True:
            seen = len(self.events)
            if await condition():
                return
            async with self._published:
                while len(self.events) == seen:
                    await self._published.wait()

    def names(self) -> list[str]:
        """Return just the event names, in order."""
        return [event for event, _ in self.events]

    def payloads(self, event: str) -> list[Any]:
        """Return the payloads broadcast for one event name."""
        return [payload for name, payload in self.events if name == event]


class JobProbe:
    """A real JobContext plus the events and snapshots it produced.

    Managed jobs decide their own terminal status and snapshot behaviour, so
    tests observe them through a genuine context rather than a stand-in.
    """

    def __init__(
        self,
        *,
        lifecycle: ManagedJobLifecycle | None = None,
        stop_requested: bool = False,
    ) -> None:
        self.publisher = RecordingPublisher()
        self.snapshots: list[tuple[str, dict[str, Any]]] = []
        self.resume_snapshots: list[tuple[str, dict[str, Any]]] = []
        self.context = JobContext(
            lifecycle=lifecycle or ManagedJobLifecycle(JobKind.SYNC),
            started_at="2026-01-01T00:00:00+00:00",
            save_snapshot=self._save_snapshot,
            save_resume_snapshot=self._save_resume_snapshot,
            publisher=self.publisher,
        )
        if stop_requested:
            self.request_stop()

    def request_stop(self) -> None:
        """Ask the job to stop, as the slot does when a client stops it."""
        self.context.stop_event.set()

    def _save_snapshot(self, event: str, payload: dict[str, Any]) -> None:
        """Record a terminal snapshot."""
        self.snapshots.append((event, payload))

    def _save_resume_snapshot(self, event: str, payload: dict[str, Any]) -> None:
        """Record a running-state snapshot."""
        self.resume_snapshots.append((event, payload))

    @property
    def events(self) -> list[tuple[str, Any]]:
        """Return every broadcast event."""
        return self.publisher.events

    def names(self) -> list[str]:
        """Return just the broadcast event names, in order."""
        return self.publisher.names()

    def terminal(self) -> tuple[str, dict[str, Any]]:
        """Return the single terminal snapshot, failing if there is not exactly one."""
        assert len(self.snapshots) == 1, self.snapshots
        return self.snapshots[0]


def make_download_service(
    publisher: protocols.EventPublisher,
    *,
    provider_registry: ProviderRegistry,
    asset_storage: AssetStorage,
    phash: PhashService,
    image_clients: ProxyClientManager,
    youtube_resolver: YouTubeResolver,
    app_config: Settings,
    database: Database,
    library_gate: LibraryGate | None = None,
) -> DownloadService:
    """Wire a real download queue with the test's external collaborators."""
    return DownloadService(
        art_handler=DownloadArtHandler(
            provider_registry=provider_registry,
            asset_storage=asset_storage,
            phash=phash,
            image_clients=image_clients,
            app_config=app_config,
            database=database,
        ),
        theme_handler=DownloadThemeHandler(
            asset_storage=asset_storage,
            youtube_resolver=youtube_resolver,
            database=database,
        ),
        provider_registry=provider_registry,
        events=DownloadEventPublisher(publisher),
        publisher=publisher,
        asset_storage=asset_storage,
        app_config=app_config,
        database=database,
        library_gate=library_gate,
    )


def make_local_assets(
    *,
    app_config: Settings,
    database: Database,
    phash: PhashService | None = None,
    asset_storage: AssetStorage | None = None,
    publisher: protocols.EventPublisher | None = None,
) -> LocalAssets:
    """Build the local-file record service the way the runtime does."""
    return LocalAssets(
        asset_storage=asset_storage or AssetStorage(app_config=app_config),
        phash=phash or PhashService(app_config=app_config),
        database=database,
        publisher=publisher or NullEventPublisher(),
    )


class RecordingSchedules(NoopSchedules):
    def __init__(self, *, app_config: Settings) -> None:
        super().__init__(app_config=app_config)
        self.calls: list[tuple[str, object]] = []

    @override
    async def all(self) -> list[Any]:
        self.calls.append(("list", None))
        return []

    @override
    async def create(self, fields: ScheduleWrite[Any]) -> Any:
        self.calls.append(("create", (fields.name, fields.config)))
        return 1

    @override
    async def update(self, schedule_id: int, fields: ScheduleWrite[Any]) -> Any:
        self.calls.append(("update", (schedule_id, fields.name, fields.config)))
        return schedule_id

    @override
    async def delete(self, schedule_id: int) -> StatusResponse:
        self.calls.append(("delete", schedule_id))
        return StatusResponse(status=Status.DELETED)

    @override
    async def run_now(self, schedule_id: int) -> StatusResponse:
        self.calls.append(("run", schedule_id))
        return StatusResponse(status=Status.QUEUED)
