"""Download manager job and payload workflow tests."""

lazy import asyncio
lazy from datetime import UTC, datetime
lazy from io import BytesIO
lazy from typing import Any, cast, override

lazy import pytest
lazy from PIL import Image
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, JobStatus, JobType, MediaType
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.jobs.kinds import DownloadStatus
lazy from overture.services.art.phash import PhashService
lazy from overture.services.downloads.events import DownloadEventPublisher, job_target
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.downloads.theme import DownloadedTheme
lazy from overture.services.storage.assets import AssetStorage, StoredFile
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.image import (
    UnsupportedImageFormatError,
    encoded_image_extension,
)
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    make_download_service,
    unused,
)


def _image_bytes(fmt: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), color="red").save(buffer, format=fmt)
    return buffer.getvalue()


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
    publisher: RecordingPublisher, *, app_config: Settings, database: Database
) -> DownloadService:
    return make_download_service(
        publisher,
        provider_registry=NoopProviderRegistry(),
        asset_storage=AssetStorage(app_config=app_config),
        phash=PhashService(app_config=app_config),
        image_clients=unused(ProxyClientManager),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
    )


@pytest.mark.parametrize("policy", ["off", "theme", "art_and_theme"])
async def test_download_completion_applies_monitoring_policy(
    db_session: AsyncSession,
    policy: str,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    service = _download_service(
        RecordingPublisher(), app_config=app_config, database=database
    )
    item = MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie")
    job = DownloadJob(
        id="theme-download",
        media_item_id=1,
        job_type=JobType.THEME,
        status=JobStatus.RUNNING,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db_session.add_all(
        [
            item,
            job,
            AppSettings.model_validate({"auto_unmonitor": policy}),
        ]
    )
    await db_session.commit()
    await service.record_job(
        job, DownloadedTheme("video", "Theme", 60), StoredFile("hash", 1, 5)
    )
    await db_session.refresh(item)
    assert item.theme_file_hash == "hash"
    assert item.monitored is (policy != "theme")
    assert job.status is JobStatus.DONE


async def test_queued_jobs_are_announced_after_commit_and_deduplicated(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    queued: list[str] = []
    service = _download_service(
        RecordingPublisher(), app_config=app_config, database=database
    )
    db_session.add(MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie"))
    await db_session.flush()
    target = JobTarget.art(1, ArtType.POSTER, "https://images.test/poster.jpg")

    first_id, first_created = await service.queue_job(
        db_session, target, on_queued=queued.append
    )
    second_id, second_created = await service.queue_job(
        db_session, target, on_queued=queued.append
    )
    # Nothing can run a job the caller's transaction has not committed.
    assert queued == []
    await db_session.commit()

    assert first_created is True
    assert second_created is False
    assert second_id == first_id
    assert queued == [first_id]


async def test_queue_download_job_ignores_completed_jobs(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    queued: list[str] = []
    service = _download_service(
        RecordingPublisher(), app_config=app_config, database=database
    )
    db_session.add(MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie"))
    await db_session.flush()
    existing = DownloadJob(
        media_item_id=1,
        job_type=JobType.THEME,
        target_url="abcDEF123_4",
        status=JobStatus.DONE,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    db_session.add(existing)
    await db_session.flush()

    new_id, created = await service.queue_job(
        db_session, JobTarget.theme(1, "abcDEF123_4"), on_queued=queued.append
    )
    await db_session.commit()

    assert created is True
    assert new_id != existing.id
    assert queued == [new_id]


async def test_queue_download_job_rejects_a_season_from_another_item(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    db_session.add_all(
        [
            MediaItem(id=1, media_type=MediaType.SHOW, title="Requested show"),
            MediaItem(id=2, media_type=MediaType.SHOW, title="Other show"),
            Season(id=10, media_item_id=2, season_num=1),
        ]
    )
    await db_session.flush()

    with pytest.raises(ValueError, match="does not belong"):
        await _download_service(
            RecordingPublisher(), app_config=app_config, database=database
        ).queue_job(
            db_session,
            JobTarget.art(
                1, ArtType.SEASON_POSTER, "https://images.test/season.jpg", season_id=10
            ),
        )


def test_encoded_image_extension_detects_jpeg_png_and_rejects_other_formats() -> None:
    assert encoded_image_extension(_image_bytes("JPEG")) == ".jpg"
    assert encoded_image_extension(_image_bytes("PNG")) == ".png"

    with pytest.raises(UnsupportedImageFormatError, match="Unsupported image format"):
        encoded_image_extension(_image_bytes("GIF"))


def test_job_target_has_stable_websocket_payload_shape() -> None:
    job = DownloadJob(
        media_item_id=7,
        job_type=JobType.ART,
        art_type=ArtType.SEASON_POSTER,
        season_id=3,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    assert job_target(job, "Firefly") == {
        "target_type": "item",
        "media_item_id": 7,
        "title": "Firefly",
        "season_id": 3,
        "art_type": "season_poster",
        "job_type": "art",
    }


async def test_progress_events_carry_the_job_and_its_stage() -> None:
    publisher = RecordingPublisher()
    job = DownloadJob(
        id="job-1",
        media_item_id=1,
        job_type=JobType.ART,
        art_type=ArtType.POSTER,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )

    await DownloadEventPublisher(publisher).publish(
        job, DownloadStatus.PROGRESS, title="Alien", percent=55, stage="writing"
    )

    assert publisher.events[0][0] == "download.progress"
    raw_payload = publisher.events[0][1]
    assert isinstance(raw_payload, dict)
    payload = cast("dict[str, Any]", raw_payload)
    raw_job = payload["job"]
    assert isinstance(raw_job, dict)
    job_payload = cast("dict[str, Any]", raw_job)
    assert job_payload["id"] == "job-1"
    assert payload["stage"] == "writing"


async def test_a_slow_theme_does_not_hold_up_the_artwork_behind_it(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    """Each job type has its own lane, so one long download blocks only its own."""
    manager = _download_service(
        RecordingPublisher(), app_config=app_config, database=database
    )
    started: list[str] = []
    holding = asyncio.Event()
    two_started = asyncio.Event()

    async def no_recovery() -> None:
        return

    async def fake_process(job_id: str) -> None:
        started.append(job_id)
        if len(started) >= 2:
            two_started.set()
        if job_id.startswith("theme"):
            await holding.wait()

    monkeypatch.setattr(manager, "_recover_jobs", no_recovery)
    monkeypatch.setattr(manager, "process_job", fake_process)

    async with database.write_session() as session:
        session.add(MediaItem(id=1, title="Movie", media_type=MediaType.MOVIE))
        await session.flush()
        for job_id, kind in (
            ("theme-1", JobType.THEME),
            ("theme-2", JobType.THEME),
            ("art-1", JobType.ART),
        ):
            session.add(
                DownloadJob(
                    id=job_id,
                    media_item_id=1,
                    job_type=kind,
                    created_at=datetime.now(UTC),
                )
            )
    # Workers claim the committed rows as soon as they start.
    await manager.start()
    try:
        async with asyncio.timeout(5):
            await two_started.wait()
    finally:
        await manager.stop()
        holding.set()

    # The art job ran while the first theme was still going and the second
    # was still queued behind it.
    assert sorted(started) == ["art-1", "theme-1"]
