"""Catalog imports validate and resolve a complete snapshot before replacing it."""

lazy import asyncio
lazy import gzip
lazy from collections import Counter
lazy from pathlib import Path
lazy from typing import Any

lazy import httpx2
lazy import pytest
lazy from sqlalchemy.exc import SQLAlchemyError
lazy from sqlalchemy.ext.asyncio import async_sessionmaker
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.public_dataset import PublicDatasetItem
lazy from overture.schemas.public_dataset import PublicDatasetSyncStats
lazy from overture.services.public_dataset import catalog, staging
lazy from overture.services.public_dataset.schema.contract import SCHEMA_VERSION
lazy from overture.services.public_dataset.service import PublicDatasetService
lazy from overture.services.schedule_store import PUBLIC_DATASET_SCHEDULE, load_schedule
lazy from overture.services.scheduler import SchedulerService
lazy from overture.utils.time import utc_now
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import JobProbe, database_for
lazy from tests.test_services.test_public_dataset_edges import (
    catalog_jsonl,
    catalog_payload,
)

pytestmark = pytest.mark.usefixtures("public_art_hosts")


@pytest.mark.parametrize(
    "content",
    [
        gzip.compress(b"{}")[0:-4],
        gzip.compress(b"{}") + b"trailing",
        gzip.compress(b"{}") * 2,
    ],
)
async def test_gzip_requires_one_complete_bounded_stream(
    content: bytes, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    transport = httpx2.MockTransport(
        lambda _request: httpx2.Response(200, content=content)
    )
    monkeypatch.setattr(
        catalog,
        "catalog_url_candidates",
        lambda: ["https://catalog.test/catalog.jsonl.gz"],
    )

    def mock_client(**_kwargs: object) -> httpx2.AsyncClient:
        return httpx2.AsyncClient(transport=transport)

    monkeypatch.setattr(staging, "create_client", mock_client)
    with pytest.raises(ValueError, match="download failed"):
        await staging.download(tmp_path / "catalog.jsonl", PublicDatasetSyncStats())


async def test_url_checks_deduplicate_urls_and_dns_with_bounded_concurrency(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    calls: Counter[str] = Counter()
    active = peak = 0

    async def resolve(host: str, *_args: Any, **_kwargs: Any) -> list[Any]:
        nonlocal active, peak
        calls[host] += 1
        active += 1
        peak = max(active, peak)
        await asyncio.sleep(0)
        active -= 1
        return [(2, 1, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(asyncio.get_running_loop(), "getaddrinfo", resolve)
    movie = catalog_payload()["entries"][1]
    entries = [
        {
            **movie,
            "tmdb_id": index + 1,
            "poster_url": f"https://art{index % 20}.test/{index % 40}.jpg",
            "background_url": f"https://art{index % 20}.test/{index % 40}.jpg",
        }
        for index in range(80)
    ]
    await catalog.check_catalog_urls(entries, app_config=app_config)
    assert 1 < peak <= 16
    assert calls == Counter({f"art{index}.test": 1 for index in range(20)})
    await catalog.check_catalog_urls(entries, app_config=app_config)
    assert set(calls.values()) == {2}


@pytest.mark.parametrize("failure", ["validation", "unsafe_url", "database", None])
async def test_catalog_replacement_is_atomic(
    failure: str | None,
    isolated_session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    app_config: Settings,
) -> None:
    database = database_for(isolated_session_factory)
    service = PublicDatasetService(
        scheduler=SchedulerService(app_config=app_config),
        publisher=NullEventPublisher(),
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )
    original = catalog_payload()
    original_path = tmp_path / "original.jsonl"
    original_stage = tmp_path / "original.sqlite"
    original_path.write_bytes(catalog_jsonl(original))
    await staging.prepare(original_path, original_stage, app_config=app_config)
    async with isolated_session_factory() as session:
        await staging.replace(
            session, original_stage, utc_now(), PublicDatasetSyncStats()
        )
        await session.commit()

    incoming = catalog_payload()
    incoming["entries"][0]["title"] = "Updated show"
    incoming["entries"][1]["title"] = "Updated movie"
    if failure == "validation":
        incoming["entries"][1]["tmdb_id"] = 0
    elif failure == "unsafe_url":
        incoming["entries"][1]["poster_url"] = "https://127.0.0.1/private.jpg"

    async def download(path: Path, stats: PublicDatasetSyncStats) -> None:
        await asyncio.to_thread(path.write_bytes, catalog_jsonl(incoming))
        stats.catalog_url = "https://catalog.test/catalog.jsonl.gz"
        stats.schema_version = SCHEMA_VERSION

    monkeypatch.setattr(staging, "download", download)
    if failure == "database":
        replace = staging.replace

        async def failing_replace(*args: Any, **kwargs: Any) -> None:
            await replace(*args, **kwargs)
            raise SQLAlchemyError("Injected write failure before commit")

        monkeypatch.setattr(staging, "replace", failing_replace)

    probe = JobProbe(lifecycle=service.job.lifecycle)
    await service.run_sync(probe.context)
    event, payload = probe.terminal()
    assert event == (
        "public-dataset.sync.failed" if failure else "public-dataset.sync.completed"
    )
    async with isolated_session_factory() as session:
        rows = (await session.exec(select(PublicDatasetItem))).all()
        assert {row.title for row in rows} == (
            {"Breaking Bad", "Heat"} if failure else {"Updated show", "Updated movie"}
        )
        schedule = await load_schedule(session, PUBLIC_DATASET_SCHEDULE)
        assert schedule.payload.last_status == ("failed" if failure else "success")
        assert bool(schedule.payload.last_synced_at) is (failure is None)
        assert payload["stats"]["items"] == (0 if failure else 2)
