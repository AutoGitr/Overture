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
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_public_dataset
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
        self, server_item_id: str, art_type: ArtType, size: ImageSize | None
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

    monkeypatch.setattr("overture.services.art.service.is_private_url", public)
    monkeypatch.setattr("overture.utils.image.is_private_url", public)
    async with database.write_session() as session:
        session.add(
            MediaCollection(
                id=1,
                server_item_id="box",
                server_type=ServerType.PLEX,
                media_type=MediaType.MOVIE,
                title="Saga",
                tmdb_collection_id=10,
                last_synced_at=utc_now(),
            )
        )
    service = ArtService(
        app_config=app_config,
        database=database,
        asset_storage=AssetStorage(app_config=app_config),
        matcher=Matcher(),
        downloads=unused(DownloadService),
        publisher=publisher,
        provider_registry=NoopProviderRegistry(provider),
        candidates=Candidates(),
        image_clients=images,
        image_cache=ImageCache(tmp_path / "images"),
    )
    try:
        sources = await service.get_collection_sources(
            1, MediaType.MOVIE, ArtType.POSTER
        )
        assert sources.sources["tmdb"][0].url == URL
        await service.save_collection(
            1,
            MediaType.MOVIE,
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
        assert publisher.broadcasts[-1] == ("collection.updated", {"collection_id": 1})
        # Client dimensions cannot disguise actual landscape bytes as a poster.
        with pytest.raises(PublicServiceError, match="aspect ratio"):
            await service.save_collection(
                1,
                MediaType.MOVIE,
                ArtType.BACKGROUND,
                SaveArtRequest(url=URL, width=1920, height=1080),
            )
        assert len(provider.uploads) == 1
        result = await service.match_collection(1, MediaType.MOVIE, ArtType.POSTER, 5)
        assert result.reference == "media_server"
        assert result.total_compared == 1
        state = await service.clear_collection(1, MediaType.MOVIE, ArtType.POSTER)
        assert state.poster_url is None
        assert state.poster_status == "partial"
        async with database.read_session() as session:
            cleared = await CollectionRepository(session).get(1)
            assert cleared is not None
            assert cleared.thumb_url is not None
            assert read_art_slot(cleared, ArtType.POSTER).file_hash is not None
        assert len(provider.uploads) == 1
        with pytest.raises(PublicServiceError, match="posters and backgrounds"):
            await service.get_collection_sources(
                1, MediaType.MOVIE, ArtType.SEASON_POSTER
            )
        with pytest.raises(PublicServiceError, match="Collection not found"):
            await service.save_collection(
                1, MediaType.SHOW, ArtType.POSTER, SaveArtRequest(url=URL)
            )
    finally:
        await images.client.aclose()


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
    row = MediaCollection(
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
