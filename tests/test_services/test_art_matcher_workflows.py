"""Art matcher filtering, caching, and ordering tests."""

lazy import asyncio

lazy import httpx2
lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, AspectRatioTolerance, TmdbLanguageFilter
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.schemas.art import ArtCandidate
lazy from overture.services.art.candidates import ArtCandidates, CandidatePolicy
lazy from overture.services.art.matcher import ArtMatcher, ArtMatcherCache
lazy from overture.services.art.phash import PhashService
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.utils.image import FetchedImage
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    make_local_assets,
    unused,
)


def _policy(tolerance: AspectRatioTolerance) -> CandidatePolicy:
    return CandidatePolicy(
        tmdb_language_filter=TmdbLanguageFilter.ALL,
        aspect_ratio_tolerance=tolerance,
        disable_media_server_art=False,
        skip_media_server_tmdb_urls=False,
    )


def test_source_candidates_follow_selected_aspect_ratio_tolerance() -> None:
    strict = _policy(AspectRatioTolerance.STRICT)
    off = _policy(AspectRatioTolerance.OFF)
    url = "https://image.test/a.jpg"

    assert strict.accepts(
        ArtCandidate(url=url, width=1000, height=1500), ArtType.POSTER
    )
    assert not strict.accepts(
        ArtCandidate(url=url, width=1000, height=1000), ArtType.POSTER
    )
    assert not strict.accepts(ArtCandidate(url=url), ArtType.POSTER)
    assert off.accepts(ArtCandidate(url=url), ArtType.POSTER)
    assert strict.accepts(
        ArtCandidate(url=url, width=1920, height=1080), ArtType.BACKGROUND
    )


async def test_match_candidates_skips_images_narrower_than_the_reference(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
    image_clients: ProxyClientManager,
) -> None:
    async def fake_cached_url_phash(url: str, **_kwargs: object) -> str | None:
        return {
            "https://ok.test/tmdb.jpg": "near",
            "https://ok.test/plex.jpg": "same",
        }.get(url)

    def fake_distance(reference: str, candidate: str) -> int:
        return {"near": 3, "same": 0}[candidate]

    phash = PhashService(app_config=app_config)
    cache = ArtMatcherCache(
        phash=phash,
        provider_registry=NoopProviderRegistry(),
        image_clients=image_clients,
        app_config=app_config,
    )
    monkeypatch.setattr(cache, "cached_url_phash", fake_cached_url_phash)
    monkeypatch.setattr(phash, "hamming_distance", fake_distance)

    comparison = await ArtMatcher(
        phash=phash,
        local_assets=make_local_assets(
            app_config=app_config,
            database=database,
            asset_storage=AssetStorage(app_config=app_config),
        ),
        provider_registry=NoopProviderRegistry(),
        candidates=unused(ArtCandidates),
        image_clients=image_clients,
        cache=cache,
        app_config=app_config,
        database=database,
    ).match_candidates(
        "reference",
        [
            ArtCandidate(
                url="https://bad.test/small.jpg",
                width=100,
                height=150,
                source="tmdb",
            ),
            ArtCandidate(
                url="https://bad.test/wide.jpg",
                width=1000,
                height=1000,
                source="tmdb",
            ),
            ArtCandidate(
                url="https://bad.test/unknown.jpg",
                source="tmdb",
            ),
            ArtCandidate(
                url="https://unreadable.test/image.jpg",
                width=1000,
                height=1500,
            ),
            ArtCandidate(
                url="https://ok.test/tmdb.jpg",
                width=1000,
                height=1500,
                source="tmdb",
            ),
            ArtCandidate(
                url="https://ok.test/plex.jpg",
                width=900,
                height=1350,
                source="plex",
            ),
        ],
        threshold=5,
        reference_width=500,
    )

    # The shape of an image is the candidate policy's concern, not the
    # matcher's: only the narrow one is skipped, and three cannot be read.
    assert comparison.prefiltered == 1
    assert comparison.compared == 2
    assert comparison.failed == 3
    assert [match.url for match in comparison.matches] == [
        "https://ok.test/plex.jpg",
        "https://ok.test/tmdb.jpg",
    ]
    assert [match.hamming for match in comparison.matches] == [0, 3]


async def test_cached_url_phash_caches_success(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    image_clients: ProxyClientManager,
) -> None:
    calls = 0
    phash = PhashService(app_config=app_config)
    cache = ArtMatcherCache(
        phash=phash,
        provider_registry=NoopProviderRegistry(),
        image_clients=image_clients,
        app_config=app_config,
    )

    async def fake_fetch_match_image(*_args: object, **_kwargs: object) -> FetchedImage:
        nonlocal calls
        calls += 1
        return FetchedImage(b"image", "image/jpeg")

    async def fake_compute(_data: bytes) -> str:
        return "abc123"

    monkeypatch.setattr(cache, "fetch", fake_fetch_match_image)
    monkeypatch.setattr(phash, "compute_from_bytes", fake_compute)

    first = await cache.cached_url_phash("https://images.test/poster.jpg")
    second = await cache.cached_url_phash("https://images.test/poster.jpg")

    assert first == "abc123"
    assert second == "abc123"
    assert calls == 1
    assert (
        await cache.cached_url_phash("https://images.test/poster.jpg", fresh=True)
        == "abc123"
    )
    assert calls == 2


async def test_cached_url_phash_returns_none_when_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    image_clients: ProxyClientManager,
) -> None:
    cache = ArtMatcherCache(
        phash=PhashService(app_config=app_config),
        provider_registry=NoopProviderRegistry(),
        image_clients=image_clients,
        app_config=app_config,
    )

    async def fake_fetch_match_image(*_args: object, **_kwargs: object) -> FetchedImage:
        raise httpx2.HTTPError("not found")

    monkeypatch.setattr(cache, "fetch", fake_fetch_match_image)

    assert await cache.cached_url_phash("https://images.test/missing.jpg") is None


async def test_cached_url_phash_keeps_waiters_serialized_after_a_failure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    image_clients: ProxyClientManager,
) -> None:
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()
    release_second = asyncio.Event()
    calls = 0
    running = 0
    peak = 0
    phash = PhashService(app_config=app_config)
    cache = ArtMatcherCache(
        phash=phash,
        provider_registry=NoopProviderRegistry(),
        image_clients=image_clients,
        app_config=app_config,
    )

    async def fake_fetch_match_image(*_args: object, **_kwargs: object) -> FetchedImage:
        nonlocal calls, running, peak
        calls += 1
        running += 1
        peak = max(peak, running)
        try:
            if calls == 1:
                first_started.set()
                await release_first.wait()
                raise httpx2.HTTPError("temporary")
            second_started.set()
            await release_second.wait()
            return FetchedImage(b"image", "image/jpeg")
        finally:
            running -= 1

    async def fake_compute(_data: bytes) -> str:
        return "abc123"

    monkeypatch.setattr(cache, "fetch", fake_fetch_match_image)
    monkeypatch.setattr(phash, "compute_from_bytes", fake_compute)

    first = asyncio.create_task(
        cache.cached_url_phash("https://images.test/poster.jpg")
    )
    await first_started.wait()
    second = asyncio.create_task(
        cache.cached_url_phash("https://images.test/poster.jpg")
    )
    release_first.set()
    assert await asyncio.gather(first, second) == [None, None]
    assert calls == 1

    retry = asyncio.create_task(
        cache.cached_url_phash("https://images.test/poster.jpg")
    )
    await second_started.wait()
    third = asyncio.create_task(
        cache.cached_url_phash("https://images.test/poster.jpg")
    )
    await asyncio.sleep(0)
    assert calls == 2
    release_second.set()
    assert await asyncio.gather(retry, third) == ["abc123", "abc123"]

    assert peak == 1
