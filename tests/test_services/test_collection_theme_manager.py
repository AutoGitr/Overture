"""Collection theme download queue and processing tests."""

lazy from collections.abc import Collection
lazy from pathlib import Path
lazy from typing import Any, cast, override

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.ledger import missing_deliveries
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.session import Database
lazy from overture.domain import (
    AssetStatus,
    JobStatus,
    MediaType,
    ServerAsset,
    ServerType,
)
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from overture.media_servers.plex import PlexProvider
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.services.art.collection_art import CollectionArtService
lazy from overture.services.asset_runs.support import refresh_folder_themes
lazy from overture.services.downloads.art import DownloadArtHandler
lazy from overture.services.downloads.events import DownloadEventPublisher
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.downloads.theme import DownloadThemeHandler
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.themes.youtube_resolver import (
    DownloadError,
    ThemeAudio,
    YouTubeResolver,
)
lazy from overture.utils.time import utc_now
lazy from tests.collection_helpers import stored_collection
lazy from tests.factories import server_ref, theme_of
lazy from tests.media_servers import TEST_SERVER_ID, configure, server_of
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import NoopProviderRegistry, unused


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
        if before_publish is not None:
            before_publish(event, payload)
        self.events.append((event, payload))


def _download_service(
    publisher: RecordingPublisher | None = None,
    *,
    youtube_resolver: YouTubeResolver | None = None,
    provider: object | None = None,
    database: Database,
    app_config: Settings,
) -> DownloadService:
    pub = publisher or RecordingPublisher()
    events = DownloadEventPublisher(pub)
    return DownloadService(
        collection_art=unused(CollectionArtService),
        art_handler=unused(DownloadArtHandler),
        theme_handler=DownloadThemeHandler(
            asset_storage=unused(AssetStorage),
            youtube_resolver=youtube_resolver or unused(YouTubeResolver),
            database=database,
        ),
        provider_registry=NoopProviderRegistry(provider),
        events=events,
        publisher=pub,
        asset_storage=AssetStorage(app_config=app_config),
        app_config=app_config,
        database=database,
    )


async def test_enqueue_supersedes_a_previous_upload_to_the_same_collection(
    *, app_config: Settings, database: Database
) -> None:
    await _listed_collection(database)
    service = _download_service(app_config=app_config, database=database)

    async with database.write_session() as session:
        job1_id, created1 = await service.queue_job(
            session,
            JobTarget.collection_theme(1, "Collection", "abcDEF123_4"),
        )

        assert created1 is True
        assert await service.snapshot_events() == []

        job2_id, created2 = await service.queue_job(
            session,
            JobTarget.collection_theme(1, "Collection", "different_youtube_id"),
        )

        assert created2 is True
        assert job2_id != job1_id

    async with database.read_session() as session:
        job1 = await session.get(DownloadJob, job1_id)
        assert job1 is not None
        assert job1.status is JobStatus.CANCELLED


async def test_process_job_broadcasts_failed_payload_on_download_error(
    *, app_config: Settings, database: Database
) -> None:
    class FailingYoutubeResolver:
        async def download_audio(self, *_args: object, **_kwargs: object) -> ThemeAudio:
            raise DownloadError("api_key=secret")

    await _listed_collection(database)
    publisher = RecordingPublisher()
    service = _download_service(
        publisher,
        youtube_resolver=cast("Any", FailingYoutubeResolver()),
        database=database,
        app_config=app_config,
    )
    async with database.write_session() as session:
        job_id, _ = await service.queue_job(
            session,
            JobTarget.collection_theme(1, "Collection", "abcDEF123_4"),
        )
    await service.process_job(job_id)

    assert [event for event, _ in publisher.events] == [
        "download.started",
        "download.failed",
    ]


class Resolver:
    async def download_audio(
        self,
        youtube_id: str,
        min_duration: int = 30,
        max_duration: int = 300,
        progress_callback: object = None,
        *,
        normalize_loudness: bool = False,
    ) -> ThemeAudio:
        del youtube_id, min_duration, max_duration, progress_callback
        del normalize_loudness
        return ThemeAudio(
            audio_bytes=b"mp3",
            title="YouTube Theme",
            duration=123,
            fingerprint="collection-fp",
        )


async def _listed_collection(
    database: Database, server_path: str | None = None
) -> None:
    async with database.write_session() as session:
        session.add(
            stored_collection(
                server_item_id="collection-1",
                media_type=MediaType.MOVIE,
                title="Collection",
                server_path=server_path,
                last_synced_at=utc_now(),
            )
        )


@pytest.mark.parametrize("upload_fails", [False, True])
async def test_process_job_persists_complete_collection_theme_provenance(
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
    upload_fails: bool,
) -> None:
    class Provider(PlexProvider):
        @override
        async def upload_collection_theme(
            self, server_item_id: str, mp3_bytes: bytes
        ) -> str:
            if upload_fails:
                raise MediaServerError("Plex rejected the collection theme upload")
            return "/themes/uploaded"

    await _listed_collection(database)
    publisher = RecordingPublisher()
    service = _download_service(
        publisher,
        youtube_resolver=cast("Any", Resolver()),
        provider=Provider(
            server=server_of(app_config, Provider.server_type),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
        database=database,
        app_config=app_config,
    )
    async with database.write_session() as session:
        job_id, _ = await service.queue_job(
            session,
            JobTarget.collection_theme(1, "Collection", "VENZKx1iFzA"),
        )
    await service.process_job(job_id)

    row = await CollectionRepository(db_session).get(1)
    assert row is not None
    if upload_fails:
        assert theme_of(row).youtube_id is None
        job = await db_session.get(DownloadJob, job_id)
        assert job is not None
        assert job.error_message == "Plex rejected the collection theme upload"
        assert publisher.events[-1][0] == "download.failed"
        return
    assert theme_of(row).youtube_id == "VENZKx1iFzA"
    assert theme_of(row).youtube_title == "YouTube Theme"
    assert theme_of(row).youtube_duration == 123
    assert server_ref(row, ServerAsset.THEME) == "/themes/uploaded"
    assert theme_of(row).status is AssetStatus.COMPLETE
    assert publisher.events[-2] == (
        "collection.updated",
        {"collection_id": 1, "titles": False},
    )


async def test_jellyfin_collection_theme_is_written_to_the_boxset_folder(
    tmp_path: Path,
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    refreshed: list[str] = []

    class Provider(JellyfinProvider):
        @override
        async def refresh_item(
            self, item_id: str, *, unlock: Collection[ServerAsset]
        ) -> None:
            refreshed.append(item_id)

    folder = tmp_path / "Star Wars [boxset]"
    folder.mkdir()
    configure(app_config, collections_path=tmp_path)
    # Jellyfin names its own path for the folder; only the name carries over.
    await _listed_collection(database, "/config/data/collections/Star Wars [boxset]")
    service = _download_service(
        youtube_resolver=cast("Any", Resolver()),
        provider=Provider(
            server=server_of(app_config, Provider.server_type),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
        database=database,
        app_config=app_config,
    )
    async with database.write_session() as session:
        job_id, _ = await service.queue_job(
            session,
            JobTarget.collection_theme(1, "Collection", "VENZKx1iFzA"),
        )
    await service.process_job(job_id)

    assert (folder / "theme.mp3").read_bytes() == b"mp3"
    assert refreshed == ["collection-1"]
    row = await CollectionRepository(db_session).get(1)
    assert row is not None
    assert theme_of(row).youtube_id == "VENZKx1iFzA"
    stat = (folder / "theme.mp3").stat()
    assert server_ref(row, ServerAsset.THEME) is None
    [folder_copy] = theme_of(row).deliveries
    assert folder_copy.observed_hash == theme_of(row).content_hash is not None
    assert theme_of(row).fingerprint == "collection-fp"
    assert folder_copy.fingerprint == "collection-fp"
    assert (folder_copy.file_size, folder_copy.file_mtime_ns) == (
        stat.st_size,
        stat.st_mtime_ns,
    )


async def test_jellyfin_collection_theme_needs_the_collections_path(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    await _listed_collection(database, "/data/Star Wars [boxset]")
    service = _download_service(
        youtube_resolver=cast("Any", Resolver()),
        provider=JellyfinProvider(
            server=server_of(app_config, ServerType.JELLYFIN),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
        database=database,
        app_config=app_config,
    )
    async with database.write_session() as session:
        job_id, _ = await service.queue_job(
            session,
            JobTarget.collection_theme(1, "Collection", "VENZKx1iFzA"),
        )
    await service.process_job(job_id)

    job = await db_session.get(DownloadJob, job_id)
    assert job is not None
    assert job.error_message == (
        "Set MEDIA_SERVER_JELLYFIN_COLLECTIONS_PATH to store collection themes"
    )


async def test_a_jellyfin_folder_without_its_theme_file_is_found(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    class Provider(JellyfinProvider):
        @override
        async def refresh_item(
            self, item_id: str, *, unlock: Collection[ServerAsset]
        ) -> None:
            del item_id, unlock

    folder = tmp_path / "Star Wars [boxset]"
    folder.mkdir()
    configure(app_config, collections_path=tmp_path)
    await _listed_collection(database, "/config/data/collections/Star Wars [boxset]")
    publisher = RecordingPublisher()
    service = _download_service(
        publisher,
        youtube_resolver=cast("Any", Resolver()),
        provider=Provider(
            server=server_of(app_config, Provider.server_type),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
        database=database,
        app_config=app_config,
    )
    async with database.write_session() as session:
        job_id, _ = await service.queue_job(
            session, JobTarget.collection_theme(1, "Collection", "VENZKx1iFzA")
        )
    await service.process_job(job_id)

    async with database.read_session() as session:
        row = await CollectionRepository(session).get(1)
    assert row is not None
    assert not missing_deliveries(theme_of(row))

    publisher.events.clear()
    original_write_session = database.write_session

    def fail_write() -> Any:
        raise AssertionError("refresh_folder_themes must not open write_session")

    monkeypatch.setattr(database, "write_session", fail_write)
    unchanged = await refresh_folder_themes(row, downloads=service, database=database)
    assert not missing_deliveries(theme_of(unchanged))
    assert publisher.events == []

    monkeypatch.setattr(database, "write_session", original_write_session)
    (folder / "theme.mp3").unlink()
    refreshed = await refresh_folder_themes(row, downloads=service, database=database)
    assert missing_deliveries(theme_of(refreshed))
    assert publisher.events == [
        ("collection.updated", {"collection_id": 1, "titles": False})
    ]
