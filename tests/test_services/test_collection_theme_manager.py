"""Collection theme download queue and processing tests."""

lazy from typing import Any, cast, override

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.session import Database
lazy from overture.domain import MediaType, ServerType
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.repositories.collection_themes import CollectionThemeRepository
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


async def test_enqueue_refuses_a_second_upload_to_the_same_collection(
    *, app_config: Settings, database: Database
) -> None:
    service = _download_service(app_config=app_config, database=database)

    async with database.write_session() as session:
        _job_id, created = await service.queue_job(
            session,
            JobTarget.collection_theme(
                "1", MediaType.MOVIE, "Collection", "abcDEF123_4"
            ),
        )

        assert created is True
        assert await service.snapshot_events() == []

        with pytest.raises(RuntimeError, match="already running"):
            await service.queue_job(
                session,
                JobTarget.collection_theme(
                    "1", MediaType.MOVIE, "Collection", "different_youtube_id"
                ),
            )


async def test_process_job_broadcasts_failed_payload_on_download_error(
    *, app_config: Settings, database: Database
) -> None:
    class FailingYoutubeResolver:
        async def download_audio(self, *_args: object, **_kwargs: object) -> ThemeAudio:
            raise DownloadError("api_key=secret")

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
            JobTarget.collection_theme(
                "collection-1", MediaType.MOVIE, "Collection", "abcDEF123_4"
            ),
        )
    await service.process_job(job_id)

    assert [event for event, _ in publisher.events] == [
        "download.started",
        "download.failed",
    ]


@pytest.mark.parametrize("upload_fails", [False, True])
async def test_process_job_persists_complete_collection_theme_provenance(
    db_session: AsyncSession,
    *,
    app_config: Settings,
    database: Database,
    upload_fails: bool,
) -> None:
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
            return ThemeAudio(audio_bytes=b"mp3", title="YouTube Theme", duration=123)

    class Provider:
        server_type = ServerType.PLEX

        async def upload_collection_theme(self, _server_id: str, _audio: bytes) -> str:
            if upload_fails:
                raise MediaServerError("Plex rejected the collection theme upload")
            return "/themes/uploaded"

    publisher = RecordingPublisher()
    service = _download_service(
        publisher,
        youtube_resolver=cast("Any", Resolver()),
        provider=Provider(),
        database=database,
        app_config=app_config,
    )
    async with database.write_session() as session:
        job_id, _ = await service.queue_job(
            session,
            JobTarget.collection_theme(
                "collection-1", MediaType.MOVIE, "Collection", "VENZKx1iFzA"
            ),
        )
    await service.process_job(job_id)

    row = await CollectionThemeRepository(db_session).get_for_collection(
        "collection-1", MediaType.MOVIE
    )
    if upload_fails:
        assert row is None
        job = await db_session.get(DownloadJob, job_id)
        assert job is not None
        assert job.error_message == "Plex rejected the collection theme upload"
        assert publisher.events[-1][0] == "download.failed"
        return
    assert row is not None
    assert row.youtube_id == "VENZKx1iFzA"
    assert row.youtube_title == "YouTube Theme"
    assert row.youtube_duration == 123
    assert row.server_theme_id == "/themes/uploaded"
    assert publisher.events[-2] == (
        "collection.theme.updated",
        {
            "server_id": "collection-1",
            "media_type": "movie",
            "has_theme": True,
            "youtube_id": "VENZKx1iFzA",
            "youtube_title": "YouTube Theme",
            "youtube_duration": 123,
            "theme_status": "complete",
        },
    )
