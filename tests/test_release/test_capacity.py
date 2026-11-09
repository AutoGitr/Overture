"""Capacity budgets for the paths that scale with a user's library."""

lazy import asyncio
lazy import json
lazy import os
lazy import time
lazy import tracemalloc
lazy from collections.abc import Mapping
lazy from itertools import batched
lazy from pathlib import Path
lazy from typing import Any, cast

lazy import pytest
lazy from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
lazy from sqlmodel import func, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture import protocols
lazy from overture.config import Settings
lazy from overture.dataset_contract.contract import SCHEMA_VERSION
lazy from overture.db import metadata
lazy from overture.db.models.library import Library
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import (
    PublicDatasetItem,
    PublicDatasetSeason,
)
lazy from overture.db.session import as_writer, configure_sqlite
lazy from overture.domain import (
    CollectionOrder,
    FilterField,
    FilterOperator,
    MediaType,
    TermKind,
)
lazy from overture.media_servers.adapters import ServerItem
lazy from overture.repositories.collections import CollectionItem, CollectionRepository
lazy from overture.repositories.terms import TermRepository
lazy from overture.schemas.collections import FieldCondition, FilterGroup
lazy from overture.schemas.public_dataset import PublicDatasetSyncStats
lazy from overture.services.collections.criteria import (
    CriteriaContext,
    criteria_terms,
    evaluate,
    order_items,
)
lazy from overture.services.public_dataset import catalog, staging
lazy from overture.services.sync.reconciler import LibraryReconciler
lazy from overture.utils.time import utc_now
lazy from overture.utils.types import JsonValue
lazy from overture.ws.connection_manager import ConnectionManager
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import NoopDownloads, database_for, make_local_assets
lazy from tests.sync_helpers import sync_full
lazy from tests.test_services.test_public_dataset_edges import (
    catalog_jsonl,
    catalog_payload,
)
lazy from tests.workload import watching_the_event_loop


def _count(name: str, default: int) -> int:
    value = int(os.environ.get(name, default))
    if value < 1:
        raise ValueError(f"{name} must be positive")
    return value


async def _database(path: Path):
    engine = configure_sqlite(create_async_engine(f"sqlite+aiosqlite:///{path}"))
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
    return engine


async def test_first_sync_stays_within_time_and_memory_budgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    item_count = _count("OVERTURE_SYNC_CAPACITY_ITEMS", 1_000)
    time_budget = float(os.environ.get("OVERTURE_SYNC_BUDGET_SECONDS", "40"))
    memory_budget = 192 * 1024 * 1024
    engine = await _database(tmp_path / "sync.db")
    sessions = async_sessionmaker(
        as_writer(engine), class_=AsyncSession, expire_on_commit=False
    )
    database = database_for(sessions)
    items = [
        ServerItem(
            id=f"movie-{index}",
            title=f"Movie {index:05d}",
            year=2000 + index % 25,
            guids={},
            media_type=MediaType.MOVIE,
            poster_url=None,
            background_url=None,
            library_id="movies",
        )
        for index in range(item_count)
    ]
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    tracemalloc.start()
    started = time.perf_counter()
    try:
        result = await sync_full(reconciler, items)
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    try:
        async with sessions() as session:
            stored = (
                await session.exec(select(func.count()).select_from(MediaItem))
            ).one()
        assert result.tally.added == item_count
        assert result.tally.errors == 0
        assert stored == item_count
        assert elapsed <= time_budget, (elapsed, time_budget, item_count)
        assert peak <= memory_budget, (peak, memory_budget, item_count)
    finally:
        await engine.dispose()


async def test_catalog_import_stays_bounded_and_deduplicates_dns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    entry_count = _count("OVERTURE_CATALOG_CAPACITY_ITEMS", 3_000)
    time_budget = float(os.environ.get("OVERTURE_CATALOG_BUDGET_SECONDS", "20"))
    memory_budget = 256 * 1024 * 1024
    shared_url = "https://image.tmdb.org/t/p/original/poster.jpg"
    entries: list[dict[str, Any]] = [
        {
            "media_type": MediaType.SHOW if index % 2 else MediaType.MOVIE,
            "title": f"Title {index:05d}",
            "year": 2000 + index % 25,
            "tmdb_id": index + 1 if index % 2 == 0 else None,
            "tvdb_id": index + 1 if index % 2 else None,
            "imdb_id": None,
            "poster_url": shared_url,
            "background_url": None,
            "youtube_id_overturedb": None,
            "youtube_id_themerrdb": None,
            # Only shows have seasons.
            **(
                {"seasons": [{"season_num": 1, "poster_url": shared_url}]}
                if index % 2
                else {}
            ),
        }
        for index in range(entry_count)
    ]
    resolutions = 0

    async def public_url(url: str, **_kwargs: object) -> str:
        nonlocal resolutions
        resolutions += 1
        return url

    monkeypatch.setattr(catalog, "public_art_url", public_url)
    engine = await _database(tmp_path / "catalog.db")
    sessions = async_sessionmaker(
        as_writer(engine), class_=AsyncSession, expire_on_commit=False
    )
    stats = PublicDatasetSyncStats(entries=entry_count, schema_version=SCHEMA_VERSION)

    tracemalloc.start()
    started = time.perf_counter()
    try:
        source = tmp_path / "catalog.jsonl"
        staged = tmp_path / "catalog.sqlite"
        payload = catalog_payload()
        payload["entries"] = entries
        source.write_bytes(catalog_jsonl(payload))
        await staging.prepare(source, staged, app_config=app_config)
        async with sessions() as session:
            await staging.replace(session, staged, utc_now(), stats)
            await session.commit()
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    try:
        async with sessions() as session:
            items = (
                await session.exec(select(func.count()).select_from(PublicDatasetItem))
            ).one()
            seasons = (
                await session.exec(
                    select(func.count()).select_from(PublicDatasetSeason)
                )
            ).one()
        assert 1 <= resolutions <= (entry_count + 99) // 100
        assert items == entry_count
        assert seasons == entry_count // 2
        assert elapsed <= time_budget, (elapsed, time_budget, entry_count)
        assert peak <= memory_budget, (peak, memory_budget, entry_count)
    finally:
        await engine.dispose()


class _Snapshot:
    def __init__(self, count: int) -> None:
        self.count = count

    def capture(self) -> Mapping[str, Any]:
        return {}

    async def gather(self) -> Mapping[str, Any]:
        return {}

    def finish(
        self,
        captured: Mapping[str, Any],
        gathered: Mapping[str, Any],
        epoch: str,
        sequence: int,
    ) -> dict[str, JsonValue]:
        _ = captured, gathered
        return cast(
            "dict[str, JsonValue]",
            {
                "epoch": epoch,
                "sequence": sequence,
                "jobs": [
                    {
                        "event": "download.progress",
                        "data": {
                            "job": {"id": f"job-{index}", "status": "progress"},
                            "progress": index % 100,
                        },
                    }
                    for index in range(self.count)
                ],
            },
        )


class _Socket:
    def __init__(self) -> None:
        self.message = ""

    async def accept(self) -> None:
        return None

    async def send_text(self, data: str) -> None:
        self.message = data

    async def close(self, code: int = 1000) -> None:
        return None

    async def send_json(self, _data: Any) -> None:
        return None


async def test_large_realtime_snapshot_has_a_serialization_budget() -> None:
    snapshot_count = _count("OVERTURE_SNAPSHOT_CAPACITY_JOBS", 2_000)
    manager = ConnectionManager()
    socket = _Socket()
    await manager.connect(socket)

    tracemalloc.start()
    started = time.perf_counter()
    try:
        await manager.send_realtime_snapshot(
            cast("protocols.ClientConnection", socket), _Snapshot(snapshot_count)
        )
        elapsed = time.perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    await asyncio.sleep(0)
    await manager.close()
    envelope = json.loads(socket.message)
    assert envelope["event"] == "realtime.snapshot"
    assert len(envelope["data"]["jobs"]) == snapshot_count
    assert elapsed <= 2
    assert peak <= 64 * 1024 * 1024
    assert len(socket.message.encode()) <= 2 * 1024 * 1024


async def _rule_library(sessions: async_sessionmaker[AsyncSession], count: int) -> None:
    """Store a library whose titles hold as many values as real ones do."""
    per_title = {
        TermKind.ACTOR: 55,
        TermKind.GENRE: 3,
        TermKind.TMDB_KEYWORD: 12,
        TermKind.WRITER: 3,
        TermKind.PRODUCER: 4,
    }
    async with sessions() as session:
        session.add(Library(id="rules", media_type=MediaType.MOVIE, title="Rules"))
        await session.flush()
        session.add_all(
            MediaItem(
                id=item_id,
                media_type=MediaType.MOVIE,
                title=f"Title {item_id}",
                year=2000 + item_id % 25,
                server_item_id=f"server-{item_id}",
                library_id="rules",
            )
            for item_id in range(1, count + 1)
        )
        await session.flush()
        repo = TermRepository(session)
        for batch in batched(range(1, count + 1), 200, strict=False):
            await repo.assign_many(
                {
                    item_id: {
                        kind: [
                            f"{kind} {(item_id * 7 + place) % (count * 4)}"
                            for place in range(places)
                        ]
                        for kind, places in per_title.items()
                    }
                    for item_id in batch
                }
            )
        await session.commit()


async def test_resolving_a_rule_stays_within_time_memory_and_stall_budgets(
    tmp_path: Path,
) -> None:
    item_count = _count("OVERTURE_SYNC_CAPACITY_ITEMS", 1_000)
    time_budget = float(os.environ.get("OVERTURE_RULE_BUDGET_SECONDS", "2"))
    stall_budget = float(os.environ.get("OVERTURE_RULE_STALL_SECONDS", "0.5"))
    memory_budget = 64 * 1024 * 1024
    engine = await _database(tmp_path / "rules.db")
    sessions = async_sessionmaker(
        as_writer(engine), class_=AsyncSession, expire_on_commit=False
    )
    database = database_for(sessions)
    criteria = FilterGroup(
        conditions=[
            FieldCondition(
                field=FilterField.ACTOR,
                operator=FilterOperator.IS,
                value=f"{TermKind.ACTOR} 21",
            )
        ]
    )
    context = CriteriaContext(sources={}, collections={}, now=utc_now())

    async def resolve() -> list[CollectionItem]:
        async with database.read_session() as session:
            items = await CollectionRepository(session).library_items(
                MediaType.MOVIE, "rules", criteria_terms([criteria])
            )
        return order_items(
            evaluate(items, criteria, context), CollectionOrder.TITLE_ASC
        )

    try:
        await _rule_library(sessions, item_count)
        started = time.perf_counter()
        async with watching_the_event_loop() as stall:
            matched = await resolve()
        elapsed = time.perf_counter() - started

        tracemalloc.start()
        try:
            await resolve()
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()

        assert matched
        assert elapsed <= time_budget, (elapsed, time_budget, item_count)
        assert stall.longest <= stall_budget, (stall.longest, item_count)
        assert peak <= memory_budget, (peak, memory_budget, item_count)
    finally:
        await engine.dispose()
