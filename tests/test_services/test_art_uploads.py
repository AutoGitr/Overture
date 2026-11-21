"""Artwork uploaded from a browser: kept, selected, written and retained."""

lazy from datetime import timedelta
lazy from io import BytesIO
lazy from pathlib import Path

lazy import pytest
lazy from PIL import Image
lazy from sqlmodel import select

lazy from overture.config import Settings
lazy from overture.db.ledger import find_asset, select_upload
lazy from overture.db.models.asset import Asset
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtGeneration,
    ArtSource,
    ArtStyle,
    ArtType,
    AssetStatus,
    JobType,
    MediaType,
    ServerAsset,
)
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.schemas.art import SaveArtRequest
lazy from overture.schemas.library import media_item_read_from_model
lazy from overture.schemas.removal import AssetRemoval
lazy from overture.services import retention
lazy from overture.services.art.candidates import ArtCandidates
lazy from overture.services.art.matcher import ArtMatcher
lazy from overture.services.art.phash import PhashService
lazy from overture.services.art.service import ArtService
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.removal import AssetRemover
lazy from overture.services.retention import prune_image_cache
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.storage.image_cache import ImageCache
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.time import utc_now
lazy from tests.factories import file_hash_of, seed_asset
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    art_service,
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
    return art_service(
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
        remover=AssetRemover(
            asset_storage=AssetStorage(app_config=app_config),
            provider_registry=registry,
            database=database,
        ),
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


async def _slot(database: Database, item_id: int) -> Asset | None:
    async with database.read_session() as session:
        item = await session.get(MediaItem, item_id)
        assert item is not None
        return find_asset(item, ServerAsset.POSTER)


async def test_an_upload_must_be_a_jpeg_or_png(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    service = _service(
        ImageCache(tmp_path / "images", tmp_path / "uploads"),
        app_config=app_config,
        database=database,
    )

    with pytest.raises(PublicServiceError) as refused:
        await service.uploads.store(b"GIF89a not an image")
    kept = await service.uploads.store(_poster())

    assert refused.value.status_code == 415
    assert (kept.width, kept.height) == (200, 300)
    cache = ImageCache(tmp_path / "images", tmp_path / "uploads")
    assert cache.has_original(kept.upload_hash)
    assert cache.has_thumb(kept.upload_hash)


async def test_an_upload_is_selected_then_written_beside_the_media(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    folder = tmp_path / "Alien (1979)"
    folder.mkdir()
    cache = ImageCache(tmp_path / "images", tmp_path / "uploads")
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
    assert (slot.url, slot.upload_hash, file_hash_of(slot)) == (
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
    assert file_hash_of(slot) == upload.upload_hash
    assert (folder / "poster.png").read_bytes() == _poster()
    async with database.read_session() as session:
        item = await session.get(MediaItem, item_id)
        assert item is not None
        read = media_item_read_from_model(item, seasons=[])
    assert (
        read.assets.poster.status,
        read.assets.poster.source,
    ) == (
        AssetStatus.COMPLETE,
        ArtSource.UPLOAD,
    )


async def test_an_item_without_a_folder_keeps_its_upload_as_its_file(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    service = _service(
        ImageCache(tmp_path / "images", tmp_path / "uploads"),
        app_config=app_config,
        database=database,
    )
    item_id = await _item(database, None)
    upload = await service.uploads.store(_poster())

    response = await service.save(
        item_id, ArtType.POSTER, SaveArtRequest(upload_hash=upload.upload_hash)
    )

    assert response.selection.job_id is None
    assert response.item.assets.poster.content_hash == upload.upload_hash
    assert response.item.assets.poster.status is AssetStatus.COMPLETE
    await service.remove(item_id, ArtType.POSTER, AssetRemoval())
    removed = await _slot(database, item_id)
    assert removed is not None
    assert removed.status is AssetStatus.MISSING


async def test_an_upload_the_cache_no_longer_keeps_is_refused(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    service = _service(
        ImageCache(tmp_path / "images", tmp_path / "uploads"),
        app_config=app_config,
        database=database,
    )
    item_id = await _item(database, None)

    with pytest.raises(PublicServiceError) as refused:
        await service.save(
            item_id, ArtType.POSTER, SaveArtRequest(upload_hash="d" * 64)
        )

    assert refused.value.status_code == 409


async def test_retention_never_deletes_an_upload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    # Every cached file is old enough to go unless something names it.
    monkeypatch.setattr(retention, "UNUSED_IMAGE_RETENTION", timedelta(days=-1))
    cache = ImageCache(tmp_path / "cache", tmp_path / "uploads")
    service = _service(cache, app_config=app_config, database=database)
    unselected = await service.uploads.store(_poster("red"))
    stray = await cache.store_original(_poster("green"))
    interrupted = tmp_path / "uploads" / ".staging" / ".write.tmp"
    interrupted.parent.mkdir(parents=True, exist_ok=True)
    interrupted.write_bytes(b"half")

    await prune_image_cache(database=database, image_cache=cache)

    assert cache.has_original(unselected.upload_hash)
    assert not cache.has_original(stray.file_hash)
    assert not interrupted.exists()


async def test_uploads_in_the_cache_move_to_the_uploads_folder(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    # Overture 0.3 kept the cache, uploads included, in cache/images.
    legacy = ImageCache(tmp_path / "cache" / "images", tmp_path / "unused")
    selected = await legacy.store_original(_poster("red"))
    queued = await legacy.store_original(_poster("blue"))
    generated = await legacy.store_original(_poster("green"))
    await legacy.thumb(generated)
    item_id = await _item(database, None)
    async with database.write_session() as session:
        item = await session.get(MediaItem, item_id)
        assert item is not None
        seed_asset(item, ArtType.POSTER, upload_hash=selected.file_hash)
        select_upload(
            item,
            ServerAsset.BACKGROUND,
            generated.file_hash,
            generated=ArtGeneration(ArtStyle.DARK, title_only=False),
        )
        session.add(item)
        session.add(
            DownloadJob(
                media_item_id=item_id,
                job_type=JobType.ART,
                art_type=ArtType.BACKGROUND,
                upload_hash=queued.file_hash,
                created_at=utc_now(),
            )
        )
    cache = ImageCache(tmp_path / "cache", tmp_path / "uploads")
    service = _service(cache, app_config=app_config, database=database)

    await service.uploads.adopt_from_cache()
    await service.uploads.adopt_from_cache()

    for upload in (selected, queued):
        original = await cache.original(upload.file_hash)
        assert original is not None
        assert original.path.is_relative_to(tmp_path / "uploads")
    # Generated art can be drawn again, so it stays in the cache.
    original = await cache.original(generated.file_hash)
    assert original is not None
    assert original.path.is_relative_to(tmp_path / "cache" / "originals")
    assert cache.has_thumb(generated.file_hash)
    assert not (tmp_path / "cache" / "images").exists()


async def test_an_upload_a_crash_left_damaged_is_written_again_before_its_copy_goes(
    tmp_path: Path,
) -> None:
    legacy = ImageCache(tmp_path / "cache" / "images", tmp_path / "unused")
    kept = await legacy.store_original(_poster("red"))
    cache = ImageCache(tmp_path / "cache", tmp_path / "uploads")
    upload = (
        tmp_path
        / "uploads"
        / kept.file_hash[:2]
        / f"{kept.file_hash}{kept.path.suffix}"
    )
    upload.parent.mkdir(parents=True)
    upload.write_bytes(b"")

    assert await cache.adopt_uploads([kept.file_hash]) == 1

    assert upload.read_bytes() == _poster("red")
    assert not (tmp_path / "cache" / "images").exists()


async def test_a_cached_upload_that_lost_its_bytes_is_left_where_it_is(
    tmp_path: Path,
) -> None:
    cache = ImageCache(tmp_path / "cache", tmp_path / "uploads")
    kept = await cache.store_original(_poster("red"))
    kept.path.write_bytes(b"damaged")

    assert await cache.adopt_uploads([kept.file_hash]) == 0

    assert kept.path.read_bytes() == b"damaged"
    assert not (tmp_path / "uploads").exists() or not any(
        (tmp_path / "uploads").rglob("*.jpg")
    )


async def test_storing_an_upload_again_repairs_a_damaged_copy(tmp_path: Path) -> None:
    cache = ImageCache(tmp_path / "cache", tmp_path / "uploads")
    stored = await cache.store_upload(_poster("red"))
    stored.path.write_bytes(b"")

    again = await cache.store_upload(_poster("red"))

    assert again.path.read_bytes() == _poster("red")
