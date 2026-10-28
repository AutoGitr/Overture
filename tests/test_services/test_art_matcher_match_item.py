"""DB-backed ArtMatcher.match_item_art paths."""

lazy from pathlib import Path
lazy from typing import Any, override

lazy import pytest
lazy from PIL import Image
lazy from sqlalchemy.ext.asyncio import async_sessionmaker
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import read_art_slot, write_art_slot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, AspectRatioTolerance, MediaType
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.schemas.art import ArtCandidate, ArtMatchResponse
lazy from overture.services.art.candidates import (
    ArtCandidates,
    CandidatePolicy,
    CandidateSources,
)
lazy from overture.services.art.matcher import (
    ArtMatcher,
    ArtMatchOutcome,
    CandidateComparison,
)
lazy from overture.services.art.matcher_cache import ArtMatcherCache
lazy from overture.services.art.phash import PHASH_HEX_LENGTH, PhashService
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.utils.file import compute_bytes_hash
lazy from overture.utils.image import FetchedImage
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    make_local_assets,
    unused,
)


def _poster(path: Path, color: str) -> bytes:
    Image.new("RGB", (40, 60), color=color).save(path, format="JPEG")
    return path.read_bytes()


@pytest.mark.parametrize("identical", [True, False])
async def test_match_refreshes_the_local_record_and_compares_its_bytes(
    tmp_path: Path,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
    identical: bool,
) -> None:
    local = _poster(tmp_path / "poster.jpg", "red")
    item = MediaItem(
        id=1, title="Changed", media_type=MediaType.MOVIE, folder_path=str(tmp_path)
    )
    # A stale record of an earlier file: the match must not trust it.
    write_art_slot(
        item,
        ArtType.POSTER,
        file_hash=compute_bytes_hash(b"old-image"),
        phash="0" * PHASH_HEX_LENGTH,
        file_mtime_ns=1,
        file_size=9,
    )
    db_session.add(item)
    await db_session.commit()
    matcher = _matcher(app_config=app_config, database=database)
    references: list[str] = []

    async def compare(*_args: Any, **kwargs: Any) -> CandidateComparison:
        references.append(kwargs["reference_phash"])
        return CandidateComparison(
            matches=[ArtCandidate(url="https://cdn.test/image.jpg", hamming=0)],
            prefiltered=0,
            compared=1,
            failed=0,
        )

    async def fetch(*_args: Any, **_kwargs: Any) -> FetchedImage:
        return FetchedImage(local if identical else b"other", "image/jpeg")

    monkeypatch.setattr(matcher, "_match_against_candidates", compare)
    monkeypatch.setattr(ArtMatcherCache, "fetch", fetch)

    result = await matcher.match_item_art(1, ArtType.POSTER, include_overturedb=False)

    assert bool(result.response.matches[0].perfect_match) is identical
    assert result.response.errors == []
    assert result.response.reference == "local_file"
    facts = result.local_file
    assert facts is not None
    assert facts.file_hash == compute_bytes_hash(local)
    assert references == [facts.phash]
    await db_session.refresh(item)
    slot = read_art_slot(item, ArtType.POSTER)
    assert slot.file_hash == compute_bytes_hash(local)
    assert slot.file_size == len(local)


class UnknownToTheServer:
    """A media server that holds none of the items it is asked about."""

    async def find_item_id(self, _item: MediaItem) -> str | None:
        return None


def _matcher(
    *,
    app_config: Settings,
    database: Database,
    candidates: ArtCandidates | None = None,
) -> ArtMatcher:
    return ArtMatcher(
        phash=PhashService(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config,
            database=database,
            asset_storage=AssetStorage(app_config=app_config),
        ),
        provider_registry=NoopProviderRegistry(UnknownToTheServer()),
        candidates=candidates or unused(ArtCandidates),
        image_clients=unused(ProxyClientManager),
        app_config=app_config,
        database=database,
        compare_concurrency=2,
    )


async def test_without_any_reference_nothing_is_compared(
    db_session: AsyncSession,
    app_config: Settings,
    database: Database,
) -> None:
    item = MediaItem(id=1, title="No reference", media_type=MediaType.MOVIE)
    db_session.add(item)
    await db_session.commit()
    result = await _matcher(app_config=app_config, database=database).match_item_art(
        1, ArtType.POSTER, include_overturedb=False
    )
    assert result.response.total_compared == 0
    assert result.response.matches == []
    assert result.response.reason == (
        "no local file, media-server image or saved URL to compare against"
    )


_NOT_FOUND = ArtMatchOutcome(ArtMatchResponse(errors=["artwork target does not exist"]))


async def test_match_item_art_returns_empty_for_missing_or_invalid_scope(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with isolated_session_factory() as session:
        session.add(MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie"))
        await session.commit()

    matcher = _matcher(app_config=app_config, database=database)

    assert (
        await matcher.match_item_art(404, ArtType.POSTER, include_overturedb=False)
        == _NOT_FOUND
    )
    assert (
        await matcher.match_item_art(
            1, ArtType.SEASON_POSTER, season_id=1, include_overturedb=False
        )
        == _NOT_FOUND
    )


async def test_match_item_art_rejects_a_season_from_another_item(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with isolated_session_factory() as session:
        session.add_all(
            [
                MediaItem(id=1, media_type=MediaType.SHOW, title="Requested show"),
                MediaItem(id=2, media_type=MediaType.SHOW, title="Other show"),
                Season(id=10, media_item_id=2, season_num=1),
            ]
        )
        await session.commit()

    assert (
        await _matcher(app_config=app_config, database=database).match_item_art(
            1, ArtType.SEASON_POSTER, season_id=10, include_overturedb=False
        )
        == _NOT_FOUND
    )


async def test_match_item_art_compares_the_gathered_candidates_under_saved_settings(
    monkeypatch: pytest.MonkeyPatch,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    gathered: list[tuple[CandidatePolicy, bool]] = []

    class Candidates(ArtCandidates):
        def __init__(self) -> None:
            pass

        @override
        async def gather(
            self, item: MediaItem, art_type: ArtType, **kwargs: Any
        ) -> CandidateSources:
            assert item.id == 1
            assert art_type is ArtType.POSTER
            assert kwargs["season_num"] is None
            gathered.append((kwargs["policy"], kwargs["include_overturedb"]))
            return CandidateSources(
                {"overturedb": [ArtCandidate(url="https://public.test/poster.jpg")]}
            )

    async def fake_match_candidates(
        reference_phash: str,
        candidates: list[ArtCandidate],
        threshold: int,
        reference_width: int = 0,
    ) -> CandidateComparison:
        assert reference_phash == "0" * PHASH_HEX_LENGTH
        assert threshold == 4
        assert reference_width == 0
        return CandidateComparison(
            matches=[candidates[0].model_copy(update={"hamming": 2})],
            prefiltered=0,
            compared=1,
            failed=0,
        )

    async with isolated_session_factory() as session:
        item = MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie")
        session.add(item)
        await session.flush()
        write_art_slot(item, ArtType.POSTER, phash="0" * PHASH_HEX_LENGTH)
        session.add(
            AppSettings(id=1, aspect_ratio_tolerance=AspectRatioTolerance.LENIENT)
        )
        await session.commit()

    matcher = _matcher(
        app_config=app_config, database=database, candidates=Candidates()
    )

    async def live_reference(*_args: object, **_kwargs: object) -> tuple[str, str]:
        return "0" * PHASH_HEX_LENGTH, "media_server"

    monkeypatch.setattr(matcher, "_phash_from_remote_reference", live_reference)
    monkeypatch.setattr(matcher, "match_candidates", fake_match_candidates)

    result = await matcher.match_item_art(
        1, ArtType.POSTER, threshold=4, include_overturedb=True
    )

    [(policy, include_overturedb)] = gathered
    assert policy.aspect_ratio_tolerance is AspectRatioTolerance.LENIENT
    assert include_overturedb is True
    assert result == ArtMatchOutcome(
        ArtMatchResponse(
            matches=[ArtCandidate(url="https://public.test/poster.jpg", hamming=2)],
            total_compared=1,
            reference="media_server",
        )
    )
