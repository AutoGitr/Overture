"""Catalog parsing and candidate edge cases."""

lazy import gzip
lazy import json
lazy from pathlib import Path
lazy from typing import Any

lazy import httpx2
lazy import pytest
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy import overture.services.catalog.remote as catalog_mod
lazy from overture.catalog_contract.contract import (
    SCHEMA_VERSION,
    dump_catalog,
    read_catalog,
)
lazy from overture.config import Settings
lazy from overture.db.models.catalog import CatalogItem
lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import ArtType, MediaType, ThemeBulkSource
lazy from overture.repositories.catalog import CatalogRepository
lazy from overture.schemas.catalog import CatalogSyncStats
lazy from overture.services.catalog import staging
lazy from overture.services.catalog.index import CatalogIndex
lazy from overture.services.catalog.lookup import (
    build_candidate,
)
lazy from overture.utils.time import utc_now
lazy from tests.http_mock import RecordingMockTransport


def catalog_payload() -> dict[str, Any]:
    """A catalog in exactly the shape OvertureDB publishes.

    ``generated_at``, ``third_party_notices`` and ``sources`` are the catalog's
    own bookkeeping: Overture stores none of them and must not choke on them.
    """
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": "2026-08-26T12:00:00Z",
        "source_revision": "a" * 40,
        "third_party_notices": "THIRD_PARTY_NOTICES.md",
        "entries": [
            {
                "media_type": "show",
                "title": "Breaking Bad",
                "year": 2008,
                "tmdb_id": 1396,
                "tvdb_id": 81189,
                "imdb_id": "tt0903747",
                "poster_url": "https://image.tmdb.org/t/p/original/poster.jpg",
                "background_url": "https://image.tmdb.org/t/p/original/background.jpg",
                "youtube_id_overturedb": "3U6PSWyv5sc",
                "youtube_id_themerrdb": "secondary12",
                "seasons": [
                    {
                        "season_num": 0,
                        "poster_url": "https://image.tmdb.org/t/p/original/s0.jpg",
                    },
                    {
                        "season_num": 1,
                        "poster_url": "https://image.tmdb.org/t/p/original/s1.jpg",
                    },
                ],
            },
            {
                "media_type": "movie",
                "title": "Heat",
                "year": 1995,
                "tmdb_id": 949,
                "tvdb_id": None,
                "imdb_id": "tt0113277",
                "poster_url": "https://image.tmdb.org/t/p/original/heat.jpg",
                "background_url": None,
                "youtube_id_overturedb": None,
                "youtube_id_themerrdb": None,
            },
        ],
    }


def catalog_jsonl(payload: dict[str, Any]) -> bytes:
    """Publish a fixture the way OvertureDB does: a header line, then entries."""
    header = {key: value for key, value in payload.items() if key != "entries"}
    return dump_catalog(header, payload["entries"])


def catalog_with_entry(**overrides: Any) -> dict[str, Any]:
    """Return the fixture catalog with its show entry patched."""
    payload = catalog_payload()
    payload["entries"][0] = {**payload["entries"][0], **overrides}
    return payload


def test_read_catalog_reads_the_published_entry_shape() -> None:
    show, movie = read_catalog(catalog_jsonl(catalog_payload()).splitlines())

    assert show["media_type"] == "show"
    assert show["tvdb_id"] == 81189
    assert show["youtube_id_overturedb"] == "3U6PSWyv5sc"
    assert show["youtube_id_themerrdb"] == "secondary12"
    assert [season["season_num"] for season in show["seasons"]] == [0, 1]

    assert movie["media_type"] == "movie"
    assert movie["tvdb_id"] is None
    assert movie["youtube_id_themerrdb"] is None
    assert movie.get("seasons", []) == []


def test_read_catalog_rejects_anything_but_the_contract() -> None:
    """Overture converts nothing, so a value of the wrong shape is a failed sync."""
    rejected: tuple[bytes, ...] = (
        b"",
        b"[]\n",
        b'{"entries": []}\n',
        json.dumps(catalog_payload()).encode(),
        catalog_jsonl({**catalog_payload(), "schema_version": 999}),
        catalog_jsonl({**catalog_payload(), "schema_version": SCHEMA_VERSION - 1}),
        catalog_jsonl(catalog_with_entry(media_type="unsupported")),
        catalog_jsonl(catalog_with_entry(tmdb_id="1396")),
        catalog_jsonl(catalog_with_entry(year="2008")),
        catalog_jsonl(catalog_with_entry(youtube_id_themerrdb="invalid")),
        catalog_jsonl(catalog_with_entry(youtube_id_themerrdb="secondary12\n")),
        catalog_jsonl(
            catalog_with_entry(
                youtube_id_overturedb="same_id_123",
                youtube_id_themerrdb="same_id_123",
            )
        ),
        catalog_jsonl(
            catalog_with_entry(
                seasons=[{"poster_url": "https://image.tmdb.org/t/p/original/a.jpg"}]
            )
        ),
        catalog_jsonl(catalog_payload()).replace(
            b'"title":"Heat"', b'"title":"Heat","title":"Heat"'
        ),
    )
    for content in rejected:
        with pytest.raises(ValueError, match=r".+"):
            list(read_catalog(content.splitlines()))


def test_catalog_candidate_shapes_source_and_preview() -> None:
    candidate = build_candidate(
        "https://image.tmdb.org/t/p/original/poster.jpg", ArtType.POSTER
    )

    assert candidate is not None
    assert candidate.source == "tmdb"
    assert candidate.url.endswith("/poster.jpg")
    assert candidate.preview_url == "https://image.tmdb.org/t/p/w342/poster.jpg"
    assert build_candidate(None, ArtType.POSTER) is None


async def test_download_catalog_streams_the_gzip_catalog_and_reports_stats(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        catalog_mod,
        "CATALOG_URL",
        "https://acme.github.io/db/catalog.jsonl.gz",
    )
    content = catalog_jsonl(catalog_payload())
    compressed = gzip.compress(content)

    transport = RecordingMockTransport(
        lambda _: httpx2.Response(200, content=compressed)
    )

    original_async_client = httpx2.AsyncClient

    def mock_client(*args: Any, **kwargs: Any) -> httpx2.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(staging, "create_client", mock_client)

    path = tmp_path / "catalog.jsonl"
    stats = CatalogSyncStats()
    await staging.download(path, stats)

    assert transport.called
    assert path.read_bytes() == content
    assert stats.catalog_url == "https://acme.github.io/db/catalog.jsonl.gz"
    assert stats.catalog_bytes == len(compressed)
    assert stats.schema_version == SCHEMA_VERSION


async def test_catalog_decompression_rejects_payload_over_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    compressed = gzip.compress(b"x" * 1024)
    monkeypatch.setattr(catalog_mod, "MAX_CATALOG_UNCOMPRESSED_BYTES", 100)
    monkeypatch.setattr(
        catalog_mod,
        "CATALOG_URL",
        "https://catalog.test/catalog.jsonl.gz",
    )
    transport = RecordingMockTransport(
        lambda _: httpx2.Response(200, content=compressed)
    )
    original_async_client = httpx2.AsyncClient

    def mock_client(*args: Any, **kwargs: Any) -> httpx2.AsyncClient:
        kwargs["transport"] = transport
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr(staging, "create_client", mock_client)
    with pytest.raises(ValueError, match="download failed"):
        await staging.download(tmp_path / "catalog.jsonl", CatalogSyncStats())


async def test_replace_catalog_persists_entries_field_for_field(
    db_session: AsyncSession, tmp_path: Path, *, app_config: Settings
) -> None:
    """A downloaded catalog lands in the database with nothing renamed."""
    stats = CatalogSyncStats()

    source = tmp_path / "catalog.jsonl"
    stage = tmp_path / "catalog.sqlite"
    source.write_bytes(catalog_jsonl(catalog_payload()))
    await staging.prepare(source, stage, app_config=app_config)
    await staging.replace(db_session, stage, utc_now(), stats)
    await db_session.commit()

    assert stats.items == 2
    assert stats.shows == 1
    assert stats.movies == 1
    assert stats.seasons == 2

    stored = (await db_session.exec(select(CatalogItem))).all()
    by_type = {item.media_type: item for item in stored}
    assert set(by_type) == {MediaType.MOVIE, MediaType.SHOW}

    show = by_type[MediaType.SHOW]
    assert show.title == "Breaking Bad"
    assert show.tmdb_id == 1396
    assert show.tvdb_id == 81189
    assert show.imdb_id == "tt0903747"
    assert show.youtube_id_overturedb == "3U6PSWyv5sc"
    assert show.youtube_id_themerrdb == "secondary12"
    assert show.id is not None

    seasons = await CatalogRepository(db_session).list_seasons(show.id)
    assert [season.season_num for season in seasons] == [0, 1]


BOTH = (ThemeBulkSource.OVERTUREDB, ThemeBulkSource.THEMERRDB)


def test_catalog_index_youtube_id_prefers_primary_and_falls_back() -> None:
    item1 = MediaItem(id=1, media_type=MediaType.MOVIE, title="Item 1")
    item2 = MediaItem(id=2, media_type=MediaType.MOVIE, title="Item 2")
    item3 = MediaItem(id=3, media_type=MediaType.MOVIE, title="Item 3")

    p1 = CatalogItem(
        id=10,
        media_type=MediaType.MOVIE,
        youtube_id_overturedb="primary_123",
        youtube_id_themerrdb="secondary12",
    )
    p2 = CatalogItem(
        id=20,
        media_type=MediaType.MOVIE,
        youtube_id_overturedb=None,
        youtube_id_themerrdb="secondary12",
    )
    p3 = CatalogItem(
        id=30,
        media_type=MediaType.MOVIE,
        youtube_id_overturedb=None,
        youtube_id_themerrdb=None,
    )

    index = CatalogIndex(items={1: p1, 2: p2, 3: p3}, season_posters={})

    for item, overturedb, themerrdb in (
        (item1, "primary_123", "secondary12"),
        (item2, None, "secondary12"),
        (item3, None, None),
    ):
        assert index.theme(item, [ThemeBulkSource.OVERTUREDB]).value == overturedb
        assert index.theme(item, [ThemeBulkSource.THEMERRDB]).value == themerrdb
        # The first source holding an ID wins.
        assert index.theme(item, BOTH).value == (overturedb or themerrdb)
    assert (
        index.theme(
            MediaItem(id=4, media_type=MediaType.MOVIE, title="Missing"), BOTH
        ).value
        is None
    )
    assert (
        index.theme(MediaItem(media_type=MediaType.MOVIE, title="Unsaved"), BOTH).value
        is None
    )
