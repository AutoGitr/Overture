"""Stream catalog validation through an operation-owned SQLite snapshot."""

lazy import json
lazy import sqlite3
lazy import zlib
lazy from contextlib import closing
lazy from datetime import datetime
lazy from pathlib import Path
lazy from typing import Any, cast

lazy import httpx2
lazy from sqlmodel import insert
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ...config import Settings
lazy from ...db.models.public_dataset import PublicDatasetItem, PublicDatasetSeason
lazy from ...db.session import PAGE_SIZE
lazy from ...domain import MediaType
lazy from ...integrations.http import create_client
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...schemas.public_dataset import PublicDatasetSyncStats
lazy from ...utils.threads import owned_thread
lazy from . import catalog
lazy from .schema.contract import SCHEMA_VERSION, entry_identities, read_catalog


async def download(path: Path, stats: PublicDatasetSyncStats) -> None:
    """Stream a bounded, complete gzip member to disk, noting its size in *stats*."""
    last_error: Exception | None = None
    async with create_client(follow_redirects=True) as client:
        for url in catalog.catalog_url_candidates():
            try:
                await _download_url(client, url, path, stats)
                return
            except (httpx2.HTTPError, OSError, ValueError, zlib.error) as exc:
                last_error = exc
    raise ValueError("Public dataset catalog download failed") from last_error


async def _download_url(
    client: httpx2.AsyncClient,
    url: str,
    path: Path,
    stats: PublicDatasetSyncStats,
) -> None:
    decoder = zlib.decompressobj(zlib.MAX_WBITS | 16) if url.endswith(".gz") else None
    compressed = expanded = 0
    with path.open("wb") as stream:
        async with client.stream("GET", url) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                compressed += len(chunk)
                if compressed > catalog.MAX_CATALOG_COMPRESSED_BYTES:
                    raise ValueError("Catalog exceeds compressed size limit")
                pending = chunk
                while pending:
                    data = (
                        decoder.decompress(pending, 64 * 1024) if decoder else pending
                    )
                    pending = decoder.unconsumed_tail if decoder else b""
                    expanded += len(data)
                    if expanded > catalog.MAX_CATALOG_UNCOMPRESSED_BYTES:
                        raise ValueError("Catalog exceeds decompressed size limit")
                    await owned_thread(stream.write, data)
        if decoder is not None and (not decoder.eof or decoder.unused_data):
            raise ValueError("Catalog is not one complete gzip stream")
    stats.catalog_url = url
    stats.catalog_bytes = compressed
    stats.catalog_uncompressed_bytes = expanded
    stats.schema_version = SCHEMA_VERSION


def _stage(path: Path, database: Path) -> int:
    """Validate one entry line at a time; enforce uniqueness with SQLite indexes."""
    with closing(sqlite3.connect(database)) as stage, path.open("rb") as stream:
        stage.execute(
            "CREATE TABLE entries (id INTEGER PRIMARY KEY, data TEXT NOT NULL)"
        )
        stage.execute(
            "CREATE TABLE identities (kind TEXT, provider TEXT, value TEXT, "
            "PRIMARY KEY(kind, provider, value))"
        )
        count = 0
        try:
            for count, entry in enumerate(read_catalog(stream), start=1):
                for kind, provider, value in entry_identities(entry):
                    stage.execute(
                        "INSERT INTO identities VALUES (?, ?, ?)",
                        (kind, provider, str(value)),
                    )
                stage.execute(
                    "INSERT INTO entries VALUES (?, ?)", (count, json.dumps(entry))
                )
            stage.commit()
        except sqlite3.IntegrityError as exc:
            raise ValueError("Duplicate dataset identity") from exc
    return count


def _batch(database: Path, after: int) -> list[tuple[int, dict[str, Any]]]:
    with closing(sqlite3.connect(database)) as stage:
        return [
            (int(key), cast("dict[str, Any]", json.loads(value)))
            for key, value in stage.execute(
                "SELECT id, data FROM entries WHERE id > ? ORDER BY id LIMIT ?",
                (after, PAGE_SIZE),
            )
        ]


async def prepare(path: Path, database: Path, *, app_config: Settings) -> int:
    """Finish all schema, identity and URL validation before live replacement."""
    count = await owned_thread(_stage, path, database)
    after = 0
    while batch := await owned_thread(_batch, database, after):
        await catalog.check_catalog_urls(
            [entry for _, entry in batch], app_config=app_config
        )
        after = batch[-1][0]
    return count


async def replace(
    session: AsyncSession,
    database: Path,
    synced_at: datetime,
    stats: PublicDatasetSyncStats,
) -> None:
    """Atomically replace live rows using bounded bulk inserts."""
    await PublicDatasetRepository(session).clear_catalog()
    after = 0
    while batch := await owned_thread(_batch, database, after):
        items: list[dict[str, Any]] = []
        seasons: list[dict[str, Any]] = []
        for key, entry in batch:
            values = {name: value for name, value in entry.items() if name != "seasons"}
            items.append({**values, "id": key, "catalog_synced_at": synced_at})
            seasons.extend(
                {"public_dataset_item_id": key, **season}
                for season in entry.get("seasons", [])
            )
            stats.items += 1
            if entry["media_type"] == MediaType.MOVIE:
                stats.movies += 1
            else:
                stats.shows += 1
        await session.exec(insert(PublicDatasetItem), params=items)
        if seasons:
            await session.exec(insert(PublicDatasetSeason), params=seasons)
        stats.seasons += len(seasons)
        after = batch[-1][0]
