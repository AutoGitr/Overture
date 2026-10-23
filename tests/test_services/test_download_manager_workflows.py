"""Download manager job and payload workflow tests."""

lazy import asyncio
lazy from datetime import UTC, datetime
lazy from io import BytesIO
lazy from pathlib import Path
lazy from typing import Any, cast, override

lazy import pytest
lazy from PIL import Image
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import ArtFileFacts, read_art_slot, record_art_file
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import (
    ACTIVE_JOB_STATUSES,
    ArtType,
    JobStatus,
    JobType,
    MediaType,
    ServerType,
)
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.jobs.kinds import INTERRUPTED_MESSAGE, DownloadStatus
lazy from overture.schemas.library import BulkItemOperation
lazy from overture.services.art.phash import PhashService
lazy from overture.services.downloads.events import DownloadEventPublisher, job_target
lazy from overture.services.downloads.queue import AssetScope, JobTarget
lazy from overture.services.downloads.results import (
    DownloadedArt,
    DownloadedTheme,
    PreparedDownload,
)
lazy from overture.services.downloads.service import DownloadService
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
    make_runtime,
    unused,
)


def _image_bytes(fmt: str, color: str = "red") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (2, 2), color=color).save(buffer, format=fmt)
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

    first_id, first_created = await service.queue_job(db_session, target)
    if first_created:
        queued.append(first_id)
    second_id, second_created = await service.queue_job(db_session, target)
    if second_created:
        queued.append(second_id)
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
        db_session, JobTarget.theme(1, "abcDEF123_4")
    )
    if created:
        queued.append(new_id)
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
    started: list[JobType] = []
    kinds: dict[str, JobType] = {}
    holding = asyncio.Event()
    two_started = asyncio.Event()

    async def fake_process(job_id: str) -> None:
        kind = kinds[job_id]
        started.append(kind)
        if len(started) >= 2:
            two_started.set()
        if kind is JobType.THEME:
            await holding.wait()

    monkeypatch.setattr(manager, "process_job", fake_process)
    await manager.start()
    try:
        async with database.write_session() as session:
            session.add(MediaItem(id=1, title="Movie", media_type=MediaType.MOVIE))
            await session.flush()
            for target in (
                JobTarget.theme(1, "abcDEF123_4"),
                JobTarget.theme(1, "defABC456_7"),
                JobTarget.art(1, ArtType.POSTER, "https://images.test/poster.jpg"),
            ):
                job_id, _ = await manager.queue_job(session, target)
                kinds[job_id] = target.job_type
        await manager.committed(session)
        async with asyncio.timeout(5):
            await two_started.wait()
    finally:
        await manager.stop()
        holding.set()

    # The art job ran while the first theme was still going and the second
    # was still queued behind it.
    assert sorted(started) == [JobType.ART, JobType.THEME]


async def test_two_selections_completing_in_reverse_order_keeps_newest_choice(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
    tmp_path: Path,
) -> None:
    publisher = RecordingPublisher()
    service = _download_service(publisher, app_config=app_config, database=database)
    folder = tmp_path / "Alien"
    folder.mkdir(parents=True)
    urls = {"red": "https://images.test/a.jpg", "blue": "https://images.test/b.jpg"}
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=1, media_type=MediaType.MOVIE, title="Alien", folder_path=str(folder)
            )
        )
        await session.flush()
        job_id_a, _ = await service.queue_job(
            session, JobTarget.art(1, ArtType.POSTER, urls["red"])
        )

    a_downloading = asyncio.Event()
    a_can_finish = asyncio.Event()

    async def fake_download(
        job: DownloadJob, item: MediaItem, progress: Any
    ) -> PreparedDownload:
        color = "red" if job.id == job_id_a else "blue"
        if color == "red":
            a_downloading.set()
            await a_can_finish.wait()
        return PreparedDownload(
            target_path=str(folder / "poster.jpg"),
            trusted_root=str(tmp_path),
            data=_image_bytes("JPEG", color),
            result=DownloadedArt(ArtType.POSTER, None, urls[color], None, 2, 2),
        )

    monkeypatch.setattr(service.art_handler, "download", fake_download)

    with service.watch() as watch:
        watch.tracking("A")(job_id_a)
        task_a = asyncio.create_task(service.process_job(job_id_a))
        await a_downloading.wait()

        async with database.write_session() as session:
            job_id_b, created_b = await service.queue_job(
                session, JobTarget.art(1, ArtType.POSTER, urls["blue"])
            )
        await service.committed(session)
        assert created_b is True
        watch.tracking("B")(job_id_b)

        await service.process_job(job_id_b)
        a_can_finish.set()
        await task_a
        watch.close()
        outcomes = {outcome.target: outcome async for outcome in watch.stream()}

    assert outcomes["A"].cancelled
    assert outcomes["B"].error is None
    assert (folder / "poster.jpg").read_bytes() == _image_bytes("JPEG", "blue")
    async with database.read_session() as session:
        item_row = await session.get(MediaItem, 1)
        assert item_row is not None
        assert read_art_slot(item_row, ArtType.POSTER).url == urls["blue"]
        statuses = {
            job.id: job.status for job in (await session.exec(select(DownloadJob)))
        }
    assert statuses == {job_id_a: JobStatus.CANCELLED, job_id_b: JobStatus.DONE}


async def test_clear_during_preparation_cancels_download_without_overwriting(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
    tmp_path: Path,
) -> None:
    service = _download_service(
        RecordingPublisher(), app_config=app_config, database=database
    )
    folder = tmp_path / "Alien"
    folder.mkdir(parents=True)
    async with database.write_session() as session:
        item = MediaItem(
            id=1,
            media_type=MediaType.MOVIE,
            title="Alien",
            folder_path=str(folder),
        )
        record_art_file(
            item,
            ArtType.POSTER,
            ArtFileFacts(
                file_hash="original_hash",
                phash=None,
                width=1000,
                height=1500,
                file_mtime_ns=1,
                file_size=10,
            ),
        )
        session.add(item)
        await session.flush()
        target = JobTarget.art(1, ArtType.POSTER, "https://images.test/poster_new.jpg")
        job_id, _ = await service.queue_job(session, target)

    downloading = asyncio.Event()
    can_finish = asyncio.Event()

    async def fake_download(
        job: DownloadJob, item: MediaItem, progress: Any
    ) -> PreparedDownload:
        downloading.set()
        await can_finish.wait()
        result = DownloadedArt(
            ArtType.POSTER, None, "https://images.test/poster_new.jpg", None, 1000, 1500
        )
        return PreparedDownload(
            target_path=str(folder / "poster.jpg"),
            trusted_root=str(tmp_path),
            data=_image_bytes("JPEG"),
            result=result,
        )

    monkeypatch.setattr(service.art_handler, "download", fake_download)

    task = asyncio.create_task(service.process_job(job_id))
    await downloading.wait()

    async with database.write_session() as session:
        await service.cancel_assets(
            session, AssetScope(1, job_type=JobType.ART, art_type=ArtType.POSTER)
        )
    await service.committed(session)

    can_finish.set()
    await task

    assert not (folder / "poster.jpg").exists()
    async with database.read_session() as session:
        item_row = await session.get(MediaItem, 1)
        assert item_row is not None
        slot = read_art_slot(item_row, ArtType.POSTER)
        assert (slot.url, slot.file_hash) == (None, "original_hash")
        job_row = await session.get(DownloadJob, job_id)
        assert job_row is not None
        assert job_row.status is JobStatus.CANCELLED


async def test_failed_transaction_queues_nothing_and_wakes_no_worker(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    service = _download_service(
        RecordingPublisher(), app_config=app_config, database=database
    )
    processed: list[str] = []

    async def process_job(job_id: str) -> None:
        processed.append(job_id)

    async def queue_in_savepoint_then_fail() -> None:
        async with database.write_session() as session:
            session.add(MediaItem(id=1, media_type=MediaType.MOVIE, title="Alien"))
            async with session.begin_nested():
                await service.queue_job(
                    session,
                    JobTarget.art(1, ArtType.POSTER, "https://images.test/poster.jpg"),
                )
            raise RuntimeError("Transaction rolled back")

    monkeypatch.setattr(service, "process_job", process_job)
    await service.start()
    try:
        with pytest.raises(RuntimeError, match="Transaction rolled back"):
            await queue_in_savepoint_then_fail()
        await asyncio.sleep(0)
    finally:
        await service.stop()

    assert processed == []
    async with database.read_session() as session:
        assert (await session.exec(select(DownloadJob))).all() == []


async def test_restart_cancels_pending_and_running_work_without_replay(
    *, app_config: Settings, database: Database
) -> None:
    publisher = RecordingPublisher()
    service = _download_service(publisher, app_config=app_config, database=database)

    async with database.write_session() as session:
        session.add(MediaItem(id=1, media_type=MediaType.MOVIE, title="Alien"))
        await session.flush()
        job_pending = DownloadJob(
            id="job-pending",
            media_item_id=1,
            job_type=JobType.ART,
            art_type=ArtType.POSTER,
            status=JobStatus.PENDING,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        job_running = DownloadJob(
            id="job-running",
            media_item_id=1,
            job_type=JobType.THEME,
            status=JobStatus.RUNNING,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
        session.add_all([job_pending, job_running])

    await service.start()
    try:
        async with database.read_session() as session:
            p_job = await session.get(DownloadJob, "job-pending")
            r_job = await session.get(DownloadJob, "job-running")
            assert p_job is not None
            assert p_job.status is JobStatus.CANCELLED
            assert p_job.error_message == INTERRUPTED_MESSAGE
            assert r_job is not None
            assert r_job.status is JobStatus.CANCELLED
            assert r_job.error_message == INTERRUPTED_MESSAGE

        cancelled_events = [
            (ev, payload)
            for ev, payload in publisher.events
            if ev == "download.cancelled"
        ]
        assert len(cancelled_events) == 2
    finally:
        await service.stop()


async def test_failed_transaction_does_not_cancel_superseded_job_or_emit_events(
    *, app_config: Settings, database: Database
) -> None:
    publisher = RecordingPublisher()
    service = _download_service(publisher, app_config=app_config, database=database)

    async with database.write_session() as session:
        session.add(MediaItem(id=1, media_type=MediaType.MOVIE, title="Alien"))
        await session.flush()
        target_a = JobTarget.art(1, ArtType.POSTER, "https://images.test/poster_a.jpg")
        job_id_a, _ = await service.queue_job(session, target_a)
    await service.committed(session)

    async def failing_transaction() -> None:
        async with database.write_session() as session:
            target_b = JobTarget.art(
                1, ArtType.POSTER, "https://images.test/poster_b.jpg"
            )
            await service.queue_job(session, target_b)
            raise RuntimeError("Transaction aborted")

    with pytest.raises(RuntimeError, match="Transaction aborted"):
        await failing_transaction()

    async with database.read_session() as session:
        job_a = await session.get(DownloadJob, job_id_a)
        assert job_a is not None
        assert job_a.status in ACTIVE_JOB_STATUSES

    await service.committed(session)
    assert [ev for ev, _ in publisher.events if ev == "download.cancelled"] == []


async def test_cancellation_never_subsequently_becomes_failure_or_completion(
    *, app_config: Settings, database: Database
) -> None:
    publisher = RecordingPublisher()
    service = _download_service(publisher, app_config=app_config, database=database)

    async with database.write_session() as session:
        item = MediaItem(id=1, media_type=MediaType.MOVIE, title="Alien")
        session.add(item)
        job = DownloadJob(
            id="cancelled-job",
            media_item_id=1,
            job_type=JobType.ART,
            art_type=ArtType.POSTER,
            status=JobStatus.CANCELLED,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
            completed_at=datetime(2026, 1, 1, tzinfo=UTC),
            error_message="cancelled by user",
        )
        session.add(job)

    with service.watch() as watch:
        track = watch.tracking("Alien")
        track("cancelled-job")
        await service.fail_job(job, RuntimeError("Simulated failure"), title="Alien")

    async with database.read_session() as session:
        stored = await session.get(DownloadJob, "cancelled-job")
        assert stored is not None
        assert stored.status is JobStatus.CANCELLED
        assert stored.error_message == "cancelled by user"

    failed_events = [ev for ev, _ in publisher.events if ev == "download.failed"]
    assert len(failed_events) == 0
    assert watch.active_job_ids == ["cancelled-job"]


@pytest.mark.parametrize("cancelled", [False, True])
async def test_identical_file_completes_unchanged_unless_cancelled(
    monkeypatch: pytest.MonkeyPatch,
    *,
    cancelled: bool,
    app_config: Settings,
    database: Database,
    tmp_path: Path,
) -> None:
    publisher = RecordingPublisher()
    service = _download_service(publisher, app_config=app_config, database=database)
    folder = tmp_path / "Movie"
    folder.mkdir(parents=True)
    poster_path = folder / "poster.jpg"
    image_data = _image_bytes("JPEG")
    poster_path.write_bytes(image_data)

    async with database.write_session() as session:
        item = MediaItem(
            id=1, media_type=MediaType.MOVIE, title="Movie", folder_path=str(folder)
        )
        session.add(item)
        await session.flush()
        target = JobTarget.art(1, ArtType.POSTER, "https://images.test/poster.jpg")
        job_id, _ = await service.queue_job(session, target)

    async def fake_download(
        job: DownloadJob, item: MediaItem, progress: Any
    ) -> PreparedDownload:
        if cancelled:
            async with database.write_session() as session:
                await service.cancel_assets(session, AssetScope(1))
        return PreparedDownload(
            target_path=str(poster_path),
            trusted_root=str(tmp_path),
            data=image_data,
            result=DownloadedArt(
                ArtType.POSTER,
                None,
                "https://images.test/poster.jpg",
                None,
                100,
                150,
            ),
        )

    monkeypatch.setattr(service.art_handler, "download", fake_download)

    await service.process_job(job_id)

    async with database.read_session() as session:
        job_row = await session.get(DownloadJob, job_id)
        assert job_row is not None
        assert job_row.status is (JobStatus.CANCELLED if cancelled else JobStatus.DONE)
        item_row = await session.get(MediaItem, 1)
        assert item_row is not None
        assert read_art_slot(item_row, ArtType.POSTER).url == (
            None if cancelled else "https://images.test/poster.jpg"
        )

    completed_events = [
        payload for ev, payload in publisher.events if ev == "download.completed"
    ]
    if cancelled:
        assert completed_events == []
    else:
        (raw_payload,) = completed_events
        assert isinstance(raw_payload, dict)
        assert cast("dict[str, Any]", raw_payload)["unchanged"] is True


async def test_shutdown_during_local_commit_preserves_completion(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
    tmp_path: Path,
) -> None:
    publisher = RecordingPublisher()
    asset_storage = AssetStorage(app_config=app_config)
    service = make_download_service(
        publisher,
        provider_registry=NoopProviderRegistry(),
        asset_storage=asset_storage,
        phash=PhashService(app_config=app_config),
        image_clients=unused(ProxyClientManager),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config.model_copy(update={"ART_DOWNLOAD_WORKERS": 1}),
        database=database,
    )
    folder = tmp_path / "Movie"
    folder.mkdir(parents=True)
    commit_started = asyncio.Event()
    stop_requested = asyncio.Event()
    original_write = asset_storage.write_file_async

    async def slow_write(
        target_path: str, content: bytes, trusted_root: str
    ) -> StoredFile:
        commit_started.set()
        await stop_requested.wait()
        return await original_write(target_path, content, trusted_root)

    async def fake_download(
        job: DownloadJob, item: MediaItem, progress: Any
    ) -> PreparedDownload:
        return PreparedDownload(
            target_path=str(folder / "poster.jpg"),
            trusted_root=str(tmp_path),
            data=_image_bytes("JPEG"),
            result=DownloadedArt(
                ArtType.POSTER, None, "https://images.test/poster.jpg", None, 2, 2
            ),
        )

    monkeypatch.setattr(asset_storage, "write_file_async", slow_write)
    monkeypatch.setattr(service.art_handler, "download", fake_download)
    await service.start()
    with service.watch() as watch:
        async with database.write_session() as session:
            session.add(
                MediaItem(
                    id=1,
                    media_type=MediaType.MOVIE,
                    title="Movie",
                    folder_path=str(folder),
                )
            )
            await session.flush()
            job_id_committing, _ = await service.queue_job(
                session, JobTarget.art(1, ArtType.POSTER, "https://images.test/p.jpg")
            )
            job_id_queued, _ = await service.queue_job(
                session,
                JobTarget.art(1, ArtType.BACKGROUND, "https://images.test/b.jpg"),
            )
        watch.tracking("poster")(job_id_committing)
        watch.tracking("background")(job_id_queued)
        await service.committed(session)
        await commit_started.wait()

        stop_task = asyncio.create_task(service.stop())
        await asyncio.sleep(0)
        stop_requested.set()
        await stop_task
        watch.close()
        outcomes = {outcome.target: outcome async for outcome in watch.stream()}

    assert (folder / "poster.jpg").exists()
    async with database.read_session() as session:
        statuses = {
            job.id: job.status for job in (await session.exec(select(DownloadJob)))
        }
    assert statuses == {
        job_id_committing: JobStatus.DONE,
        job_id_queued: JobStatus.CANCELLED,
    }
    assert outcomes["poster"].error is None
    assert not outcomes["poster"].cancelled
    assert outcomes["background"].cancelled
    terminal = {
        cast("dict[str, Any]", payload)["job"]["id"]: event
        for event, payload in publisher.events
        if event in {"download.completed", "download.cancelled", "download.failed"}
    }
    assert terminal == {
        job_id_committing: "download.completed",
        job_id_queued: "download.cancelled",
    }


async def test_season_poster_isolation_and_bulk_clear(
    *, app_config: Settings, database: Database
) -> None:
    publisher = RecordingPublisher()
    service = _download_service(publisher, app_config=app_config, database=database)

    async with database.write_session() as session:
        show = MediaItem(id=1, media_type=MediaType.SHOW, title="Show")
        s1 = Season(id=10, media_item_id=1, season_num=1, title="Season 1")
        s2 = Season(id=20, media_item_id=1, season_num=2, title="Season 2")
        session.add_all([show, s1, s2])
        await session.flush()

        t_s1 = JobTarget.art(
            1, ArtType.SEASON_POSTER, "https://images.test/s1.jpg", season_id=10
        )
        t_s2 = JobTarget.art(
            1, ArtType.SEASON_POSTER, "https://images.test/s2.jpg", season_id=20
        )
        job1_id, _ = await service.queue_job(session, t_s1)
        job2_id, _ = await service.queue_job(session, t_s2)

    async with database.write_session() as session:
        t_s1_new = JobTarget.art(
            1,
            ArtType.SEASON_POSTER,
            "https://images.test/s1_new.jpg",
            season_id=10,
        )
        job1_new_id, created = await service.queue_job(session, t_s1_new)
        assert created is True

    await service.committed(session)

    async with database.read_session() as session:
        j1 = await session.get(DownloadJob, job1_id)
        j2 = await session.get(DownloadJob, job2_id)
        j1_new = await session.get(DownloadJob, job1_new_id)
        assert j1 is not None
        assert j1.status is JobStatus.CANCELLED
        assert j2 is not None
        assert j2.status in ACTIVE_JOB_STATUSES
        assert j1_new is not None
        assert j1_new.status in ACTIVE_JOB_STATUSES

    async with database.write_session() as session:
        await service.cancel_assets(
            session, AssetScope(1, job_type=JobType.ART, art_type=ArtType.SEASON_POSTER)
        )
    await service.committed(session)

    async with database.read_session() as session:
        j2 = await session.get(DownloadJob, job2_id)
        j1_new = await session.get(DownloadJob, job1_new_id)
        assert j2 is not None
        assert j2.status is JobStatus.CANCELLED
        assert j1_new is not None
        assert j1_new.status is JobStatus.CANCELLED


@pytest.mark.parametrize("operation", ["artwork", "themes"])
async def test_bulk_clear_cancels_only_targeted_downloads(
    tmp_path: Path, *, app_config: Settings, database: Database, operation: str
) -> None:
    publisher = RecordingPublisher()
    service = _download_service(publisher, app_config=app_config, database=database)
    runtime = make_runtime(
        config_dir=tmp_path,
        app_config=app_config,
        database=database,
        downloads=service,
        events=publisher,
    )
    async with database.write_session() as session:
        session.add_all(
            [
                MediaItem(id=1, title="First", media_type=MediaType.SHOW),
                MediaItem(id=2, title="Other", media_type=MediaType.SHOW),
            ]
        )
        await session.flush()
        session.add(Season(id=1, media_item_id=1, season_num=1))
        await session.flush()
        targets = [
            JobTarget.art(1, ArtType.POSTER, "poster"),
            JobTarget.art(1, ArtType.SEASON_POSTER, "season", season_id=1),
            JobTarget.theme(1, "theme"),
            JobTarget.theme(2, "other"),
        ]
        job_ids = [(await service.queue_job(session, target))[0] for target in targets]
    with service.watch() as watch:
        for job_id in job_ids:
            watch.tracking(job_id)(job_id)
        await runtime.library.bulk_operate_items(
            BulkItemOperation.model_validate({"item_ids": [1], "operation": operation})
        )
        expected = set(job_ids[:2] if operation == "artwork" else job_ids[2:3])
        assert set(watch.active_job_ids) == set(job_ids) - expected
        async with database.read_session() as session:
            jobs = (await session.exec(select(DownloadJob))).all()
            assert {
                job.id for job in jobs if job.status is JobStatus.CANCELLED
            } == expected
        assert sum(
            event == "download.cancelled" for event, _ in publisher.events
        ) == len(expected)


async def test_a_fill_without_supersede_keeps_the_pending_choice(
    db_session: AsyncSession, *, app_config: Settings, database: Database
) -> None:
    service = _download_service(
        RecordingPublisher(), app_config=app_config, database=database
    )
    db_session.add(MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie"))
    await db_session.flush()
    chosen_id, _ = await service.queue_job(
        db_session, JobTarget.art(1, ArtType.POSTER, "https://images.test/chosen.jpg")
    )

    fill_id, created = await service.queue_job(
        db_session,
        JobTarget.art(1, ArtType.POSTER, "https://images.test/catalog.jpg"),
        supersede=False,
    )
    await db_session.commit()

    assert (fill_id, created) == (chosen_id, False)
    jobs = (await db_session.exec(select(DownloadJob))).all()
    assert [(job.id, job.status) for job in jobs] == [(chosen_id, JobStatus.PENDING)]


async def test_a_new_collection_theme_supersedes_the_pending_upload(
    *, app_config: Settings, database: Database
) -> None:
    publisher = RecordingPublisher()
    service = _download_service(publisher, app_config=app_config, database=database)

    async with database.write_session() as session:
        session.add(
            MediaCollection(
                id=1,
                server_type=ServerType.PLEX,
                server_item_id="c1",
                media_type=MediaType.MOVIE,
            )
        )
    job_ids: list[str] = []
    for youtube_id in ("abcDEF123_4", "defABC456_7"):
        async with database.write_session() as session:
            job_id, created = await service.queue_job(
                session,
                JobTarget.collection_theme(1, "Saga", youtube_id),
            )
        await service.committed(session)
        assert created
        job_ids.append(job_id)

    async with database.read_session() as session:
        statuses = {
            job.id: job.status for job in (await session.exec(select(DownloadJob)))
        }
    assert statuses == {
        job_ids[0]: JobStatus.CANCELLED,
        job_ids[1]: JobStatus.PENDING,
    }
    assert [event for event, _ in publisher.events] == ["download.cancelled"]
