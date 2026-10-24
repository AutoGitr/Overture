"""Retention deletes what nothing reads any more, and nothing else."""

lazy import os
lazy from datetime import UTC, datetime, timedelta
lazy from io import BytesIO
lazy from pathlib import Path

lazy import pytest
lazy from PIL import Image
lazy from sqlmodel import select, text
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.art_slots import write_art_slot
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, JobStatus, JobType, MediaType
lazy from overture.services import retention
lazy from overture.services.storage.image_cache import ImageCache

NOW = datetime(2026, 8, 1, tzinfo=UTC)


@pytest.fixture(autouse=True)
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> None:
    """Freeze the clock retention prunes against."""

    def fixed_now() -> datetime:
        return NOW

    monkeypatch.setattr(retention, "utc_now", fixed_now)


_TABLE_COUNT_QUERIES = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "media_items": text("select count(*) from media_items"),
        "seasons": text("select count(*) from seasons"),
        "art_slots": text("select count(*) from art_slots"),
        "download_jobs": text("select count(*) from download_jobs"),
    }
)


async def _count(session: AsyncSession, table: str) -> int:
    conn = await session.connection()
    result = await conn.execute(_TABLE_COUNT_QUERIES[table])
    return result.scalar() or 0


async def test_finished_jobs_age_out_while_queued_ones_stay(
    db_session: AsyncSession,
) -> None:
    db_session.add(MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie"))
    await db_session.commit()

    stale = NOW - retention.FINISHED_JOB_RETENTION - timedelta(days=1)
    db_session.add_all(
        [
            DownloadJob(
                id="old-done",
                media_item_id=1,
                job_type=JobType.ART,
                status=JobStatus.DONE,
                created_at=stale,
                completed_at=stale,
            ),
            DownloadJob(
                id="old-pending",
                media_item_id=1,
                job_type=JobType.ART,
                status=JobStatus.PENDING,
                created_at=stale,
            ),
            DownloadJob(
                id="recent-failed",
                media_item_id=1,
                job_type=JobType.THEME,
                status=JobStatus.FAILED,
                created_at=stale,
                completed_at=NOW - timedelta(days=1),
            ),
        ]
    )
    await db_session.commit()

    result = await retention.prune(db_session)
    await db_session.commit()

    assert result.download_jobs == 1
    remaining = (
        await db_session.exec(select(DownloadJob.id).order_by(DownloadJob.id))
    ).all()
    assert list(remaining) == ["old-pending", "recent-failed"]


async def test_long_removed_items_are_deleted_with_everything_they_own(
    db_session: AsyncSession,
) -> None:
    stale = NOW - retention.REMOVED_ITEM_RETENTION - timedelta(days=1)
    removed = MediaItem(
        id=1, media_type=MediaType.SHOW, title="Gone", server_removed_at=stale
    )
    recently_removed = MediaItem(
        id=2,
        media_type=MediaType.SHOW,
        title="Recently Gone",
        server_removed_at=NOW - timedelta(days=1),
    )
    present = MediaItem(id=3, media_type=MediaType.MOVIE, title="Here")
    db_session.add_all([removed, recently_removed, present])
    await db_session.commit()

    season = Season(id=10, media_item_id=1, season_num=1, file_count=1)
    db_session.add(season)
    db_session.add(
        DownloadJob(
            id="job",
            media_item_id=1,
            job_type=JobType.ART,
            status=JobStatus.DONE,
            created_at=NOW,
        )
    )
    await db_session.commit()
    write_art_slot(removed, ArtType.POSTER, url="https://img.test/p.jpg")
    write_art_slot(season, ArtType.SEASON_POSTER, url="https://img.test/s.jpg")
    db_session.add_all([removed, season])
    await db_session.commit()

    result = await retention.prune(db_session)
    await db_session.commit()

    assert result.media_items == 1
    assert await _count(db_session, "media_items") == 2
    assert await _count(db_session, "seasons") == 0
    assert await _count(db_session, "art_slots") == 0
    assert await _count(db_session, "download_jobs") == 0


async def test_a_quiet_pass_reports_nothing_deleted(db_session: AsyncSession) -> None:
    result = await retention.prune(db_session)

    assert result.total == 0


def _jpeg_bytes(color: str) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (40, 60), color).save(buffer, "JPEG")
    return buffer.getvalue()


async def test_retention_pass_prunes_unreferenced_cached_images_after_grace_window(
    tmp_path: Path,
    database: Database,
) -> None:
    image_cache = ImageCache(tmp_path / "cache" / "images")
    referenced = await image_cache.store_original(_jpeg_bytes("red"))
    stale_unused = await image_cache.store_original(_jpeg_bytes("blue"))
    fresh_unused = await image_cache.store_original(_jpeg_bytes("green"))
    referenced_thumb = await image_cache.thumb(referenced)
    stale_thumb = await image_cache.thumb(stale_unused)

    stale_mtime = (
        NOW - retention.UNUSED_IMAGE_RETENTION - timedelta(hours=1)
    ).timestamp()
    for path in (
        referenced.path,
        referenced_thumb,
        stale_unused.path,
        stale_thumb,
    ):
        os.utime(path, (stale_mtime, stale_mtime))
    fresh_mtime = (NOW - timedelta(hours=1)).timestamp()
    os.utime(fresh_unused.path, (fresh_mtime, fresh_mtime))

    async with database.write_session() as session:
        movie = MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie")
        session.add(movie)
        await session.flush()
        write_art_slot(movie, ArtType.POSTER, file_hash=referenced.file_hash)
        session.add(movie)

    await retention.run_retention_pass(database=database, image_cache=image_cache)

    assert await image_cache.original(referenced.file_hash) == referenced
    assert referenced_thumb.is_file()
    assert await image_cache.original(fresh_unused.file_hash) == fresh_unused
    assert await image_cache.original(stale_unused.file_hash) is None
    assert not stale_thumb.exists()
    assert not stale_unused.path.parent.exists()
    assert not stale_thumb.parent.exists()
