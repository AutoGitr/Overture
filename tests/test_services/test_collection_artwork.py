"""Collection artwork uses shared validation, storage, candidates, and matching."""

lazy import shutil
lazy from io import BytesIO
lazy from pathlib import Path
lazy from typing import override

lazy import httpx2
lazy import pytest
lazy from PIL import Image
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.db.ledger import (
    Destination,
    Evidence,
    confirm_delivery,
    missing_deliveries,
    observe,
    read_asset,
)
lazy from overture.db.models.catalog import CatalogCollection
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtGeneration,
    ArtSource,
    ArtStyle,
    ArtType,
    AssetStatus,
    CatalogMediaType,
    CollectionPosterStyle,
    DeliveryChannel,
    ImageSize,
    MediaType,
    ServerAsset,
    TmdbLanguageFilter,
)
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.media_servers.adapters import ProviderImageRequest
lazy from overture.repositories.collections import CollectionRepository
lazy from overture.schemas.art import ArtCandidate, SaveCollectionArtRequest
lazy from overture.schemas.assets import assets_read
lazy from overture.schemas.removal import AssetRemoval
lazy from overture.services.art.candidates import (
    MEMBER_BACKGROUNDS_TOTAL,
    ArtCandidates,
    CandidatePolicy,
    CandidateSources,
)
lazy from overture.services.art.matcher import ArtMatcher, CandidateComparison
lazy from overture.services.art.phash import PhashService
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.removal import AssetRemover
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.storage.image_cache import ImageCache
lazy from overture.utils.art_urls import PublicArtUrl
lazy from overture.utils.errors import PublicServiceError
lazy from overture.utils.generated_art import FONT_FILES, font_coverage, render_art
lazy from overture.utils.image import THUMB_EXTENSION
lazy from overture.utils.time import utc_now
lazy from tests.bulk_helpers import enable_catalog
lazy from tests.collection_helpers import (
    managing_rule,
    shown_on_server,
    stored_collection,
)
lazy from tests.factories import seed_asset, server_ref
lazy from tests.runtime_helpers import NoopProviderRegistry, art_service, unused
lazy from tests.test_services.test_collection_management import Provider
lazy from tests.test_services.test_collections_service import FakePublisher

URL = "https://image.tmdb.org/t/p/original/collection.jpg"
TPDB = "https://theposterdb.com/api/assets/2503"


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

    @override
    async def annotate_perfect(
        self, content_hash: str, matches: list[ArtCandidate]
    ) -> list[str]:
        for match in matches:
            match.perfect_match = True
        return []


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
    monkeypatch.setattr("overture.utils.image_fetch.is_private_url", public)
    async with database.write_session() as session:
        session.add(
            stored_collection(
                id=1,
                server_item_id="box",
                media_type=MediaType.MOVIE,
                title="Saga",
                tmdb_collection_id=10,
                last_synced_at=utc_now(),
            )
        )
        await session.flush()
        session.add(managing_rule(1))
    image_cache = ImageCache(tmp_path / "images", tmp_path / "uploads")
    service = art_service(
        app_config=app_config,
        database=database,
        asset_storage=AssetStorage(app_config=app_config),
        matcher=Matcher(),
        phash=Hashes(),
        downloads=unused(DownloadService),
        publisher=publisher,
        provider_registry=NoopProviderRegistry(provider),
        candidates=Candidates(),
        image_clients=images,
        image_cache=image_cache,
        remover=AssetRemover(
            asset_storage=AssetStorage(app_config=app_config),
            provider_registry=NoopProviderRegistry(provider),
            database=database,
        ),
    )
    try:
        sources = await service.collections.sources(1, ArtType.POSTER)
        assert sources.sources["tmdb"][0].url == URL
        await service.collections.save(
            1,
            ArtType.POSTER,
            SaveCollectionArtRequest(
                url=URL,
                width=200,
                height=300,
                poster_style=CollectionPosterStyle.INDIVIDUAL,
            ),
        )
        assert provider.uploads == [(ArtType.POSTER, image_bytes, "image/jpeg")]
        # Its thumbnail is rendered as it is kept, as every kept original's is.
        assert (
            len(list((tmp_path / "images" / "thumbs").rglob(f"*{THUMB_EXTENSION}")))
            == 1
        )
        async with database.read_session() as session:
            row = await CollectionRepository(session).get(1)
            assert row is not None
            slot = read_asset(row, ServerAsset.POSTER)
            assert slot.url == URL
            assert slot.poster_style is CollectionPosterStyle.INDIVIDUAL
            assert (slot.fingerprint, slot.width, slot.height) == ("a" * 64, 200, 300)
            assert slot.collection_id == 1
            assert slot.media_item_id is None
            # The image route reads the path the server lists after the upload.
            assert (
                server_ref(row, ServerAsset.POSTER)
                == "https://plex.test/library/metadata/box/thumb/1"
            )
        assert publisher.broadcasts[-1] == ("collection.updated", {"collection_id": 1})
        with pytest.raises(PublicServiceError, match="poster style"):
            await service.collections.save(
                1, ArtType.POSTER, SaveCollectionArtRequest(url=URL)
            )
        # Client dimensions cannot disguise actual landscape bytes as a poster.
        with pytest.raises(PublicServiceError, match="aspect ratio"):
            await service.collections.save(
                1,
                ArtType.BACKGROUND,
                SaveCollectionArtRequest(url=URL, width=1920, height=1080),
            )
        assert len(provider.uploads) == 1
        # The image Overture uploaded is what the server shows, as a local
        # file is an item's: candidates are compared with it.
        result = await service.collections.match(1, ArtType.POSTER, 5)
        assert result.reference == "local_file"
        assert result.total_compared == 1
        assert [match.perfect_match for match in result.matches] == [True]
        await service.collections.remove(1, ArtType.POSTER, AssetRemoval())
        async with database.read_session() as session:
            cleared = await CollectionRepository(session).get(1)
            assert cleared is not None
            assert read_asset(cleared, ServerAsset.POSTER).url is None
            # The copy still shows what it was last seen showing.
            assert server_ref(cleared, ServerAsset.POSTER) is not None
            [copy] = read_asset(cleared, ServerAsset.POSTER).deliveries
            assert copy.observed_hash is not None
        assert len(provider.uploads) == 1
        with pytest.raises(PublicServiceError, match="posters and backgrounds"):
            await service.collections.sources(1, ArtType.SEASON_POSTER)
        with pytest.raises(PublicServiceError, match="Collection not found"):
            await service.collections.save(
                404,
                ArtType.POSTER,
                SaveCollectionArtRequest(
                    url=URL, poster_style=CollectionPosterStyle.INDIVIDUAL
                ),
            )
    finally:
        await images.client.aclose()


@pytest.mark.parametrize("held", [False, True])
async def test_adopting_a_collection_image_keeps_it_delivered_without_an_upload(
    held: bool,
    tmp_path: Path,
    database: Database,
    app_config: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without content of its own, the link becomes what the lead copy shows."""
    data = BytesIO()
    Image.new("RGB", (200, 300), "red").save(data, format="JPEG")
    images = Images(data.getvalue())
    provider = ArtProvider(app_config)

    async def public(_url: str) -> bool:
        return False

    monkeypatch.setattr("overture.utils.image_fetch.is_private_url", public)
    async with database.write_session() as session:
        row = stored_collection(
            id=1,
            server_item_id="box",
            media_type=MediaType.MOVIE,
            title="Saga",
            tmdb_collection_id=10,
            last_synced_at=utc_now(),
        )
        shown_on_server(row, poster="/library/metadata/box/thumb/7")
        if held:
            seed_asset(
                row,
                ServerAsset.POSTER,
                upload_hash="kept",
                file_hash="kept",
                fingerprint="a" * 64,
            )
            part = row.libraries[0]
            confirm_delivery(
                row,
                ServerAsset.POSTER,
                Destination(
                    part.server_id, part.server_item_id, DeliveryChannel.UPLOAD
                ),
                ref="/library/metadata/box/thumb/7",
            )
        session.add(row)
        await session.flush()
        session.add(managing_rule(1))
    service = art_service(
        app_config=app_config,
        database=database,
        asset_storage=AssetStorage(app_config=app_config),
        matcher=Matcher(),
        phash=Hashes(),
        downloads=unused(DownloadService),
        publisher=FakePublisher(),
        provider_registry=NoopProviderRegistry(provider),
        candidates=Candidates(),
        image_clients=images,
        image_cache=ImageCache(tmp_path / "images", tmp_path / "uploads"),
        remover=unused(AssetRemover),
    )
    try:
        matched = await service.collections.match(1, ArtType.POSTER, 5)
        assert matched.reference == ("local_file" if held else "media_server")
        await service.collections.adopt(
            1, ArtType.POSTER, PublicArtUrl(URL), CollectionPosterStyle.INDIVIDUAL
        )
    finally:
        await images.client.aclose()

    async with database.read_session() as session:
        saved = await CollectionRepository(session).get(1)
        assert saved is not None
    poster = read_asset(saved, ServerAsset.POSTER)
    assert poster.url == URL
    assert poster.status is AssetStatus.COMPLETE
    assert missing_deliveries(poster) == []
    assert poster.content_hash == ("kept" if held else poster.content_hash)
    assert server_ref(saved, ServerAsset.POSTER) == "/library/metadata/box/thumb/7"
    assert provider.uploads == []


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
                media_type=MediaType.MOVIE,
                title="Saga",
                last_synced_at=utc_now(),
            )
        )
        await session.flush()
        session.add(managing_rule(1))
    service = art_service(
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
        image_cache=ImageCache(tmp_path / "images", tmp_path / "uploads"),
        remover=AssetRemover(
            asset_storage=AssetStorage(app_config=app_config),
            provider_registry=NoopProviderRegistry(provider),
            database=database,
        ),
    )

    upload = await service.uploads.store(image_bytes)
    await service.collections.save(
        1, ArtType.POSTER, SaveCollectionArtRequest(upload_hash=upload.upload_hash)
    )

    assert provider.uploads == [(ArtType.POSTER, image_bytes, "image/png")]
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(1)
        assert row is not None
        artwork = assets_read(row)
    assert (
        artwork.poster.source,
        artwork.poster.content_hash,
    ) == (
        ArtSource.UPLOAD,
        upload.upload_hash,
    )
    assert artwork.poster.status == "complete"
    thumb = await service.collections.local_image(
        1, ArtType.POSTER, ImageSize.DISPLAY, upload.upload_hash
    )
    assert thumb.media_type == "image/avif"
    with pytest.raises(PublicServiceError, match="Collection image not found"):
        await service.collections.local_image(1, ArtType.BACKGROUND, None, None)

    await service.collections.reupload(1, ArtType.POSTER)
    assert provider.uploads[-1] == (ArtType.POSTER, image_bytes, "image/png")

    # A sync saw another image on the server and forgot the one uploaded;
    # the selection still names it, so it is sent and recorded again.
    async with database.write_session() as session:
        row = await CollectionRepository(session).get(1)
        assert row is not None
        part = row.libraries[0]
        copy = Destination(part.server_id, part.server_item_id, DeliveryChannel.UPLOAD)
        observe(row, ServerAsset.POSTER, copy, Evidence.DIFFERENT, ref="/other")
        session.add(row)
    await service.collections.reupload(1, ArtType.POSTER)
    assert len(provider.uploads) == 3
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(1)
        assert row is not None
        assert assets_read(row).poster.content_hash == upload.upload_hash


async def test_an_inactive_collection_records_its_art_for_the_sync_that_restores_it(
    database: Database, app_config: Settings, tmp_path: Path
) -> None:
    provider = ArtProvider(app_config)
    async with database.write_session() as session:
        session.add(
            stored_collection(
                id=2,
                server_item_id=None,
                media_type=MediaType.MOVIE,
                title="Inactive",
                last_synced_at=utc_now(),
            )
        )
        await session.flush()
        session.add(managing_rule(2))
    service = art_service(
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
        image_cache=ImageCache(tmp_path / "images", tmp_path / "uploads"),
        remover=AssetRemover(
            asset_storage=AssetStorage(app_config=app_config),
            provider_registry=NoopProviderRegistry(provider),
            database=database,
        ),
    )
    await service.collections.save(
        2, ArtType.POSTER, SaveCollectionArtRequest(generated=ArtStyle.DARK)
    )

    assert provider.uploads == []
    async with database.read_session() as session:
        row = await session.get(MediaCollection, 2)
    assert row is not None
    slot = read_asset(row, ServerAsset.POSTER)
    assert slot.generated_style is ArtStyle.DARK
    assert slot.upload_hash is not None
    assert slot.content_hash == slot.upload_hash
    assert server_ref(row, ServerAsset.POSTER) is None


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

    app_config.TMDB_READ_ACCESS_TOKEN = SecretStr("key")
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
        tmdb_collection_id=10,
    )
    policy = CandidatePolicy.of(AppSettings())
    disabled = await candidates.gather_collection(row, ArtType.POSTER, policy)
    assert [candidate.url for candidate in disabled.by_source["tmdb"]] == [URL]
    assert disabled.by_source["overturedb"] == []
    async with database.write_session() as session:
        session.add(
            CatalogCollection(
                tmdb_id=10,
                title="Saga",
                poster_url_individual=URL,
                poster_url_matte=TPDB,
            )
        )
    async with database.write_session() as session:
        await enable_catalog(session)
    policy = CandidatePolicy.of(AppSettings(skip_media_server_tmdb_urls=True))
    enabled = await candidates.gather_collection(row, ArtType.POSTER, policy)
    assert list(enabled.by_source) == ["tmdb", "Plex", "overturedb"]
    # Each OvertureDB poster is offered with its style, the collection's first,
    # and only there: TMDB and the server offer the same image too.
    assert [
        (candidate.url, candidate.poster_style)
        for candidate in enabled.by_source["overturedb"]
    ] == [
        (URL, CollectionPosterStyle.INDIVIDUAL),
        (TPDB, CollectionPosterStyle.MATTE),
    ]
    assert enabled.by_source["tmdb"] == []
    assert enabled.by_source["Plex"] == []
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


async def test_generated_art_is_offered_chosen_and_generated_again_for_a_new_title(
    tmp_path: Path, database: Database, app_config: Settings
) -> None:
    provider = ArtProvider(app_config)
    async with database.write_session() as session:
        session.add(
            stored_collection(
                id=1,
                server_item_id="box",
                media_type=MediaType.MOVIE,
                title="Saga",
                group="Franchises",
                last_synced_at=utc_now(),
            )
        )
        await session.flush()
        session.add(managing_rule(1))
    service = art_service(
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
        image_cache=ImageCache(tmp_path / "images", tmp_path / "uploads"),
        remover=AssetRemover(
            asset_storage=AssetStorage(app_config=app_config),
            provider_registry=NoopProviderRegistry(provider),
            database=database,
        ),
    )

    offered = (await service.collections.sources(1, ArtType.POSTER)).sources
    # A grouped collection's poster is offered under its group, then alone.
    assert [
        (candidate.generated, candidate.title_only)
        for candidate in offered[ArtSource.GENERATED]
    ] == [(style, False) for style in ArtStyle] + [(style, True) for style in ArtStyle]
    backgrounds = (await service.collections.sources(1, ArtType.BACKGROUND)).sources
    assert [
        (candidate.generated, candidate.title_only)
        for candidate in backgrounds[ArtSource.GENERATED]
    ] == [(style, False) for style in ArtStyle]
    with pytest.raises(PublicServiceError, match="Only posters"):
        await service.collections.save(
            1,
            ArtType.BACKGROUND,
            SaveCollectionArtRequest(generated=ArtStyle.DARK, title_only=True),
        )
    # What matching compares never includes art to generate.
    assert (
        ArtSource.GENERATED
        not in (await service.collections.found(1, ArtType.POSTER)).sources
    )
    preview = await service.collections.preview(
        1, ArtType.POSTER, ArtGeneration(ArtStyle.DARK)
    )
    assert Image.open(BytesIO(preview)).size == (2000, 3000)

    await service.collections.save(
        1, ArtType.POSTER, SaveCollectionArtRequest(generated=ArtStyle.DARK)
    )
    assert provider.uploads == [(ArtType.POSTER, preview, "image/png")]
    async with database.read_session() as session:
        row = await CollectionRepository(session).get(1)
        assert row is not None
        assert assets_read(row).poster.source == ArtSource.GENERATED

    # Generated art is kept in the cache, which can be deleted: it is drawn again.
    assert not (tmp_path / "uploads").exists()
    shutil.rmtree(tmp_path / "images")
    shown = await service.collections.local_image(1, ArtType.POSTER, None, None)
    assert Path(shown.path).is_relative_to(tmp_path / "images" / "originals")
    shutil.rmtree(tmp_path / "images")
    await service.collections.reupload(1, ArtType.POSTER)
    assert provider.uploads[-1] == (ArtType.POSTER, preview, "image/png")
    del provider.uploads[1:]

    # The same title generates the same image, which stays on the server as it is.
    await service.collections.regenerate(1, ArtType.POSTER, resend=False)
    assert len(provider.uploads) == 1
    async with database.write_session() as session:
        renamed = await CollectionRepository(session).get(1)
        assert renamed is not None
        renamed.title = "Trilogy"
        session.add(renamed)
    await service.collections.regenerate(1, ArtType.POSTER, resend=False)
    assert len(provider.uploads) == 2
    assert provider.uploads[-1][1] != preview


def test_generated_art_is_the_same_for_the_same_title() -> None:
    first = render_art(ArtType.BACKGROUND, ArtStyle.LIGHT, "Studio Ghibli", "Studios")
    assert first == render_art(
        ArtType.BACKGROUND, ArtStyle.LIGHT, "Studio Ghibli", "Studios"
    )
    assert Image.open(BytesIO(first)).size == (3840, 2160)
    # Art without a title is the style's colours alone.
    untitled = render_art(ArtType.BACKGROUND, ArtStyle.LIGHT)
    assert untitled not in {first, render_art(ArtType.BACKGROUND, ArtStyle.DARK)}
    # A title without a heading is generated alone, with no rule above it.
    alone = render_art(ArtType.POSTER, ArtStyle.DARK, "Sagas")
    assert alone != render_art(ArtType.POSTER, ArtStyle.DARK, "Sagas", "Sagas")


def test_generated_gradients_are_dithered_rather_than_banded() -> None:
    background = Image.open(BytesIO(render_art(ArtType.BACKGROUND, ArtStyle.DARK)))
    width, height = background.size
    # A band is a run of rows of one level; the dark gradient spans about 17
    # levels over 2160 rows, so undithered bands would be over 100 rows tall.
    band = 0
    longest = 0
    previous = b""
    for y in range(height):
        row = background.crop((0, y, 8, y + 1)).tobytes()
        band = band + 1 if row == previous else 1
        longest = max(longest, band)
        previous = row
    assert longest < 16
    assert width == 3840


@pytest.mark.parametrize(
    "title",
    [
        "100 Years of Olympic Films: 1912\u20132012",
        "Amélie “Ghibli” — Ωμέγα Ёлки… № ½ € ★ ♫ 🎬",
        "千と千尋の神隠し スタジオジブリ 스튜디오 지브리 宫崎骏",
        "سلسلة أفلام الرعب עברית हिन्दी ภาษาไทย",
    ],
)
def test_bundled_fonts_draw_every_character_of_a_title(title: str) -> None:
    missing = {
        char
        for char in title
        if not any(ord(char) in font_coverage(name) for name in FONT_FILES)
    }
    assert not missing
    assert Image.open(BytesIO(render_art(ArtType.POSTER, ArtStyle.DARK, title)))


async def test_generated_backgrounds_never_show_text_and_title_only_posters_stay_so(
    database: Database, app_config: Settings, tmp_path: Path
) -> None:
    provider = ArtProvider(app_config)
    async with database.write_session() as session:
        session.add(
            stored_collection(
                id=1,
                server_item_id="box",
                media_type=MediaType.MOVIE,
                title="Saga",
                last_synced_at=utc_now(),
            )
        )
        await session.flush()
        session.add(managing_rule(1))
    service = art_service(
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
        image_cache=ImageCache(tmp_path / "images", tmp_path / "uploads"),
        remover=AssetRemover(
            asset_storage=AssetStorage(app_config=app_config),
            provider_registry=NoopProviderRegistry(provider),
            database=database,
        ),
    )

    await service.collections.save(
        1,
        ArtType.BACKGROUND,
        SaveCollectionArtRequest(generated=ArtStyle.ACCENT),
    )
    await service.collections.save(
        1,
        ArtType.POSTER,
        SaveCollectionArtRequest(generated=ArtStyle.DARK, title_only=True),
    )
    async with database.write_session() as session:
        row = await CollectionRepository(session).get(1)
        assert row is not None
        slot = read_asset(row, ServerAsset.POSTER)
        assert (slot.generated_style, slot.generated_title_only) == (
            ArtStyle.DARK,
            True,
        )
        row.title = "Renamed"
        session.add(row)
    await service.collections.regenerate(1, ArtType.BACKGROUND, resend=False)
    await service.collections.regenerate(1, ArtType.POSTER, resend=False)

    # The background shows no title, so a new one leaves it as it is.
    assert [art_type for art_type, *_ in provider.uploads] == [
        ArtType.BACKGROUND,
        ArtType.POSTER,
        ArtType.POSTER,
    ]
    assert provider.uploads[0][1] == render_art(ArtType.BACKGROUND, ArtStyle.ACCENT)
    assert provider.uploads[-1][1] == render_art(
        ArtType.POSTER, ArtStyle.DARK, "Renamed"
    )


async def test_member_backgrounds_are_the_largest_of_each_member_and_of_all(
    database: Database, app_config: Settings
) -> None:
    class Tmdb(TMDBClient):
        def __init__(self) -> None:
            pass

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
            assert art_type is ArtType.BACKGROUND
            if tmdb_id == 99:
                raise ValueError("TMDB unavailable")
            # Twelve 16:9 backgrounds, member 1's the largest of all.
            return [
                ArtCandidate(
                    url=f"https://image.tmdb.org/t/p/original/{tmdb_id}-{size}.jpg",
                    width=(width := 1920 + 16 * (size + 12 * tmdb_id)),
                    height=width * 9 // 16,
                )
                for size in range(12)
            ]

    app_config.TMDB_READ_ACCESS_TOKEN = SecretStr("key")
    candidates = ArtCandidates(
        database=database,
        provider_registry=NoopProviderRegistry(),
        tmdb_client=Tmdb(),
        app_config=app_config,
    )
    members = [(MediaType.MOVIE, tmdb_id) for tmdb_id in (*range(1, 12), 99)]

    offered = await candidates.member_backgrounds(
        "Saga", members, CandidatePolicy.of(AppSettings())
    )

    assert len(offered) == MEMBER_BACKGROUNDS_TOTAL
    sizes = [(c.width or 0) * (c.height or 0) for c in offered]
    assert sizes == sorted(sizes, reverse=True)
    # Each member offers only its ten largest: its two smallest never appear.
    assert not any(c.url.endswith(("-0.jpg", "-1.jpg")) for c in offered)
    assert offered[0].url.endswith("/11-11.jpg")
