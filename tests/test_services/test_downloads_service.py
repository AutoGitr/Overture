"""Full download manager processing paths with isolated DB and fake upstreams."""

lazy import asyncio
lazy import threading
lazy from collections.abc import Collection
lazy from contextlib import AsyncExitStack
lazy from datetime import UTC, datetime
lazy from io import BytesIO
lazy from pathlib import Path
lazy from typing import Any, cast, override
lazy from unittest.mock import AsyncMock

lazy import httpx2
lazy import pytest
lazy from PIL import Image
lazy from sqlalchemy.ext.asyncio import async_sessionmaker
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import read_art_slot
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.schedule import TaskSchedule
lazy from overture.db.models.season import Season
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    JobStatus,
    JobType,
    MediaType,
    ServerAsset,
    ServerType,
)
lazy from overture.jobs.gate import LibraryGate
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.repositories.downloads import DownloadJobRepository
lazy from overture.services.art.phash import PHASH_HEX_LENGTH, PhashService
lazy from overture.services.downloads import art as art_module
lazy from overture.services.downloads.art import DownloadArtHandler
lazy from overture.services.downloads.events import DownloadEventPublisher
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.downloads.results import DownloadedCollectionTheme
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.downloads.theme import DownloadThemeHandler
lazy from overture.services.downloads.watch import DownloadOutcome
lazy from overture.services.storage.assets import AssetStorage, StoredFile
lazy from overture.services.themes.youtube_resolver import (
    DownloadError,
    ThemeAudio,
    YouTubeResolver,
)
lazy from overture.utils.file import compute_bytes_hash
lazy from overture.utils.image import RateLimitedError
lazy from overture.utils.progress import ProgressCallback, ProgressUpdate
lazy from overture.ws.events import validate_event_payload
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    StaticImageClients,
    unused,
)


@pytest.mark.parametrize(
    "initial", [None, JobStatus.RUNNING, JobStatus.DONE, JobStatus.CANCELLED]
)
async def test_unexpected_processing_failure_preserves_terminal_jobs_and_settles_watch(
    initial: JobStatus | None,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    if initial is not None:
        async with database.write_session() as session:
            session.add(MediaItem(id=1, title="Movie", media_type=MediaType.MOVIE))
            await session.flush()
            session.add(
                DownloadJob(
                    id="unexpected",
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    media_item_id=1,
                    job_type=JobType.THEME,
                    target_url="abcDEF123_4",
                    status=initial,
                    completed_at=datetime(2026, 1, 1, tzinfo=UTC)
                    if initial in {JobStatus.DONE, JobStatus.CANCELLED}
                    else None,
                )
            )
    publisher = RecordingPublisher()
    manager = _download_manager(
        publisher,
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    monkeypatch.setattr(
        manager, "_run_job", AsyncMock(side_effect=RuntimeError("internal failure"))
    )

    with manager.watch() as watch:
        watch.tracking("Movie")("unexpected")
        await manager.process_job("unexpected")
        watch.close()
        outcomes = [outcome async for outcome in watch.stream()]

    assert outcomes == [
        DownloadOutcome(
            "Movie",
            "Download failed"
            if initial is JobStatus.RUNNING
            else "the download did not run",
        )
    ]
    async with database.read_session() as session:
        stored = await session.get(DownloadJob, "unexpected")
    if initial is None:
        assert stored is None
    else:
        assert stored is not None
        assert stored.status is (
            JobStatus.FAILED if initial is JobStatus.RUNNING else initial
        )
        assert stored.completed_at is not None
    assert [name for name, _ in publisher.events] == (
        ["download.failed"] if initial is JobStatus.RUNNING else []
    )


async def test_unpersistable_failure_stops_the_lane_and_still_settles_watch(
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    async with database.write_session() as session:
        session.add(MediaItem(id=1, title="Movie", media_type=MediaType.MOVIE))
        await session.flush()
        session.add(
            DownloadJob(
                id="unsaved",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                media_item_id=1,
                job_type=JobType.THEME,
                status=JobStatus.RUNNING,
            )
        )
    manager = _download_manager(
        RecordingPublisher(),
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    original = RuntimeError("operation failed")
    monkeypatch.setattr(manager, "_run_job", AsyncMock(side_effect=original))
    monkeypatch.setattr(
        manager, "fail_job", AsyncMock(side_effect=OSError("database failed"))
    )
    with manager.watch() as watch:
        watch.tracking("Movie")("unsaved")
        with pytest.raises(
            RuntimeError, match="failure persistence unavailable"
        ) as raised:
            await manager.process_job("unsaved")
        watch.close()
        outcomes = [outcome async for outcome in watch.stream()]
    assert raised.value.__cause__ is original
    assert outcomes == [DownloadOutcome("Movie", "the download did not run")]
    async with database.read_session() as session:
        stored = await session.get(DownloadJob, "unsaved")
    assert stored is not None
    assert stored.status is JobStatus.RUNNING


async def test_start_stops_interrupted_job_before_workers_claim_it(
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    async with database.write_session() as session:
        session.add(MediaItem(id=1, title="Movie", media_type=MediaType.MOVIE))
        await session.flush()
        session.add(
            DownloadJob(
                id="interrupted",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
                media_item_id=1,
                job_type=JobType.THEME,
                target_url="abcDEF123_4",
                status=JobStatus.RUNNING,
                progress_percent=67,
            )
        )
    manager = _download_manager(
        RecordingPublisher(),
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    release = asyncio.Event()

    async def worker(_lane: JobType) -> None:
        await release.wait()

    monkeypatch.setattr(manager, "_worker_loop", worker)
    try:
        await manager.start()
        await manager.start()
        assert manager.healthy
        async with database.read_session() as session:
            stored = await session.get(DownloadJob, "interrupted")
        assert stored is not None
        assert stored.status is JobStatus.CANCELLED
        assert stored.progress_percent == 67
        assert stored.completed_at is not None
        assert stored.target_url == "abcDEF123_4"
    finally:
        release.set()
        await manager.stop()


def _jpeg_bytes() -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (4, 6), color="blue").save(buffer, format="JPEG")
    return buffer.getvalue()


class RefreshingProvider:
    server_type = ServerType.PLEX

    def __init__(self, headers: dict[str, str] | None = None) -> None:
        #: Each refreshed item, with the assets unlocked for it.
        self.refreshed: list[tuple[str, tuple[ServerAsset, ...]]] = []
        self.headers = headers or {}
        self.download_header_urls: list[str] = []

    async def refresh_item(
        self, item_id: str, *, unlock: Collection[ServerAsset]
    ) -> None:
        self.refreshed.append((item_id, tuple(sorted(unlock))))

    def get_download_headers(self, url: str) -> dict[str, str]:
        self.download_header_urls.append(url)
        return self.headers

    async def upload_collection_theme(
        self, server_item_id: str, mp3_bytes: bytes
    ) -> str | None:
        return None


class RecordingPublisher(NullEventPublisher):
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    @override
    async def broadcast(
        self,
        event: str,
        payload=None,
        *,
        before_publish=None,
    ) -> None:
        validate_event_payload(event, payload)
        if before_publish is not None:
            before_publish(event, payload)
        self.events.append((event, payload))


def _download_manager(
    publisher: RecordingPublisher,
    *,
    provider: RefreshingProvider,
    phash: PhashService,
    youtube_resolver: YouTubeResolver,
    image_clients: StaticImageClients | None = None,
    app_config: Settings,
    database: Database,
    library_gate: LibraryGate | None = None,
) -> DownloadService:
    asset_storage = AssetStorage(app_config=app_config)
    return DownloadService(
        art_handler=DownloadArtHandler(
            provider_registry=NoopProviderRegistry(provider),
            asset_storage=asset_storage,
            phash=phash,
            image_clients=cast("Any", image_clients or StaticImageClients()),
            app_config=app_config,
            database=database,
        ),
        theme_handler=DownloadThemeHandler(
            asset_storage=asset_storage,
            youtube_resolver=youtube_resolver,
            database=database,
        ),
        provider_registry=NoopProviderRegistry(provider),
        events=DownloadEventPublisher(publisher),
        publisher=publisher,
        asset_storage=asset_storage,
        app_config=app_config,
        database=database,
        library_gate=library_gate,
    )


async def _noop_progress(_update: ProgressUpdate) -> None:
    """Discard progress reports in tests that do not assert on them."""


@pytest.mark.parametrize("job_type", list(JobType))
async def test_start_cancels_jobs_left_by_a_previous_run(
    job_type: JobType,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    manager = _download_manager(
        RecordingPublisher(),
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    release = asyncio.Event()

    async def worker(_lane: JobType) -> None:
        await release.wait()

    monkeypatch.setattr(manager, "_worker_loop", worker)
    target = (
        JobTarget.art(1, ArtType.POSTER, "https://images.test/original.jpg")
        if job_type is JobType.ART
        else JobTarget.theme(1, "abcDEF123_4")
        if job_type is JobType.THEME
        else JobTarget.collection_theme(
            "collection-1", MediaType.MOVIE, "Saga", "abcDEF123_4"
        )
    )
    async with database.write_session() as session:
        session.add(MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie"))
        await session.flush()
        original_id, _ = await manager.queue_job(session, target)
    try:
        await manager.start()
        async with database.read_session() as session:
            job = await session.get(DownloadJob, original_id)
        assert job is not None
        assert job.status is JobStatus.CANCELLED
        assert job.error_message is not None
    finally:
        release.set()
        await manager.stop()


@pytest.mark.parametrize("fails", [False, True])
async def test_shutdown_owns_remote_upload_until_it_settles(
    monkeypatch: pytest.MonkeyPatch,
    *,
    fails: bool,
    app_config: Settings,
    database: Database,
) -> None:
    entered, release = asyncio.Event(), asyncio.Event()
    provider = RefreshingProvider()

    async def upload(_server_id: str, _data: bytes) -> str:
        entered.set()
        await release.wait()
        if fails:
            raise MediaServerError("Upload outcome unknown")
        return "remote-theme"

    monkeypatch.setattr(provider, "upload_collection_theme", upload)
    publisher = RecordingPublisher()
    manager = _download_manager(
        publisher,
        provider=provider,
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    monkeypatch.setattr(
        manager.theme_handler,
        "download_collection_theme",
        AsyncMock(
            return_value=DownloadedCollectionTheme(
                youtube_id="abcDEF123_4",
                title="Theme",
                duration=60,
                audio_bytes=b"audio",
            )
        ),
    )
    await manager.start()
    stopping: asyncio.Task[None] | None = None
    try:
        with manager.watch() as watch:
            async with database.write_session() as session:
                job_id, _ = await manager.queue_job(
                    session,
                    JobTarget.collection_theme(
                        "collection-1", MediaType.MOVIE, "Saga", "abcDEF123_4"
                    ),
                )
            watch.tracking("Saga")(job_id)
            await manager.committed(session)
            await asyncio.wait_for(entered.wait(), timeout=2)
            stopping = asyncio.create_task(manager.stop())
            await asyncio.sleep(0)
            assert not stopping.done()
            release.set()
            await asyncio.wait_for(stopping, timeout=2)
            watch.close()
            (outcome,) = [outcome async for outcome in watch.stream()]
        async with database.read_session() as session:
            stored = await session.get(DownloadJob, job_id)
            assert stored is not None
            assert stored.status is (JobStatus.FAILED if fails else JobStatus.DONE)
        assert (outcome.error is not None, outcome.cancelled) == (fails, False)
        terminal = [
            event
            for event, _ in publisher.events
            if event in {"download.completed", "download.failed", "download.cancelled"}
        ]
        assert terminal == ["download.failed" if fails else "download.completed"]
    finally:
        release.set()
        await manager.stop()
        if stopping is not None:
            await stopping


async def test_process_art_job_downloads_writes_hashes_and_refreshes_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    provider = RefreshingProvider()
    publisher = RecordingPublisher()
    phash = PhashService(app_config=app_config)

    async def fake_private_url(_url: str) -> bool:
        return False

    async def fake_fetch_image_bytes(
        _url: str, _client: httpx2.AsyncClient, **_kwargs: object
    ) -> bytes:
        return _jpeg_bytes()

    async def fake_phash(_data: bytes) -> str:
        return "0" * PHASH_HEX_LENGTH

    monkeypatch.setattr(art_module, "is_private_url", fake_private_url)
    monkeypatch.setattr(art_module, "fetch_image_bytes", fake_fetch_image_bytes)
    monkeypatch.setattr(phash, "compute_from_bytes", fake_phash)

    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    async with isolated_session_factory() as session:
        item = MediaItem(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
            folder_path=str(movie_dir),
            server_item_id="plex-1",
        )
        session.add(item)
        await session.flush()
        session.add(
            DownloadJob(
                id="job-art",
                media_item_id=1,
                job_type=JobType.ART,
                art_type=ArtType.POSTER,
                target_url="https://images.test/poster.jpg",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()

    manager = _download_manager(
        publisher,
        provider=provider,
        phash=phash,
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    with manager.watch() as watch:
        watch.tracking("Movie (poster)")("job-art")
        await manager.process_job("job-art")
        watch.close()
        settled = [outcome async for outcome in watch.stream()]

    assert settled == [DownloadOutcome("Movie (poster)", None)]

    async with isolated_session_factory() as session:
        job = await session.get(DownloadJob, "job-art")
        item = await session.get(MediaItem, 1)
        assert item is not None

    assert job is not None
    assert job.status == "done"
    poster = read_art_slot(item, ArtType.POSTER)
    assert poster.file_hash
    assert poster.phash == "0" * PHASH_HEX_LENGTH
    assert (movie_dir / "poster.jpg").is_file()
    assert provider.refreshed == [("plex-1", ("poster",))]
    assert [event for event, _ in publisher.events] == [
        "download.started",
        "download.progress",
        "download.progress",
        "download.progress",
        "download.completed",
        "library.item.upserted",
    ]


@pytest.mark.parametrize("identical", [True, False])
async def test_art_job_writes_only_when_the_bytes_differ(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    identical: bool,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """A download identical to the file on disk records it and writes nothing."""
    provider = RefreshingProvider()
    publisher = RecordingPublisher()
    phash = PhashService(app_config=app_config)
    downloaded = _jpeg_bytes()

    async def fake_private_url(_url: str) -> bool:
        return False

    async def fake_fetch_image_bytes(
        _url: str, _client: httpx2.AsyncClient, **_kwargs: object
    ) -> bytes:
        return downloaded

    async def fake_phash(_data: bytes) -> str:
        return "0" * PHASH_HEX_LENGTH

    monkeypatch.setattr(art_module, "is_private_url", fake_private_url)
    monkeypatch.setattr(art_module, "fetch_image_bytes", fake_fetch_image_bytes)
    monkeypatch.setattr(phash, "compute_from_bytes", fake_phash)

    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    poster = movie_dir / "poster.jpg"
    poster.write_bytes(downloaded if identical else b"an older poster")
    before = poster.stat()
    async with isolated_session_factory() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.MOVIE,
                title="Movie",
                folder_path=str(movie_dir),
                server_item_id="plex-1",
            )
        )
        await session.flush()
        session.add(
            DownloadJob(
                id="job-art",
                media_item_id=1,
                job_type=JobType.ART,
                art_type=ArtType.POSTER,
                target_url="https://images.test/poster.jpg",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()

    manager = _download_manager(
        publisher,
        provider=provider,
        phash=phash,
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    with manager.watch() as watch:
        watch.tracking("Movie (poster)")("job-art")
        await manager.process_job("job-art")
        watch.close()
        settled = [outcome async for outcome in watch.stream()]

    assert settled == [DownloadOutcome("Movie (poster)", None, unchanged=identical)]
    after = poster.stat()
    assert poster.read_bytes() == downloaded
    assert (after.st_ino == before.st_ino) is identical
    assert provider.refreshed == ([] if identical else [("plex-1", ("poster",))])
    [completed] = [
        cast("dict[str, Any]", payload)
        for event, payload in publisher.events
        if event == "download.completed"
    ]
    assert completed["unchanged"] is identical

    async with isolated_session_factory() as session:
        item = await session.get(MediaItem, 1)
        assert item is not None
        slot = read_art_slot(item, ArtType.POSTER)
    assert slot.url == "https://images.test/poster.jpg"
    assert slot.file_hash == compute_bytes_hash(downloaded)
    assert (slot.file_mtime_ns, slot.file_size) == (after.st_mtime_ns, after.st_size)


async def test_process_art_job_allows_trusted_private_media_server_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    app_config.MEDIA_SERVER = ServerType.PLEX
    app_config.MEDIA_SERVER_URL = "http://127.0.0.1:32400"
    app_config.MEDIA_SERVER_VERIFY_TLS = False
    provider = RefreshingProvider(headers={"X-Plex-Token": "server-token"})
    publisher = RecordingPublisher()
    phash = PhashService(app_config=app_config)
    fetches: list[dict[str, Any]] = []
    image_clients = StaticImageClients()

    async def fake_private_url(_url: str) -> bool:
        return True

    async def fake_fetch_image_bytes(
        url: str,
        _client: httpx2.AsyncClient,
        *,
        on_progress: Any,
        **kwargs: Any,
    ) -> bytes:
        fetches.append(
            {"url": url, "reports_progress": on_progress is not None, **kwargs}
        )
        return _jpeg_bytes()

    async def fake_phash(_data: bytes) -> str:
        return "2" * PHASH_HEX_LENGTH

    monkeypatch.setattr(art_module, "is_private_url", fake_private_url)
    monkeypatch.setattr(art_module, "fetch_image_bytes", fake_fetch_image_bytes)
    monkeypatch.setattr(phash, "compute_from_bytes", fake_phash)

    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    target_url = (
        "http://127.0.0.1:32400/library/metadata/1/thumb"
        "?X-Plex-Token=browser-token&tag=poster"
    )
    async with isolated_session_factory() as session:
        item = MediaItem(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
            folder_path=str(movie_dir),
            server_item_id="plex-1",
        )
        session.add(item)
        await session.flush()
        session.add(
            DownloadJob(
                id="job-art",
                media_item_id=1,
                job_type=JobType.ART,
                art_type=ArtType.POSTER,
                target_url=target_url,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()

    manager = _download_manager(
        publisher,
        provider=provider,
        phash=phash,
        youtube_resolver=unused(YouTubeResolver),
        image_clients=image_clients,
        app_config=app_config,
        database=database,
    )
    await manager.process_job("job-art")

    async with isolated_session_factory() as session:
        item = await session.get(MediaItem, 1)
        assert item is not None

    clean_url = "http://127.0.0.1:32400/library/metadata/1/thumb?tag=poster"
    assert image_clients.requested_urls == [clean_url]
    assert provider.download_header_urls == [clean_url]
    assert fetches == [
        {
            "url": clean_url,
            "reports_progress": True,
            "allow_private": True,
            "headers": {"X-Plex-Token": "server-token"},
            # The art lane's workers bound its downloads, not the shared gate.
            "transfer_slots": None,
        }
    ]
    # Trusted private media-server URLs are not persisted as the stored URL
    poster = read_art_slot(item, ArtType.POSTER)
    assert poster.url is None
    assert poster.file_hash


async def test_process_art_job_blocks_untrusted_private_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    provider = RefreshingProvider()
    phash = PhashService(app_config=app_config)

    async def fake_private_url(_url: str) -> bool:
        return True

    monkeypatch.setattr(art_module, "is_private_url", fake_private_url)
    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    item = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Movie",
        folder_path=str(movie_dir),
    )
    job = DownloadJob(
        id="job-art",
        media_item_id=1,
        job_type=JobType.ART,
        art_type=ArtType.POSTER,
        target_url="http://10.0.0.10/poster.jpg",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    handler = DownloadArtHandler(
        provider_registry=NoopProviderRegistry(provider),
        asset_storage=AssetStorage(app_config=app_config),
        phash=phash,
        image_clients=cast("Any", StaticImageClients()),
        app_config=app_config,
        database=database,
    )

    with pytest.raises(DownloadError, match="private address"):
        await handler.download(job, item, _noop_progress)


@pytest.mark.parametrize(
    ("failure", "message"),
    [
        (
            RateLimitedError(
                "tpdb.test is rate limiting requests; pausing them for 60s"
            ),
            "tpdb.test is rate limiting requests; pausing them for 60s",
        ),
        (
            httpx2.ConnectError("Connection refused"),
            "Could not reach tpdb.test: Connection refused",
        ),
        (httpx2.ReadTimeout(""), "Could not reach tpdb.test: ReadTimeout"),
    ],
)
async def test_art_download_failures_say_why(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    message: str,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async def public_url(_url: str) -> bool:
        return False

    async def fail(*_args: object, **_kwargs: object) -> bytes:
        raise failure

    monkeypatch.setattr(art_module, "is_private_url", public_url)
    monkeypatch.setattr(art_module, "fetch_image_bytes", fail)
    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    item = MediaItem(
        id=1, media_type=MediaType.MOVIE, title="Movie", folder_path=str(movie_dir)
    )
    job = DownloadJob(
        id="job-art",
        media_item_id=1,
        job_type=JobType.ART,
        art_type=ArtType.POSTER,
        target_url="https://tpdb.test/poster.jpg",
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    handler = DownloadArtHandler(
        provider_registry=NoopProviderRegistry(RefreshingProvider()),
        asset_storage=AssetStorage(app_config=app_config),
        phash=PhashService(app_config=app_config),
        image_clients=cast("Any", StaticImageClients()),
        app_config=app_config,
        database=database,
    )

    with pytest.raises(DownloadError) as exc:
        await handler.download(job, item, _noop_progress)
    assert str(exc.value) == message


async def test_process_season_poster_job_updates_asset_and_parent_aggregates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    provider = RefreshingProvider()
    publisher = RecordingPublisher()
    phash = PhashService(app_config=app_config)

    async def fake_private_url(_url: str) -> bool:
        return False

    async def fake_fetch_image_bytes(
        _url: str, _client: httpx2.AsyncClient, **_kwargs: object
    ) -> bytes:
        return _jpeg_bytes()

    async def fake_phash(_data: bytes) -> str:
        return "1" * PHASH_HEX_LENGTH

    monkeypatch.setattr(art_module, "is_private_url", fake_private_url)
    monkeypatch.setattr(art_module, "fetch_image_bytes", fake_fetch_image_bytes)
    monkeypatch.setattr(phash, "compute_from_bytes", fake_phash)

    show_dir = tmp_path / "Show"
    show_dir.mkdir()
    async with isolated_session_factory() as session:
        item = MediaItem(
            id=1,
            media_type=MediaType.SHOW,
            title="Show",
            folder_path=str(show_dir),
            server_item_id="plex-show",
        )
        session.add(item)
        await session.flush()
        season = Season(
            id=10,
            media_item_id=1,
            season_num=1,
            file_count=8,
        )
        session.add(season)
        await session.flush()
        session.add(
            DownloadJob(
                id="job-season-poster",
                media_item_id=1,
                job_type=JobType.ART,
                art_type=ArtType.SEASON_POSTER,
                season_id=10,
                target_url="https://images.test/season-1.jpg",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()

    manager = _download_manager(
        publisher,
        provider=provider,
        phash=phash,
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    await manager.process_job("job-season-poster")

    async with isolated_session_factory() as session:
        item = await session.get(MediaItem, 1)
        season = await session.get(Season, 10)
        assert item is not None
        assert season is not None

    season_poster = read_art_slot(season, ArtType.SEASON_POSTER)
    assert season_poster.file_hash
    assert season_poster.phash == "1" * PHASH_HEX_LENGTH
    # Season aggregate flags are now computed on read (not stored on MediaItem)
    # A season poster is not the show's, so the show unlocks nothing.
    assert provider.refreshed == [("plex-show", ())]
    assert [event for event, _ in publisher.events] == [
        "download.started",
        "download.progress",
        "download.progress",
        "download.progress",
        "download.completed",
        "library.item.upserted",
    ]


async def test_process_theme_job_writes_theme_and_updates_item(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    provider = RefreshingProvider()
    publisher = RecordingPublisher()
    levelled: list[bool] = []

    class FakeYoutubeResolver:
        async def download_audio(
            self,
            youtube_id: str,
            min_duration: int = 30,
            max_duration: int = 300,
            progress_callback: ProgressCallback | None = None,
            *,
            normalize_loudness: bool,
        ) -> ThemeAudio:
            _ = youtube_id, min_duration, max_duration, progress_callback
            levelled.append(normalize_loudness)
            return ThemeAudio(audio_bytes=b"mp3", title="Theme", duration=120)

    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    async with isolated_session_factory() as session:
        item = MediaItem(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
            folder_path=str(movie_dir),
            server_item_id="plex-1",
        )
        session.add(item)
        session.add(AppSettings(normalize_theme_loudness=False))
        await session.flush()
        session.add(
            DownloadJob(
                id="job-theme",
                media_item_id=1,
                job_type=JobType.THEME,
                target_url="abcDEF123_4",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        item.theme_provenance_cleared = True
        await session.commit()

    manager = _download_manager(
        publisher,
        provider=provider,
        phash=PhashService(app_config=app_config),
        youtube_resolver=cast("Any", FakeYoutubeResolver()),
        app_config=app_config,
        database=database,
    )
    await manager.process_job("job-theme")

    async with isolated_session_factory() as session:
        job = await session.get(DownloadJob, "job-theme")
        item = await session.get(MediaItem, 1)
        assert item is not None

    assert job is not None
    assert job.status == "done"
    assert levelled == [False]
    assert item.youtube_id == "abcDEF123_4"
    assert item.youtube_title == "Theme"
    assert item.youtube_duration == 120
    assert item.theme_file_hash is not None
    assert item.theme_provenance_cleared is False
    assert item.youtube_id_source == "download"
    assert (movie_dir / "theme.mp3").read_bytes() == b"mp3"
    assert provider.refreshed == [("plex-1", ("theme",))]
    assert [event for event, _ in publisher.events] == [
        "download.started",
        "download.completed",
        "library.item.upserted",
    ]


async def test_snapshot_events_restore_every_persisted_active_download(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with isolated_session_factory() as session:
        item = MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie")
        session.add(item)
        await session.flush()
        session.add(
            DownloadJob(
                id="queued",
                media_item_id=1,
                job_type=JobType.ART,
                art_type=ArtType.POSTER,
                status=JobStatus.PENDING,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()

    publisher = RecordingPublisher()
    event_publisher = DownloadEventPublisher(publisher)
    asset_storage = AssetStorage(app_config=app_config)
    manager = DownloadService(
        art_handler=DownloadArtHandler(
            provider_registry=NoopProviderRegistry(),
            asset_storage=asset_storage,
            phash=PhashService(app_config=app_config),
            image_clients=cast("Any", StaticImageClients()),
            app_config=app_config,
            database=database,
        ),
        theme_handler=DownloadThemeHandler(
            asset_storage=asset_storage,
            youtube_resolver=unused(YouTubeResolver),
            database=database,
        ),
        provider_registry=NoopProviderRegistry(),
        events=event_publisher,
        publisher=publisher,
        asset_storage=asset_storage,
        app_config=app_config,
        database=database,
    )
    event_publisher.remember_job_event(
        "download.progress",
        {
            "job": {
                "kind": "download",
                "status": "progress",
                "id": "active",
                "target": {
                    "target_type": "item",
                    "media_item_id": 2,
                    "job_type": "theme",
                },
            },
            "percent": 50,
            "stage": "downloading",
        },
    )

    snapshots = {event.job.id: event for event in await manager.snapshot_events()}

    # Queued rows are part of the snapshot; unpersisted progress cannot resurrect jobs.
    assert list(snapshots) == ["queued"]
    assert snapshots["queued"].job.status == "pending"


async def test_another_writer_can_commit_while_a_download_is_in_flight(
    tmp_path: Path,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """A download must not hold the write lock while it downloads.

    SQLite has one write lock for the whole application. A theme job is a
    YouTube download and an ffmpeg transcode; while that ran inside the job's
    transaction, every other writer - a sync batch, a settings save - queued
    behind it, and the ones that ran out of patience reported "database is
    locked". This asserts the shape that prevents it: mid-download, an
    unrelated writer still gets through.
    """
    publisher = RecordingPublisher()
    provider = RefreshingProvider()

    class WritingResolver:
        """Stands in for yt-dlp, and writes to the database while it works."""

        async def download_audio(
            self,
            youtube_id: str,
            min_duration: int = 30,
            max_duration: int = 300,
            progress_callback: ProgressCallback | None = None,
            *,
            normalize_loudness: bool = False,
        ) -> ThemeAudio:
            _ = youtube_id, min_duration, max_duration, progress_callback
            _ = normalize_loudness
            async with database.write_session() as session:
                session.add(
                    TaskSchedule(
                        task_name="wrote-mid-download",
                        enabled=True,
                        cron_expression="0 * * * *",
                    )
                )
            return ThemeAudio(audio_bytes=b"mp3", title="Theme", duration=120)

    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()
    async with isolated_session_factory() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.MOVIE,
                title="Movie",
                folder_path=str(movie_dir),
            )
        )
        await session.flush()
        session.add(
            DownloadJob(
                id="job-theme",
                media_item_id=1,
                job_type=JobType.THEME,
                target_url="abcDEF123_4",
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()

    manager = _download_manager(
        publisher,
        provider=provider,
        phash=PhashService(app_config=app_config),
        youtube_resolver=cast("Any", WritingResolver()),
        app_config=app_config,
        database=database,
    )
    await manager.process_job("job-theme")

    async with isolated_session_factory() as session:
        names = list((await session.exec(select(TaskSchedule.task_name))).all())
        job = await session.get(DownloadJob, "job-theme")

    assert names == ["wrote-mid-download"]
    assert job is not None
    assert job.status == "done"


async def test_process_job_settles_the_watch_for_a_job_that_never_ran(
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """A run waiting on a job that has gone must not wait for it forever."""
    manager = _download_manager(
        RecordingPublisher(),
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )

    with manager.watch() as watch:
        watch.tracking("Movie (poster)")("job-gone")
        await manager.process_job("job-gone")
        watch.close()
        settled = [outcome async for outcome in watch.stream()]

    assert settled == [DownloadOutcome("Movie (poster)", "the download did not run")]


async def test_cancel_jobs_marks_pending_jobs_cancelled_and_settles_watch(
    *,
    app_config: Settings,
    database: Database,
    isolated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Cancelling queued jobs marks them CANCELLED and settles any active watch."""
    async with isolated_session_factory() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.MOVIE,
                title="Movie",
                folder_path="/path/to/movie",
            )
        )
        await session.flush()
        session.add(
            DownloadJob(
                id="job-pending-1",
                media_item_id=1,
                job_type=JobType.THEME,
                target_url="abcDEF123_4",
                status=JobStatus.PENDING,
                created_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        )
        await session.commit()

    publisher = RecordingPublisher()
    manager = _download_manager(
        publisher,
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )

    with manager.watch() as watch:
        watch.tracking("Movie (theme)")("job-pending-1")
        await manager.cancel_watch(watch)
        watch.close()
        settled = [outcome async for outcome in watch.stream()]

    assert settled == [
        DownloadOutcome("Movie (theme)", "the download was cancelled", cancelled=True)
    ]

    async with isolated_session_factory() as session:
        stored = await session.get(DownloadJob, "job-pending-1")

    assert stored is not None
    assert stored.status == JobStatus.CANCELLED
    assert stored.completed_at is not None
    assert [event for event, _ in publisher.events] == ["download.cancelled"]


@pytest.mark.parametrize("shutdown", [False, True])
async def test_cancel_jobs_cancels_running_task(
    *,
    shutdown: bool,
    app_config: Settings,
    database: Database,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
) -> None:
    """Shutdown retains an interrupted request while user cancellation ends it."""
    movie_dir = tmp_path / "Movie"
    movie_dir.mkdir()

    async with isolated_session_factory() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.MOVIE,
                title="Movie",
                folder_path=str(movie_dir),
            )
        )
        await session.flush()
        await session.commit()

    download_started = asyncio.Event()
    download_stopped = asyncio.Event()

    class HangingResolver:
        async def download_audio(self, **kwargs: Any) -> Any:
            download_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                download_stopped.set()

    publisher = RecordingPublisher()
    manager = _download_manager(
        publisher,
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=cast("YouTubeResolver", HangingResolver()),
        app_config=app_config,
        database=database,
    )

    await manager.start()
    try:
        with manager.watch() as watch:
            async with database.write_session() as session:
                job_id, _ = await manager.queue_job(
                    session,
                    JobTarget.theme(1, "abcDEF123_4"),
                )
            watch.tracking("Movie (theme)")(job_id)
            await manager.committed(session)
            async with asyncio.timeout(2):
                await download_started.wait()
                if shutdown:
                    await manager.stop()
                else:
                    await manager.cancel_watch(watch)
                    await manager.cancel_jobs([job_id])

            assert download_stopped.is_set()
            if not shutdown:
                assert manager.healthy

            watch.close()
            settled = [outcome async for outcome in watch.stream()]

        expected = [
            DownloadOutcome(
                "Movie (theme)", "the download was cancelled", cancelled=True
            )
        ]
        assert settled == expected

        async with isolated_session_factory() as session:
            stored = await session.get(DownloadJob, job_id)

        assert stored is not None
        assert stored.status is JobStatus.CANCELLED
        events = [event for event, _ in publisher.events]
        assert events.count("download.cancelled") == 1
    finally:
        await manager.stop()


@pytest.mark.parametrize("job_type", [JobType.ART, JobType.THEME])
@pytest.mark.parametrize("shutdown", [False, True])
@pytest.mark.parametrize(
    ("write_fails", "after_write"), [(False, False), (False, True), (True, False)]
)
async def test_stop_during_file_write_finishes_file_and_metadata(
    job_type: JobType,
    shutdown: bool,
    write_fails: bool,
    after_write: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    """Stop waits for an in-flight atomic save, including repeated shutdown."""
    folder = tmp_path / "Movie"
    folder.mkdir()
    target = folder / ("poster.jpg" if job_type is JobType.ART else "theme.mp3")
    target.write_bytes(b"old asset")
    data = _jpeg_bytes() if job_type is JobType.ART else b"complete audio"
    async with isolated_session_factory() as session:
        session.add(
            MediaItem(
                id=1, media_type=MediaType.MOVIE, title="Movie", folder_path=str(folder)
            )
        )
        await session.flush()
        await session.commit()

    async def public_url(_url: str) -> bool:
        return False

    async def fetch_image(
        _url: str, _client: httpx2.AsyncClient, **_kwargs: object
    ) -> bytes:
        return data

    class Resolver:
        async def download_audio(self, **kwargs: Any) -> ThemeAudio:
            return ThemeAudio(audio_bytes=data, title="Theme", duration=60)

    monkeypatch.setattr(art_module, "is_private_url", public_url)
    monkeypatch.setattr(art_module, "fetch_image_bytes", fetch_image)
    write_started = asyncio.Event()
    write_finished = asyncio.Event()
    release_write = threading.Event()
    loop = asyncio.get_running_loop()
    original_write = AssetStorage.write_file

    def blocked_write(
        storage: AssetStorage, path: str, content: bytes, root: str
    ) -> StoredFile:
        loop.call_soon_threadsafe(write_started.set)
        if not release_write.wait(5):
            raise TimeoutError("test did not release the writer")
        if write_fails:
            raise OSError("disk unavailable")
        stored = original_write(storage, path, content, root)
        loop.call_soon_threadsafe(write_finished.set)
        return stored

    monkeypatch.setattr(AssetStorage, "write_file", blocked_write)
    publisher = RecordingPublisher()
    manager = _download_manager(
        publisher,
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=cast("YouTubeResolver", Resolver()),
        app_config=app_config,
        database=database,
    )
    stops: list[asyncio.Task[None]] = []
    database_lock = AsyncExitStack()
    try:
        with manager.watch() as watch:
            await manager.start()
            async with database.write_session() as session:
                job_id, _ = await manager.queue_job(
                    session,
                    JobTarget.art(1, ArtType.POSTER, "https://images.test/poster.jpg")
                    if job_type is JobType.ART
                    else JobTarget.theme(1, "abcDEF123_4"),
                )
            watch.tracking("Movie")(job_id)
            await manager.committed(session)
            async with asyncio.timeout(5):
                await write_started.wait()
                if after_write:
                    await database_lock.enter_async_context(database.write_lock)
                    release_write.set()
                    await write_finished.wait()
                for _ in range(2 if shutdown else 1):
                    requested = asyncio.Event()

                    async def stop(requested: asyncio.Event) -> None:
                        requested.set()
                        if shutdown:
                            await manager.stop()
                        else:
                            await manager.cancel_watch(watch)

                    task = asyncio.create_task(stop(requested))
                    stops.append(task)
                    await requested.wait()
                    assert not task.done()
                assert target.read_bytes() == (data if after_write else b"old asset")
                release_write.set()
                await database_lock.aclose()
                await asyncio.gather(*stops)
                watch.close()
                outcomes = [outcome async for outcome in watch.stream()]

        assert len(outcomes) == 1
        assert bool(outcomes[0].error) is write_fails
        assert target.read_bytes() == (b"old asset" if write_fails else data)
        assert not list(folder.glob("*.tmp"))
        async with isolated_session_factory() as session:
            stored_job = await session.get(DownloadJob, job_id)
            item = await session.get(MediaItem, 1)
            assert stored_job is not None
            assert stored_job.status is (
                JobStatus.FAILED if write_fails else JobStatus.DONE
            )
            assert item is not None
            if job_type is JobType.ART:
                assert (
                    read_art_slot(item, ArtType.POSTER).file_hash is not None
                ) is not write_fails
            else:
                assert (item.theme_file_hash is not None) is not write_fails
                assert item.youtube_id == (None if write_fails else "abcDEF123_4")
        events = [event for event, _ in publisher.events]
        assert events.count("download.completed") == int(not write_fails)
        assert events.count("download.failed") == int(write_fails)
        assert "download.cancelled" not in events
    finally:
        release_write.set()
        await database_lock.aclose()
        await asyncio.gather(*stops, return_exceptions=True)
        await manager.stop()


async def test_idle_workers_sleep_without_claiming_or_delaying_shutdown(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    claim = AsyncMock()
    monkeypatch.setattr(DownloadJobRepository, "claim_pending", claim)
    manager = _download_manager(
        RecordingPublisher(),
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )
    await manager.start()
    try:
        await asyncio.sleep(0)
        claim.assert_not_awaited()
        await asyncio.wait_for(manager.stop(), timeout=2)
        assert not manager.healthy
    finally:
        await manager.stop()


async def test_the_snapshot_lists_active_jobs_in_queue_order(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with isolated_session_factory() as session:
        session.add_all(
            MediaItem(id=item_id, media_type=MediaType.MOVIE, title=f"Movie {item_id}")
            for item_id in (1, 2, 3, 4)
        )
        await session.flush()
        session.add_all(
            DownloadJob(
                id=job_id,
                media_item_id=item_id,
                job_type=JobType.ART,
                art_type=ArtType.POSTER,
                status=status,
                created_at=datetime(2026, 1, 1, minute=minute, tzinfo=UTC),
            )
            for job_id, item_id, minute, status in (
                ("c", 3, 1, JobStatus.RUNNING),
                ("a", 1, 3, JobStatus.PENDING),
                ("d", 4, 0, JobStatus.DONE),
                ("b", 2, 2, JobStatus.PENDING),
            )
        )
        await session.commit()
    manager = _download_manager(
        RecordingPublisher(),
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )

    assert [
        (event.job.id, event.job.target.title)
        for event in await manager.snapshot_events()
    ] == [("c", "Movie 3"), ("b", "Movie 2"), ("a", "Movie 1")]


async def test_download_service_holds_and_releases_library_gate(
    *, app_config: Settings, database: Database
) -> None:
    gate = LibraryGate()
    manager = _download_manager(
        RecordingPublisher(),
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
        library_gate=gate,
    )
    assert gate.blocker("sync") is None

    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.MOVIE,
                title="Movie 1",
                server_item_id="item-1",
            )
        )
        await session.commit()
        job_id, _ = await manager.queue_job(
            session,
            JobTarget.art(1, ArtType.POSTER, "http://example.com/poster.jpg"),
        )
        await session.commit()
    await manager.committed(session)

    assert gate.blocker("sync") == "downloads"

    await manager.cancel_jobs([job_id])
    assert gate.blocker("sync") is None


async def test_download_service_reconciles_gate_on_startup(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    gate = LibraryGate()
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.MOVIE,
                title="Movie 1",
                server_item_id="item-1",
            )
        )
        session.add(
            DownloadJob(
                id="reconcile-job",
                media_item_id=1,
                job_type=JobType.ART,
                art_type=ArtType.POSTER,
                target_url="http://example.com/poster.jpg",
                status=JobStatus.RUNNING,
                created_at=datetime.now(UTC),
            )
        )
        await session.commit()

    manager = _download_manager(
        RecordingPublisher(),
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
        library_gate=gate,
    )
    monkeypatch.setattr(manager, "process_job", AsyncMock())

    await manager.start()
    try:
        assert gate.blocker("sync") is None
        async with database.read_session() as session:
            stored = await session.get(DownloadJob, "reconcile-job")
            assert stored is not None
            assert stored.status is JobStatus.CANCELLED
    finally:
        await manager.stop()
    assert gate.blocker("sync") is None


async def test_rolled_back_download_does_not_block_sync(
    *, app_config: Settings, database: Database
) -> None:
    gate = LibraryGate()
    manager = _download_manager(
        RecordingPublisher(),
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
        library_gate=gate,
    )
    async with database.write_session() as session:
        session.add(MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie"))
    async with database.write_session() as session:
        await manager.queue_job(
            session, JobTarget.art(1, ArtType.POSTER, "https://images.test/poster.jpg")
        )
        await session.rollback()
    assert gate.blocker("sync") is None


async def test_download_workers_can_stop_while_waiting_for_sync(
    *, app_config: Settings, database: Database
) -> None:
    gate = LibraryGate()
    release = gate.hold("sync", "full sync")
    manager = _download_manager(
        RecordingPublisher(),
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
        library_gate=gate,
    )
    try:
        await manager.start()
        await asyncio.sleep(0)
        await asyncio.wait_for(manager.stop(), timeout=2)
        assert gate.blocker("sync") is None
        assert gate.blocker("downloads") == "full sync"
    finally:
        release()
        await manager.stop()


async def test_download_workers_reserve_gate_before_awaiting_a_claim(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    gate = LibraryGate()
    manager = _download_manager(
        RecordingPublisher(),
        provider=RefreshingProvider(),
        phash=PhashService(app_config=app_config),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
        library_gate=gate,
    )
    monkeypatch.setattr(manager, "process_job", AsyncMock())
    await manager.start()
    try:
        async with database.write_session() as session:
            session.add(MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie"))
            await session.flush()
            await manager.queue_job(
                session,
                JobTarget.art(1, ArtType.POSTER, "https://images.test/poster.jpg"),
            )
        await manager.committed(session)
        async with database.write_lock:
            await asyncio.sleep(0)
            assert gate.blocker("sync") == "downloads"
    finally:
        await manager.stop()
    assert gate.blocker("sync") is None
