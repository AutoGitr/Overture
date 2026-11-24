"""Comparing local artwork files with the images a media server shows."""

lazy import io
lazy from collections.abc import AsyncIterator
lazy from concurrent.futures import ThreadPoolExecutor
lazy from pathlib import Path
lazy from typing import override

lazy import httpx2
lazy import pytest
lazy from PIL import Image

lazy from overture.config import Settings
lazy from overture.db.ledger import (
    ContentFacts,
    Destination,
    confirm_delivery,
    read_asset,
    record_content,
)
lazy from overture.db.models.library import Library
lazy from overture.db.models.media_collection import CollectionLibrary
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    AssetStatus,
    DeliveryChannel,
    ImageSize,
    MediaType,
    ServerAsset,
    ServerType,
)
lazy from overture.media_servers.adapters import ProviderImageRequest
lazy from overture.protocols import EventPublisher
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.schemas.server_audit import (
    AuditStatus,
    ServerAuditRequest,
    ServerAuditResult,
)
lazy from overture.services.art.candidates import ArtCandidates
lazy from overture.services.art.choice import ArtSelector
lazy from overture.services.art.collection_art import CollectionArtService
lazy from overture.services.art.matcher import ArtMatcher
lazy from overture.services.art.phash import PhashService
lazy from overture.services.art.uploads import ArtUploads
lazy from overture.services.downloads.theme import DownloadThemeHandler
lazy from overture.services.removal import AssetRemover
lazy from overture.services.server_audit.compare import AuditContext, audit_target
lazy from overture.services.server_audit.work import (
    AuditTarget,
    CollectionAuditTarget,
    plan_collection_audit,
)
lazy from overture.services.server_copies import ServerCopies
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.storage.image_cache import ImageCache
lazy from overture.utils.time import utc_now
lazy from tests.collection_helpers import shown_on_server, stored_collection
lazy from tests.factories import seed_asset
lazy from tests.http_mock import mock_client_factory
lazy from tests.media_servers import served_item
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    StaticImageClients,
    make_local_assets,
    make_server_copies,
    unused,
)

SERVER_URL = "http://plex.local:32400/library/metadata/s1/thumb/1"


def _jpeg(*, flipped: bool = False) -> bytes:
    """A gradient poster; flipped, it looks nothing like the original."""
    image = Image.linear_gradient("L").convert("RGB")
    if flipped:
        image = image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()


class ArtProvider:
    """A media server whose one item shows the poster at *url*."""

    def __init__(self, url: str | None) -> None:
        self.url = url

    async def find_item_id(self, item: MediaItem) -> str | None:
        return None

    def get_download_headers(self, url: str) -> dict[str, str]:
        return {"X-Plex-Token": "token"}


class ArtRegistry(NoopProviderRegistry):
    @override
    async def fetch_server_active_art_url(
        self, server_id: int, server_item_id: str, art_type: ArtType
    ) -> str | None:
        assert (server_id, server_item_id, art_type) == (1, "s1", ArtType.POSTER)
        return self.get(server_id).url


@pytest.fixture
async def phash(app_config: Settings) -> AsyncIterator[PhashService]:
    service = PhashService(app_config=app_config, executor=ThreadPoolExecutor(1))
    yield service
    await service.close()


async def _audit(
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
    phash: PhashService,
    local: bytes | None = None,
    server_url: str | None = SERVER_URL,
    served: httpx2.Response | None = None,
    server_item_id: str | None = "s1",
) -> tuple[ServerAuditResult, list[httpx2.Request]]:
    folder = tmp_path / "Alien (1979)"
    folder.mkdir()
    if local is not None:
        (folder / "poster.jpg").write_bytes(local)
    async with database.write_session() as session:
        session.add(
            served_item(
                id=1,
                media_type=MediaType.MOVIE,
                title="Alien",
                year=1979,
                folder_path=str(folder),
                server_item_id=server_item_id,
            )
        )
    factory, transport = mock_client_factory(
        lambda _request: served or httpx2.Response(404)
    )
    context = AuditContext(
        provider_registry=ArtRegistry(ArtProvider(server_url)),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        database=database,
        collection_art=unused(CollectionArtService),
        server_copies=make_server_copies(
            app_config=app_config,
            image_clients=StaticImageClients(factory()),
            config_dir=tmp_path / "config",
            phash=phash,
        ),
        theme_handler=unused(DownloadThemeHandler),
        publisher=NullEventPublisher(),
    )
    _, [result] = await audit_target(AuditTarget(1, ArtType.POSTER), context=context)
    return result, transport.requests


def _image(data: bytes) -> httpx2.Response:
    return httpx2.Response(200, content=data, headers={"Content-Type": "image/jpeg"})


async def test_the_same_image_on_the_server_is_a_visual_match(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    result, requests = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        phash=phash,
        local=_jpeg(),
        served=_image(_jpeg()),
    )

    assert (result.status, result.reason, result.hamming) == (
        AuditStatus.PHASH_MATCH,
        "d=0 visual match",
        0,
    )
    assert result.title == "Alien"
    assert result.server_image_present
    assert result.local_path == str(tmp_path / "Alien (1979)" / "poster.jpg")
    assert [request.headers["X-Plex-Token"] for request in requests] == ["token"]


async def test_a_different_image_on_the_server_reports_its_distance(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    result, _ = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        phash=phash,
        local=_jpeg(),
        served=_image(_jpeg(flipped=True)),
    )

    assert result.status is AuditStatus.PHASH_MISMATCH
    assert result.hamming is not None
    assert result.hamming > 0
    assert result.reason == f"d={result.hamming}"


@pytest.mark.parametrize(
    ("has_local", "server_item_id", "server_url", "status", "reason"),
    [
        (
            False,
            "s1",
            SERVER_URL,
            AuditStatus.LOCAL_MISSING,
            "Local art file is missing",
        ),
        (
            True,
            None,
            SERVER_URL,
            AuditStatus.UNRESOLVED_SERVER_ID,
            "Could not resolve media-server item ID",
        ),
        (
            True,
            "s1",
            None,
            AuditStatus.SERVER_MISSING,
            "Plex has no poster for it",
        ),
    ],
)
async def test_an_image_that_cannot_be_compared_says_why(
    tmp_path: Path,
    has_local: bool,
    server_item_id: str | None,
    server_url: str | None,
    status: AuditStatus,
    reason: str,
    *,
    app_config: Settings,
    database: Database,
    phash: PhashService,
) -> None:
    result, requests = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        phash=phash,
        local=_jpeg() if has_local else None,
        server_item_id=server_item_id,
        server_url=server_url,
    )

    assert (result.status, result.reason) == (status, reason)
    assert requests == []


async def test_a_server_image_that_fails_to_download_is_an_error(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    result, _ = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        phash=phash,
        local=_jpeg(),
        served=httpx2.Response(503),
    )

    assert result.status is AuditStatus.ERROR
    assert result.reason
    assert result.server_image_present


async def test_an_item_gone_from_the_library_is_an_error(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    context = AuditContext(
        provider_registry=ArtRegistry(ArtProvider(SERVER_URL)),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        database=database,
        collection_art=unused(CollectionArtService),
        server_copies=make_server_copies(
            app_config=app_config,
            image_clients=StaticImageClients(),
            config_dir=tmp_path,
            phash=phash,
        ),
        theme_handler=unused(DownloadThemeHandler),
        publisher=NullEventPublisher(),
    )

    _, [result] = await audit_target(AuditTarget(404, ArtType.POSTER), context=context)

    assert (result.status, result.reason) == (AuditStatus.ERROR, "Item not found")


class CollectionProvider(ArtProvider):
    """A media server showing one collection's poster at *url*."""

    server_type = ServerType.PLEX

    async def get_collection_image_url(
        self, server_collection_id: str, art_type: ArtType
    ) -> str | None:
        assert server_collection_id == "box"
        return self.url

    async def build_collection_image_request(
        self,
        server_item_id: str,
        art_type: ArtType,
        size: ImageSize | None,
        *,
        current_url: str,
    ) -> ProviderImageRequest:
        return ProviderImageRequest(current_url, {"X-Plex-Token": "token"})


def _collection_art(
    tmp_path: Path,
    image_cache: ImageCache,
    *,
    app_config: Settings,
    database: Database,
    phash: PhashService,
    image_clients: StaticImageClients,
) -> CollectionArtService:
    """The collection art an audit compares, keeping its images in *image_cache*."""
    return CollectionArtService(
        app_config=app_config,
        database=database,
        asset_locks=AssetStorage(app_config=app_config).asset_locks,
        matcher=unused(ArtMatcher),
        phash=phash,
        publisher=unused(EventPublisher),
        provider_registry=NoopProviderRegistry(),
        candidates=unused(ArtCandidates),
        image_clients=image_clients,
        image_cache=image_cache,
        selector=unused(ArtSelector),
        uploads=ArtUploads(database=database, image_cache=image_cache, phash=phash),
        remover=unused(AssetRemover),
        server_copies=unused(ServerCopies),
    )


async def _audit_collection(
    tmp_path: Path,
    served: bytes,
    *,
    uploaded: bytes | None,
    app_config: Settings,
    database: Database,
    phash: PhashService,
    recorded_phash: bool = True,
) -> ServerAuditResult:
    image_cache = ImageCache(tmp_path / "cache", tmp_path / "uploads")
    kept = await image_cache.store_original(uploaded) if uploaded is not None else None
    async with database.write_session() as session:
        row = stored_collection(
            id=1,
            server_item_id="box",
            media_type=MediaType.MOVIE,
            title="Saga",
            last_synced_at=utc_now(),
        )
        # A sync placed the poster on the collection's one copy.
        shown_on_server(row)
        if uploaded is not None and kept is not None:
            fingerprint = (
                await phash.compute_from_bytes(uploaded) if recorded_phash else None
            )
            seed_asset(
                row,
                ServerAsset.POSTER,
                upload_hash=kept.file_hash,
                file_hash=kept.file_hash,
                fingerprint=fingerprint,
                width=256,
                height=256,
            )
        session.add(row)
    factory, _transport = mock_client_factory(lambda _request: _image(served))
    image_clients = StaticImageClients(factory())
    context = AuditContext(
        provider_registry=NoopProviderRegistry(CollectionProvider(SERVER_URL)),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        database=database,
        collection_art=_collection_art(
            tmp_path,
            image_cache,
            app_config=app_config,
            database=database,
            phash=phash,
            image_clients=image_clients,
        ),
        server_copies=make_server_copies(
            app_config=app_config,
            image_clients=image_clients,
            config_dir=tmp_path / "config",
            phash=phash,
        ),
        theme_handler=unused(DownloadThemeHandler),
        publisher=NullEventPublisher(),
    )
    planned = await plan_collection_audit(
        ServerAuditRequest(check_collections=True), database=database
    )
    assert planned == (
        [CollectionAuditTarget(1, ServerAsset.POSTER)] if uploaded is not None else []
    )
    _, [result] = await audit_target(
        CollectionAuditTarget(1, ServerAsset.POSTER), context=context
    )
    return result


@pytest.mark.parametrize(
    ("served", "status"),
    [
        (_jpeg(), AuditStatus.PHASH_MATCH),
        (_jpeg(flipped=True), AuditStatus.PHASH_MISMATCH),
    ],
)
async def test_a_collection_image_overture_uploaded_is_compared_with_the_servers(
    tmp_path: Path,
    served: bytes,
    status: AuditStatus,
    *,
    app_config: Settings,
    database: Database,
    phash: PhashService,
) -> None:
    result = await _audit_collection(
        tmp_path,
        served,
        uploaded=_jpeg(),
        app_config=app_config,
        database=database,
        phash=phash,
    )

    assert (result.collection_id, result.item_id, result.title) == (1, None, "Saga")
    assert result.status is status
    # What the audit found is recorded, as a sync records it.
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(1)
    assert row is not None
    [copy] = read_asset(row, ServerAsset.POSTER).deliveries
    assert copy.observed_hash == (
        read_asset(row, ServerAsset.POSTER).content_hash
        if status is AuditStatus.PHASH_MATCH
        else None
    )


async def test_a_collection_without_an_upload_has_nothing_to_compare(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    result = await _audit_collection(
        tmp_path,
        _jpeg(),
        uploaded=None,
        app_config=app_config,
        database=database,
        phash=phash,
    )

    assert result.status is AuditStatus.LOCAL_MISSING


async def test_a_collection_image_without_a_fingerprint_is_fingerprinted_from_its_copy(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    result = await _audit_collection(
        tmp_path,
        _jpeg(),
        uploaded=_jpeg(),
        app_config=app_config,
        database=database,
        phash=phash,
        recorded_phash=False,
    )

    assert result.status is AuditStatus.PHASH_MATCH
    async with database.read_session() as session:
        row = await CollectionRepository(session).get_listed(1)
    assert row is not None
    assert read_asset(
        row, ServerAsset.POSTER
    ).fingerprint == await phash.compute_from_bytes(_jpeg())


async def test_collection_audit_broadcasts_status_change_and_keeps_concurrent_upload(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    class RecordingPublisher(EventPublisher):
        def __init__(self) -> None:
            self.events: list[tuple[str, object]] = []

        @override
        async def broadcast(
            self, event: str, payload: object = None, *, before_publish: object = None
        ) -> None:
            self.events.append((event, payload))

        @override
        async def broadcast_built(self, builder: object) -> bool:
            return False

    image_cache = ImageCache(tmp_path / "cache", tmp_path / "uploads")
    uploaded = _jpeg()
    kept = await image_cache.store_original(uploaded)
    fingerprint = await phash.compute_from_bytes(uploaded)
    async with database.write_session() as session:
        row = stored_collection(
            id=1,
            server_item_id="box",
            media_type=MediaType.MOVIE,
            title="Saga",
            last_synced_at=utc_now(),
        )
        shown_on_server(row)
        seed_asset(
            row,
            ServerAsset.POSTER,
            upload_hash=kept.file_hash,
            file_hash=kept.file_hash,
            fingerprint=fingerprint,
            width=256,
            height=256,
        )
        session.add(row)

    publisher = RecordingPublisher()
    factory, _ = mock_client_factory(lambda _req: _image(_jpeg(flipped=True)))
    image_clients = StaticImageClients(factory())
    context = AuditContext(
        provider_registry=NoopProviderRegistry(CollectionProvider(SERVER_URL)),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        database=database,
        collection_art=_collection_art(
            tmp_path,
            image_cache,
            app_config=app_config,
            database=database,
            phash=phash,
            image_clients=image_clients,
        ),
        server_copies=make_server_copies(
            app_config=app_config,
            image_clients=image_clients,
            config_dir=tmp_path / "config",
            phash=phash,
        ),
        publisher=publisher,
        theme_handler=unused(DownloadThemeHandler),
    )

    _, [mismatch] = await audit_target(
        CollectionAuditTarget(1, ServerAsset.POSTER), context=context
    )
    assert mismatch.status is AuditStatus.PHASH_MISMATCH
    assert publisher.events == [
        ("collection.updated", {"collection_id": 1, "titles": False})
    ]
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(1)
        assert row is not None
        assert read_asset(row, ServerAsset.POSTER).status is AssetStatus.PARTIAL

    # Simulate an upload replacing the collection's art while audit reads the old copy.
    publisher.events.clear()

    class RacingProvider(CollectionProvider):
        @override
        async def get_collection_image_url(
            self, server_collection_id: str, art_type: ArtType
        ) -> str | None:
            async with database.write_session() as session:
                current = await CollectionRepository(session).get(1)
                assert current is not None
                record_content(
                    current,
                    ServerAsset.POSTER,
                    ContentFacts("newer-upload", fingerprint),
                )
                confirm_delivery(
                    current,
                    ServerAsset.POSTER,
                    Destination(1, "box", DeliveryChannel.UPLOAD),
                    ref="/thumb/new",
                )
                session.add(current)
            return None

    racing_context = AuditContext(
        provider_registry=NoopProviderRegistry(RacingProvider(SERVER_URL)),
        asset_storage=context.asset_storage,
        local_assets=context.local_assets,
        phash=phash,
        database=database,
        collection_art=context.collection_art,
        server_copies=context.server_copies,
        publisher=publisher,
        theme_handler=unused(DownloadThemeHandler),
    )
    await audit_target(
        CollectionAuditTarget(1, ServerAsset.POSTER), context=racing_context
    )
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(1)
        assert row is not None
        assert read_asset(row, ServerAsset.POSTER).status is AssetStatus.COMPLETE
    assert publisher.events == []


async def test_a_cross_library_collection_copy_is_audited_once(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> None:
    image_cache = ImageCache(tmp_path / "cache", tmp_path / "uploads")
    uploaded = _jpeg()
    kept = await image_cache.store_original(uploaded)
    fingerprint = await phash.compute_from_bytes(uploaded)
    async with database.write_session() as session:
        session.add(
            Library(
                id="1:films",
                media_type=MediaType.MOVIE,
                server_id=1,
                title="Films",
            )
        )
        await session.flush()
        row = stored_collection(
            id=1,
            server_item_id="box",
            library_id="1:movies",
            media_type=MediaType.MOVIE,
            title="Saga",
            last_synced_at=utc_now(),
        )
        row.libraries.append(
            CollectionLibrary(
                server_id=1,
                collection_id=0,
                library_id="1:films",
                media_type=MediaType.MOVIE,
                server_item_id="box",
            )
        )
        shown_on_server(row)
        seed_asset(
            row,
            ServerAsset.POSTER,
            upload_hash=kept.file_hash,
            file_hash=kept.file_hash,
            fingerprint=fingerprint,
            width=256,
            height=256,
        )
        session.add(row)
    factory, _ = mock_client_factory(lambda _req: _image(uploaded))
    image_clients = StaticImageClients(factory())
    context = AuditContext(
        provider_registry=NoopProviderRegistry(CollectionProvider(SERVER_URL)),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        database=database,
        collection_art=_collection_art(
            tmp_path,
            image_cache,
            app_config=app_config,
            database=database,
            phash=phash,
            image_clients=image_clients,
        ),
        server_copies=make_server_copies(
            app_config=app_config,
            image_clients=image_clients,
            config_dir=tmp_path / "config",
            phash=phash,
        ),
        theme_handler=unused(DownloadThemeHandler),
        publisher=NullEventPublisher(),
    )

    _, results = await audit_target(
        CollectionAuditTarget(1, ServerAsset.POSTER), context=context
    )

    assert len(results) == 1
    assert results[0].status is AuditStatus.PHASH_MATCH
