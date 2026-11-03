"""Coverage for byte-for-byte comparison of remote artwork with the local file."""

lazy from typing import Any, override

lazy import httpx2
lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.art_slots import ArtFileFacts
lazy from overture.schemas.art import ArtCandidate
lazy from overture.services.art import matcher_cache
lazy from overture.services.art import perfect_match as module
lazy from overture.services.art.matcher_cache import ArtMatcherCache
lazy from overture.utils.file import compute_bytes_hash
lazy from overture.utils.image import FetchedImage
lazy from tests.runtime_helpers import NoopProviderRegistry, StaticImageClients

LOCAL_BYTES = b"identical-bytes"


def _local_facts(data: bytes = LOCAL_BYTES) -> ArtFileFacts:
    return ArtFileFacts(
        file_hash=compute_bytes_hash(data),
        phash="0" * 16,
        width=1000,
        height=1500,
        file_mtime_ns=1,
        file_size=len(data),
    )


class FakeCache(ArtMatcherCache):
    """Serves one remote image, or one failure, and records what was fetched."""

    def __init__(self, remote: bytes | Exception) -> None:
        self._remote = remote
        self.fetched: list[str] = []

    @override
    async def fetch(self, url: str) -> FetchedImage:
        self.fetched.append(url)
        if isinstance(self._remote, Exception):
            raise self._remote
        return FetchedImage(data=self._remote, media_type="image/jpeg")


@pytest.mark.parametrize("hamming", [0, 1])
@pytest.mark.parametrize("remote", [LOCAL_BYTES, b"different-bytes"])
async def test_close_matches_are_compared_with_the_original_bytes(
    hamming: int, remote: bytes
) -> None:
    cache = FakeCache(remote)
    matches: list[ArtCandidate] = [
        ArtCandidate(
            hamming=hamming,
            url="https://example.test/a.jpg",
            preview_url="https://example.test/preview.jpg",
            source="tmdb",
        )
    ]

    errors = await module.annotate_perfect_matches(_local_facts(), matches, cache=cache)

    assert errors == []
    assert bool(matches[0].perfect_match) == (remote == LOCAL_BYTES)
    assert cache.fetched == ["https://example.test/a.jpg"]


async def test_distant_and_urlless_matches_are_never_fetched() -> None:
    cache = FakeCache(LOCAL_BYTES)
    matches: list[ArtCandidate] = [
        ArtCandidate(hamming=2, url="https://example.test/far.jpg"),
        ArtCandidate(hamming=0, url=""),
    ]

    await module.annotate_perfect_matches(_local_facts(), matches, cache=cache)

    assert cache.fetched == []
    assert all(match.perfect_match is None for match in matches)


async def test_a_different_size_is_not_identical() -> None:
    assert not await module.remote_matches_file(
        "https://example.test/a.jpg",
        _local_facts(),
        cache=FakeCache(LOCAL_BYTES + b"!"),
    )


async def test_fetch_failure_is_reported_not_annotated() -> None:
    matches: list[ArtCandidate] = [
        ArtCandidate(hamming=0, url="https://example.test/a.jpg")
    ]

    errors = await module.annotate_perfect_matches(
        _local_facts(), matches, cache=FakeCache(httpx2.ConnectError("offline"))
    )

    assert matches[0].perfect_match is None
    assert len(errors) == 1
    assert errors[0].startswith("perfect-match verification failed: ")


class _HeaderProvider:
    def get_download_headers(self, url: str) -> dict[str, str]:
        return {"X-Token": "server"} if url.startswith("http://media.test") else {}


@pytest.mark.parametrize(
    ("url", "trusted", "headers"),
    [
        ("http://media.test:32400/thumb", True, {"X-Token": "server"}),
        ("https://example.test/a.jpg", False, {}),
    ],
)
async def test_only_the_media_server_is_fetched_as_trusted_with_its_headers(
    monkeypatch: pytest.MonkeyPatch,
    url: str,
    trusted: bool,
    headers: dict[str, str],
    *,
    app_config: Settings,
) -> None:
    app_config.MEDIA_SERVER_URL = "http://media.test:32400"
    calls: list[dict[str, Any]] = []

    async def fetch_image(_url: str, _client: object, **kwargs: Any) -> FetchedImage:
        calls.append(kwargs)
        return FetchedImage(data=LOCAL_BYTES, media_type="image/jpeg")

    monkeypatch.setattr(matcher_cache, "fetch_image", fetch_image)

    await matcher_cache.fetch_art(
        url,
        provider_registry=NoopProviderRegistry(_HeaderProvider()),
        image_clients=StaticImageClients(),
        app_config=app_config,
    )

    assert calls == [{"allow_private": trusted, "headers": headers}]
