"""Artwork uploaded from a browser: kept, selected, written and retained."""

lazy from datetime import timedelta
lazy from io import BytesIO
lazy from pathlib import Path

lazy import pytest
lazy from PIL import Image
lazy from sqlmodel import select

lazy from overture.config import Settings
lazy from overture.db.art_slots import find_art_slot
lazy from overture.db.models.art import ArtSlot
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import ArtSource, ArtType, AssetStatus, JobType, MediaType
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.schemas.art import SaveArtRequest
lazy from overture.schemas.library import media_item_read_from_model
lazy from overture.services import retention
lazy from overture.services.art.candidates import ArtCandidates
lazy from overture.services.art.matcher import ArtMatcher
lazy from overture.services.art.phash import PhashService
lazy from overture.services.art.service import ArtService
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.retention import prune_image_cache
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.storage.image_cache import ImageCache
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.time import utc_now
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    make_download_service,
    unused,
)


def _poster(color: str = "red") -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (200, 300), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _downloads(
    cache: ImageCache, *, app_config: Settings, database: Database
) -> DownloadService:
    return make_download_service(
        NullEventPublisher(),
        provider_registry=NoopProviderRegistry(),
        asset_storage=AssetStorage(app_config=app_config),
        phash=PhashService(app_config=app_config),
        image_clients=unused(ProxyClientManager),
        youtube_resolver=unused(YouTubeResolver),
        image_cache=cache,
        app_config=app_config,
        database=database,
    )


def _service(
    cache: ImageCache,
    *,
    app_config: Settings,
    database: Database,
    downloads: DownloadService | None = None,
) -> ArtService:
    registry = NoopProviderRegistry()
    return ArtService(
        app_config=app_config,
        database=database,
        asset_storage=AssetStorage(app_config=app_config),
        matcher=unused(ArtMatcher),
        phash=PhashService(app_config=app_config),
        downloads=downloads
        or _downloads(cache, app_config=app_config, database=database),
        publisher=NullEventPublisher(),
        provider_registry=registry,
        candidates=ArtCandidates(
            database=database,
            provider_registry=registry,
            tmdb_client=unused(TMDBClient),
            app_config=app_config,
        ),
        image_clients=unused(ProxyClientManager),
        image_cache=cache,
    )


async def _item(database: Database, folder: Path | None) -> int:
    async with database.write_session() as session:
        item = MediaItem(
            media_type=MediaType.MOVIE,
            title="Alien",
            folder_path=str(folder) if folder else None,
        )
        session.add(item)
        await session.flush()
        assert item.id is not None
        return item.id


async def _slot(database: Database, item_id: int) -> ArtSlot | None:
    async with database.read_session() as session:
        item = await session.get(MediaItem, item_id)
        assert item is not None
        return find_art_slot(item, ArtType.POSTER)


async def test_an_upload_must_be_a_jpeg_or_png(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    service = _service(
        ImageCache(tmp_path / "images"), app_config=app_config, database=database
    )

    with pytest.raises(PublicServiceError) as refused:
        await service.uploads.store(b"GIF89a not an image")
    kept = await service.uploads.store(_poster())

    assert refused.value.status_code == 415
    assert (kept.width, kept.height) == (200, 300)
    cache = ImageCache(tmp_path / "images")
    assert cache.has_original(kept.upload_hash)
    assert cache.has_thumb(kept.upload_hash)


async def test_an_upload_is_selected_then_written_beside_the_media(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    folder = tmp_path / "Alien (1979)"
    folder.mkdir()
    cache = ImageCache(tmp_path / "images")
    downloads = _downloads(cache, app_config=app_config, database=database)
    service = _service(
        cache, app_config=app_config, database=database, downloads=downloads
    )
    item_id = await _item(database, folder)
    upload = await service.uploads.store(_poster())

    response = await service.save(
        item_id, ArtType.POSTER, SaveArtRequest(upload_hash=upload.upload_hash)
    )

    slot = await _slot(database, item_id)
    assert slot is not None
    assert (slot.url, slot.upload_hash, slot.file_hash) == (
        None,
        upload.upload_hash,
        None,
    )
    async with database.read_session() as session:
        job = (await session.exec(select(DownloadJob))).one()
    assert (job.target_url, job.upload_hash) == (None, upload.upload_hash)
    assert response.selection.job_id == job.id

    await downloads.process_job(job.id)

    slot = await _slot(database, item_id)
    assert slot is not None
    assert slot.file_hash == upload.upload_hash
    assert (folder / "poster.png").read_bytes() == _poster()
    async with database.read_session() as session:
        item = await session.get(MediaItem, item_id)
        assert item is not None
        read = media_item_read_from_model(item, seasons=[])
    assert (read.poster_status, read.poster_source) == (
        AssetStatus.COMPLETE,
        ArtSource.UPLOAD,
    )


async def test_an_item_without_a_folder_keeps_its_upload_as_its_file(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    service = _service(
        ImageCache(tmp_path / "images"), app_config=app_config, database=database
    )
    item_id = await _item(database, None)
    upload = await service.uploads.store(_poster())

    response = await service.save(
        item_id, ArtType.POSTER, SaveArtRequest(upload_hash=upload.upload_hash)
    )

    assert response.selection.job_id is None
    assert response.item.poster_hash == upload.upload_hash
    assert response.item.poster_status is AssetStatus.COMPLETE
    await service.clear(item_id, ArtType.POSTER)
    assert await _slot(database, item_id) is None


async def test_an_upload_the_cache_no_longer_keeps_is_refused(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    service = _service(
        ImageCache(tmp_path / "images"), app_config=app_config, database=database
    )
    item_id = await _item(database, None)

    with pytest.raises(PublicServiceError) as refused:
        await service.save(
            item_id, ArtType.POSTER, SaveArtRequest(upload_hash="d" * 64)
        )

    assert refused.value.status_code == 409


async def test_retention_keeps_uploads_a_slot_or_queued_job_names(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    # Every cached file is old enough to go unless something names it.
    monkeypatch.setattr(retention, "UNUSED_IMAGE_RETENTION", timedelta(days=-1))
    cache = ImageCache(tmp_path / "images")
    selected = await cache.store_original(_poster("red"))
    queued = await cache.store_original(_poster("blue"))
    stray = await cache.store_original(_poster("green"))
    item_id = await _item(database, None)
    async with database.write_session() as session:
        session.add(
            ArtSlot(
                media_item_id=item_id,
                art_type=ArtType.POSTER,
                upload_hash=selected.file_hash,
            )
        )
        session.add(
            DownloadJob(
                media_item_id=item_id,
                job_type=JobType.ART,
                art_type=ArtType.BACKGROUND,
                upload_hash=queued.file_hash,
                created_at=utc_now(),
            )
        )

    removed = await prune_image_cache(database=database, image_cache=cache)

    assert removed == 1
    assert cache.has_original(selected.file_hash)
    assert cache.has_original(queued.file_hash)
    assert not cache.has_original(stray.file_hash)
