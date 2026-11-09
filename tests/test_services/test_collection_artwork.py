"""Collection artwork uses shared validation, storage, candidates, and matching."""

lazy from io import BytesIO
lazy from pathlib import Path
lazy from typing import override

lazy import httpx2
lazy import pytest
lazy from PIL import Image
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.db.art_slots import read_art_slot
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.public_dataset import PublicDatasetCollection
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtSource,
    ArtStyle,
    ArtType,
    CatalogMediaType,
    ImageSize,
    MediaType,
    ServerType,
    TmdbLanguageFilter,
)
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.media_servers.adapters import ProviderImageRequest
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.schemas.art import ArtCandidate, SaveArtRequest
lazy from overture.schemas.collections import collection_artwork
lazy from overture.services.art.candidates import (
    ArtCandidates,
    CandidatePolicy,
    CandidateSources,
)
lazy from overture.services.art.matcher import ArtMatcher, CandidateComparison
lazy from overture.services.art.phash import PhashService
lazy from overture.services.art.service import ArtService
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.storage.image_cache import ImageCache
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.generated_art import render_art
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_public_dataset
lazy from tests.collection_helpers import managing_rule, stored_collection
lazy from tests.runtime_helpers import NoopProviderRegistry, unused
lazy from tests.test_services.test_collection_management import Provider
lazy from tests.test_services.test_collections_service import FakePublisher

URL = "https://image.tmdb.org/t/p/original/collection.jpg"


class Hashes(PhashService):
    def __init__(self) -> None:
        pass

    @override
    async def compute_from_bytes(self, image_bytes: bytes) -> str:
        return "a" * 64


class Matcher(ArtMatcher):
    def __init__(self) -> None:
        self.phash = Hashes()

    @override
    async def match_candidates(
        self,
        reference_phash: str,
        candidates: list[ArtCandidate],
        threshold: int = 0,
        reference_width: int = 0,
    ) -> CandidateComparison:
        assert reference_phash == "a" * 64
        assert threshold == 5
        return CandidateComparison(candidates, 0, len(candidates), 0)


class Candidates(ArtCandidates):
    def __init__(self) -> None:
        pass

    @override
    async def gather_collection(
        self, collection: MediaCollection, art_type: ArtType, policy: CandidatePolicy
    ) -> CandidateSources:
        return CandidateSources(
            {"tmdb": [ArtCandidate(url=URL, width=200, height=300)]}
        )


class Images(ProxyClientManager):
    def __init__(self, data: bytes) -> None:
        self.client = httpx2.AsyncClient(
            transport=httpx2.MockTransport(
                lambda _: httpx2.Response(
                    200, content=data, headers={"Content-Type": "image/jpeg"}
                )
            )
        )

    @override
    async def get_client(self, url: str | None = None) -> httpx2.AsyncClient:
        return self.client


class ArtProvider(Provider):
    def __init__(self, app_config: Settings) -> None:
        super().__init__(app_config)
        self.uploads: list[tuple[ArtType, bytes, str]] = []

    @override
    async def build_collection_image_request(
        self,
        server_item_id: str,
        art_type: ArtType,
        size: ImageSize | None,
        *,
        current_url: str,
    ) -> ProviderImageRequest:
        return ProviderImageRequest(URL, {})

    @override
    async def upload_collection_art(
        self,
        server_collection_id: str,
        art_type: ArtType,
        image_bytes: bytes,
        mime_type: str,
    ) -> None:
        assert server_collection_id == "box"
        self.uploads.append((art_type, image_bytes, mime_type))

    @override
    async def get_collection_image_url(
        self, server_collection_id: str, art_type: ArtType
    ) -> str | None:
        return f"https://plex.test/library/metadata/box/thumb/{len(self.uploads)}"


async def test_collection_art_upload_records_validated_bytes_and_shared_slot(
    tmp_path: Path,
    database: Database,
    app_config: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = BytesIO()
    Image.new("RGB", (200, 300), "red").save(data, format="JPEG")
    image_bytes = data.getvalue()
    images = Images(image_bytes)
    provider = ArtProvider(app_config)
    publisher = FakePublisher()

    async def public(_url: str) -> bool:
        return False

    monkeypatch.setattr("overture.services.art.choice.is_private_url", public)
    monkeypatch.setattr("overture.utils.image.is_private_url", public)
    async with database.write_session() as session:
        session.add(
            stored_collection(
                id=1,
                server_item_id="box",
                server_type=ServerType.PLEX,
                media_type=MediaType.MOVIE,
                title="Saga",
                tmdb_collection_id=10,
                last_synced_at=utc_now(),
            )
        )
        await session.flush()
        session.add(managing_rule(1))
    service = ArtService(
        app_config=app_config,
        database=database,
        asset_storage=AssetStorage(app_config=app_config),
        matcher=Matcher(),
        phash=unused(PhashService),
        downloads=unused(DownloadService),
        publisher=publisher,
        provider_registry=NoopProviderRegistry(provider),
        candidates=Candidates(),
        image_clients=images,
        image_cache=ImageCache(tmp_path / "images"),
    )
    try:
        sources = await service.collections.sources(1, ArtType.POSTER)
        assert sources.sources["tmdb"][0].url == URL
        await service.collections.save(
            1,
            ArtType.POSTER,
            SaveArtRequest(url=URL, width=200, height=300),
        )
        assert provider.uploads == [(ArtType.POSTER, image_bytes, "image/jpeg")]
        async with database.read_session() as session:
            row = await CollectionRepository(session).get(1)
            assert row is not None
            slot = read_art_slot(row, ArtType.POSTER)
            assert slot.url == URL
            assert slot.phash == "a" * 64
            assert (slot.width, slot.height, slot.file_size) == (
                200,
                300,
                len(image_bytes),
            )
            assert slot.collection_id == 1
            assert slot.media_item_id is None
            # The image route reads the path the server lists after the upload.
            assert row.thumb_url == "https://plex.test/library/metadata/box/thumb/1"
        assert publisher.broadcasts[-1] == ("collection.updated", {"collection_id": 1})
        # Client dimensions cannot disguise actual landscape bytes as a poster.
        with pytest.raises(PublicServiceError, match="aspect ratio"):
            await service.collections.save(
                1,
                ArtType.BACKGROUND,
                SaveArtRequest(url=URL, width=1920, height=1080),
            )
        assert len(provider.uploads) == 1
        result = await service.collections.match(1, ArtType.POSTER, 5)
        assert result.reference == "media_server"
        assert result.total_compared == 1
        state = await service.collections.clear(1, ArtType.POSTER)
        assert state.poster_url is None
        assert state.poster_status == "partial"
        async with database.read_session() as session:
            cleared = await CollectionRepository(session).get(1)
            assert cleared is not None
            assert cleared.thumb_url is not None
            assert read_art_slot(cleared, ArtType.POSTER).file_hash is not None
        assert len(provider.uploads) == 1
        with pytest.raises(PublicServiceError, match="posters and backgrounds"):
            await service.collections.sources(1, ArtType.SEASON_POSTER)
        with pytest.raises(PublicServiceError, match="Collection not found"):
            await service.collections.save(404, ArtType.POSTER, SaveArtRequest(url=URL))
    finally:
        await images.client.aclose()


async def test_an_uploaded_collection_image_is_shown_from_the_cache_and_sent_again(
    tmp_path: Path, database: Database, app_config: Settings
) -> None:
    data = BytesIO()
    Image.new("RGB", (200, 300), "blue").save(data, format="PNG")
    image_bytes = data.getvalue()
    provider = ArtProvider(app_config)
    async with database.write_session() as session:
        session.add(
            stored_collection(
                id=1,
                server_item_id="box",
                server_type=ServerType.PLEX,
                media_type=MediaType.MOVIE,
                title="Saga",
                last_synced_at=utc_now(),
            )
        )
        await session.flush()
        session.add(managing_rule(1))
    service = ArtService(
        app_config=app_config,
        database=database,
        asset_storage=AssetStorage(app_config=app_config),
        matcher=Matcher(),
        phash=PhashService(app_config=app_config),
        downloads=unused(DownloadService),
        publisher=FakePublisher(),
        provider_registry=NoopProviderRegistry(provider),
        candidates=Candidates(),
        image_clients=unused(ProxyClientManager),
        image_cache=ImageCache(tmp_path / "images"),
    )

    upload = await service.uploads.store(image_bytes)
    await service.collections.save(
        1, ArtType.POSTER, SaveArtRequest(upload_hash=upload.upload_hash)
    )

    assert provider.uploads == [(ArtType.POSTER, image_bytes, "image/png")]
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(1)
        assert row is not None
        artwork = collection_artwork(row)
    assert (artwork.poster_source, artwork.poster_hash) == (
        ArtSource.UPLOAD,
        upload.upload_hash,
    )
    assert artwork.poster_status == "complete"
    thumb = await service.collections.local_image(
        1, ArtType.POSTER, ImageSize.DISPLAY, upload.upload_hash
    )
    assert thumb.media_type == "image/avif"
    with pytest.raises(PublicServiceError, match="Collection image not found"):
        await service.collections.local_image(1, ArtType.BACKGROUND, None, None)

    await service.collections.reupload(1, ArtType.POSTER)
    assert provider.uploads[-1] == (ArtType.POSTER, image_bytes, "image/png")


async def test_collection_art_save_refuses_inactive_collection(
    database: Database, app_config: Settings, tmp_path: Path
) -> None:
    provider = ArtProvider(app_config)
    async with database.write_session() as session:
        session.add(
            stored_collection(
                id=2,
                server_item_id=None,
                server_type=ServerType.PLEX,
                media_type=MediaType.MOVIE,
                title="Inactive",
                last_synced_at=utc_now(),
            )
        )
        await session.flush()
        session.add(managing_rule(2))
    service = ArtService(
        app_config=app_config,
        database=database,
        asset_storage=AssetStorage(app_config=app_config),
        matcher=Matcher(),
        phash=PhashService(app_config=app_config),
        downloads=unused(DownloadService),
        publisher=FakePublisher(),
        provider_registry=NoopProviderRegistry(provider),
        candidates=Candidates(),
        image_clients=unused(ProxyClientManager),
        image_cache=ImageCache(tmp_path / "images"),
    )
    with pytest.raises(
        PublicServiceError, match="The collection is inactive and has no server copy"
    ):
        await service.collections.save(
            2, ArtType.POSTER, SaveArtRequest(generated=ArtStyle.DARK)
        )


async def test_collection_candidates_share_source_policy_and_catalog_toggle(
    database: Database, app_config: Settings
) -> None:
    class Tmdb(TMDBClient):
        def __init__(self) -> None:
            self.fail = False

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
            assert media_type is CatalogMediaType.COLLECTION
            assert tmdb_id == 10
            if self.fail:
                raise ValueError("TMDB unavailable")
            return [
                ArtCandidate(url=URL, width=200, height=300),
                ArtCandidate(
                    url="https://example.test/square.jpg", width=200, height=200
                ),
            ]

    class Server(ArtProvider):
        @override
        async def get_art_candidates(
            self, server_id: str, art_type: ArtType
        ) -> list[ArtCandidate]:
            return [ArtCandidate(url=URL, width=200, height=300)]

    app_config.TMDB_API_KEY = SecretStr("key")
    tmdb = Tmdb()
    candidates = ArtCandidates(
        database=database,
        provider_registry=NoopProviderRegistry(Server(app_config)),
        tmdb_client=tmdb,
        app_config=app_config,
    )
    row = stored_collection(
        id=1,
        server_item_id="box",
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        tmdb_collection_id=10,
    )
    policy = CandidatePolicy.of(AppSettings())
    disabled = await candidates.gather_collection(row, ArtType.POSTER, policy)
    assert [candidate.url for candidate in disabled.by_source["tmdb"]] == [URL]
    assert disabled.by_source["overturedb"] == []
    async with database.write_session() as session:
        session.add(PublicDatasetCollection(tmdb_id=10, title="Saga", poster_url=URL))
    async with database.write_session() as session:
        await enable_public_dataset(session)
    policy = CandidatePolicy.of(AppSettings(skip_media_server_tmdb_urls=True))
    enabled = await candidates.gather_collection(row, ArtType.POSTER, policy)
    assert enabled.by_source["overturedb"][0].url == URL
    assert enabled.by_source["plex"] == []
    tmdb.fail = True
    partial = await candidates.gather_collection(row, ArtType.POSTER, policy)
    assert partial.by_source["tmdb"] == []
    assert partial.by_source["overturedb"][0].url == URL
    assert len(partial.errors) == 1

    row.tmdb_collection_id = None
    assert (
        await candidates.gather_collection(row, ArtType.POSTER, policy)
        == CandidateSources()
    )


async def test_drawn_collection_art_is_offered_chosen_and_drawn_again_for_a_new_title(
    tmp_path: Path, database: Database, app_config: Settings
) -> None:
    provider = ArtProvider(app_config)
    async with database.write_session() as session:
        session.add(
            stored_collection(
                id=1,
                server_item_id="box",
                server_type=ServerType.PLEX,
                media_type=MediaType.MOVIE,
                title="Saga",
                group="Franchises",
                last_synced_at=utc_now(),
            )
        )
        await session.flush()
        session.add(managing_rule(1))
    service = ArtService(
        app_config=app_config,
        database=database,
        asset_storage=AssetStorage(app_config=app_config),
        matcher=Matcher(),
        phash=PhashService(app_config=app_config),
        downloads=unused(DownloadService),
        publisher=FakePublisher(),
        provider_registry=NoopProviderRegistry(provider),
        candidates=Candidates(),
        image_clients=unused(ProxyClientManager),
        image_cache=ImageCache(tmp_path / "images"),
    )

    offered = (await service.collections.sources(1, ArtType.POSTER)).sources
    assert [candidate.generated for candidate in offered[ArtSource.GENERATED]] == list(
        ArtStyle
    )
    # What matching compares never includes art to draw.
    assert (
        ArtSource.GENERATED
        not in (await service.collections.found(1, ArtType.POSTER)).sources
    )
    preview = await service.collections.drawn(1, ArtType.POSTER, ArtStyle.DARK)
    assert Image.open(BytesIO(preview)).size == (1000, 1500)

    await service.collections.save(
        1, ArtType.POSTER, SaveArtRequest(generated=ArtStyle.DARK)
    )
    assert provider.uploads == [(ArtType.POSTER, preview, "image/png")]
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(1)
        assert row is not None
        assert collection_artwork(row).poster_source == ArtSource.GENERATED

    # The same title draws the same image, which stays on the server as it is.
    await service.collections.redraw(1, ArtType.POSTER, resend=False)
    assert len(provider.uploads) == 1
    async with database.write_session() as session:
        renamed = await CollectionRepository(session).get(1)
        assert renamed is not None
        renamed.title = "Trilogy"
        session.add(renamed)
    await service.collections.redraw(1, ArtType.POSTER, resend=False)
    assert len(provider.uploads) == 2
    assert provider.uploads[-1][1] != preview


def test_drawn_art_is_the_same_for_the_same_title() -> None:
    first = render_art(ArtType.BACKGROUND, "Studio Ghibli", "Studios", ArtStyle.LIGHT)
    assert first == render_art(
        ArtType.BACKGROUND, "Studio Ghibli", "Studios", ArtStyle.LIGHT
    )
    assert Image.open(BytesIO(first)).size == (3840, 2160)
