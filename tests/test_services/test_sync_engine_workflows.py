"""Sync engine workflow and scheduler tests."""

lazy import asyncio
lazy import threading
lazy from collections.abc import AsyncIterator, Callable
lazy from dataclasses import replace
lazy from datetime import UTC, datetime
lazy from pathlib import Path
lazy from typing import Any, override

lazy import pytest
lazy from pydantic import SecretStr
lazy from sqlmodel import col, select

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.saved_schedule import SavedSchedule
lazy from overture.db.session import Database
lazy from overture.domain import MediaType, ServerType
lazy from overture.integrations.tmdb import TMDBClient, TmdbDetails
lazy from overture.jobs.gate import LibraryGate
lazy from overture.jobs.progress_log import JobLogEntry, JobOutcome, log_entry
lazy from overture.jobs.runner import JobContext
lazy from overture.jobs.tally import SyncTally
lazy from overture.media_servers.adapters import (
    MAX_SEASONS_PER_SHOW,
    ServerCollection,
    ServerItem,
    ServerSeason,
    SyncProgressCallback,
    SyncStopCheck,
)
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.schemas.sync import SyncScheduleConfig, SyncScheduleWrite
lazy from overture.services.art.phash import PhashService
lazy from overture.services.local_assets.service import LocalAssets
lazy from overture.services.public_dataset.downloads import QueuedDownloads
lazy from overture.services.scheduler import SchedulerService
lazy from overture.services.sync import engine as module
lazy from overture.services.sync import runner as sync_runner_module
lazy from overture.services.sync.collection_sync import CollectionSync
lazy from overture.services.sync.engine import SyncEngine
lazy from overture.services.sync.reconciler import LibraryReconciler, SyncResult
lazy from overture.services.sync.staging import StagedListing
lazy from overture.services.sync.tmdb_seasons import TmdbSeasonSync
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    JobProbe,
    NoopDownloads,
    NoopProviderRegistry,
    RecordingPublisher,
    make_local_assets,
    unused,
)
lazy from tests.sync_helpers import sync_full


def normalized_items() -> list[ServerItem]:
    return [
        ServerItem(
            id="server-42",
            title="Forwarded movie",
            year=2026,
            guids={"tmdb": "42"},
            media_type=MediaType.MOVIE,
            poster_url=None,
            background_url=None,
            server_link="https://server.test/42",
            library_id="1",
        )
    ]


class FakeProvider:
    server_type = ServerType.PLEX

    def __init__(self) -> None:
        self.items = normalized_items()
        self.collections: list[ServerCollection] = []
        self.calls: list[dict[str, Any]] = []

    async def list_collections(self) -> list[ServerCollection]:
        return self.collections

    async def iter_items(
        self,
        library_ids: list[str] | None = None,
    ) -> AsyncIterator[list[ServerItem]]:
        self.calls.append({"library_ids": library_ids})
        yield self.items

    async def iter_items_since(
        self,
        since: datetime,
        library_ids: list[str] | None = None,
    ) -> AsyncIterator[list[ServerItem]]:
        yield self.items

    async def get_directors(self, server_item_ids: list[str]) -> dict[str, str | None]:
        raise AssertionError("Plex items carry their directors")


async def test_staged_listing_rejects_duplicate_ids_across_pages(
    tmp_path: Path,
) -> None:
    item = normalized_items()[0]
    async with StagedListing(tmp_path / "provider.sqlite") as listing:
        await listing.append([item])
        with pytest.raises(ValueError, match="duplicate item IDs"):
            await listing.append([replace(item, id="server-43"), item])
        # The rejected page rolls back whole, not up to its duplicate.
        assert await listing.count() == 1


async def test_staged_listing_rejects_unbounded_show_seasons(tmp_path: Path) -> None:
    show = replace(
        normalized_items()[0],
        media_type=MediaType.SHOW,
        seasons=[ServerSeason(num=1)] * (MAX_SEASONS_PER_SHOW + 1),
    )
    async with StagedListing(tmp_path / "provider.sqlite") as listing:
        with pytest.raises(MediaServerError, match="too many seasons"):
            await listing.append([show])
        assert await listing.count() == 0


async def test_staged_listing_closes_when_cancelled_while_opening(
    tmp_path: Path,
) -> None:
    opened = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()

    class DelayedListing(StagedListing):
        @override
        def _create(self) -> None:
            super()._create()
            loop.call_soon_threadsafe(opened.set)
            release.wait()

    listing = DelayedListing(tmp_path / "provider.sqlite")

    async def stage() -> None:
        async with listing:
            raise AssertionError("Cancelled listing must not be entered")

    task = asyncio.create_task(stage())
    try:
        await asyncio.wait_for(opened.wait(), 2)
        task.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    with pytest.raises(RuntimeError, match="not open"):
        _ = listing.connection


async def test_staged_sync_assigns_shared_guid_items_to_distinct_rows(
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.MOVIE,
                title="Movie",
                tmdb_id=42,
                server_item_id="old-server-id",
            )
        )
    first = normalized_items()[0]
    second = replace(first, id="server-43")
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )
    async with StagedListing(tmp_path / "provider.sqlite") as listing:
        await listing.append([first, second])
        result = await reconciler.sync_staged(
            listing,
            library_ids=None,
            tally=SyncTally(),
            progress_cb=None,
            stop_check=None,
        )
        assert result.tally.errors == 0
        assert result.tally.done == 2
        assert await listing.is_mapped(1)
        assert await listing.is_mapped(2)


@pytest.mark.parametrize("method", ["sync_full", "sync_recent"])
async def test_listed_sync_skips_rows_it_already_claimed(
    method: str,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.MOVIE,
                title="Movie",
                tmdb_id=42,
                server_item_id="old-server-id",
            )
        )
    first = normalized_items()[0]
    second = replace(first, id="server-43")
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )

    items = [first, second]
    result = await (
        sync_full(reconciler, items)
        if method == "sync_full"
        else reconciler.sync_recent(items)
    )

    assert result.tally.errors == 0
    assert result.tally.done == 2
    async with database.read_session() as session:
        rows = (await session.exec(select(MediaItem).order_by(col(MediaItem.id)))).all()
    assert [(row.id, row.server_item_id) for row in rows] == [
        (1, "server-42"),
        (2, "server-43"),
    ]


async def test_staged_sync_stamps_items_and_reports_changes_stamped(
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    unchanged = normalized_items()[0]
    changed = replace(unchanged, id="server-43", title="New title", guids={})
    async with database.write_session() as session:
        session.add_all(
            [
                MediaItem(
                    id=1,
                    media_type=MediaType.MOVIE,
                    title=unchanged.title,
                    year=unchanged.year,
                    tmdb_id=42,
                    server_item_id=unchanged.id,
                    server_link=unchanged.server_link,
                    library_id=unchanged.library_id,
                ),
                MediaItem(
                    id=2,
                    media_type=MediaType.MOVIE,
                    title="Old title",
                    year=changed.year,
                    server_item_id=changed.id,
                    server_link=changed.server_link,
                    library_id=changed.library_id,
                ),
            ]
        )
    publisher = RecordingPublisher()
    reconciler = LibraryReconciler(
        publisher=publisher,
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=NoopDownloads(),
        app_config=app_config,
        database=database,
    )
    async with StagedListing(tmp_path / "provider.sqlite") as listing:
        await listing.append([unchanged, changed])
        result = await reconciler.sync_staged(
            listing,
            library_ids=None,
            tally=SyncTally(),
            progress_cb=None,
            stop_check=None,
        )

    assert (result.tally.unchanged, result.tally.updated) == (1, 1)
    async with database.read_session() as session:
        items = (await session.exec(select(MediaItem))).all()
    assert all(item.server_verified_at and item.last_synced_at for item in items)
    # The changed item's event already carries the stamp its art URLs use.
    [upserted] = [
        payload
        for event, payload in publisher.events
        if event == "library.item.upserted"
    ]
    assert upserted["item"]["id"] == 2
    assert upserted["item"]["last_synced_at"] is not None


async def test_partial_provider_listing_cannot_reconcile(tmp_path: Path) -> None:
    class PartialProvider(FakeProvider):
        @override
        async def iter_items(
            self, library_ids: list[str] | None = None
        ) -> AsyncIterator[list[ServerItem]]:
            yield self.items
            raise OSError("second page failed")

    class Reconciler(FakeReconciler):
        @override
        async def sync_staged(self, *_args: Any, **_kwargs: Any) -> SyncResult:
            raise AssertionError("Partial provider listing reached reconciliation")

    probe = JobProbe()
    await sync_runner_module.run_sync(
        probe.context,
        provider_registry=NoopProviderRegistry(PartialProvider()),
        reconciler=Reconciler(),
        config_dir=tmp_path,
        tmdb_seasons=NoTmdbShows(),
        collections=NoCollections(),
    )
    assert probe.names()[-1] == "sync.failed"


class NoCollections(CollectionSync):
    def __init__(self) -> None:
        pass

    @override
    async def run(self, *_args: object, **_kwargs: object) -> None:
        return None


class NoTmdbShows(TmdbSeasonSync):
    def __init__(self) -> None:
        pass

    @override
    async def targets(self) -> list[MediaItem]:
        return []


class FakeReconciler(LibraryReconciler):
    def __init__(self) -> None:
        pass

    @override
    async def sync_staged(
        self,
        listing: Any,
        *,
        library_ids: list[str] | None,
        tally: SyncTally,
        progress_cb: SyncProgressCallback | None,
        stop_check: SyncStopCheck | None,
    ) -> SyncResult:
        rows = await listing.batch(0)
        return await self.reconcile_listed(
            [item for _, item in rows],
            library_ids=library_ids,
            tally=tally,
            progress_cb=progress_cb,
            stop_check=stop_check,
        )

    async def reconcile_listed(
        self,
        server_items: list[ServerItem],
        *,
        library_ids: list[str] | None = None,
        tally: SyncTally | None = None,
        progress_cb: SyncProgressCallback | None = None,
        stop_check: SyncStopCheck | None = None,
    ) -> SyncResult:
        assert server_items == normalized_items()
        assert library_ids == ["1"]
        assert stop_check is not None
        assert stop_check() is False
        if progress_cb:
            assert tally is not None
            tally.done = 1
            tally.added = 1
            tally.unchanged = 0
            tally.errors = 0
            await progress_cb(log_entry(JobOutcome.ADDED, "One", "pulled"))
            assert tally is not None
            tally.done = 2
            tally.added = 1
            tally.unchanged = 1
            tally.errors = 0
            await progress_cb(log_entry(JobOutcome.UNCHANGED, "Two", "checked"))
        return SyncResult(
            tally=SyncTally(added=1, unchanged=1, errors=0),
            created_item_ids=[42],
        )

    @override
    async def sync_recent(
        self,
        server_items: list[ServerItem],
        *,
        tally: SyncTally | None = None,
        progress_cb: SyncProgressCallback | None = None,
        stop_check: SyncStopCheck | None = None,
    ) -> SyncResult:
        raise AssertionError("sync_recent was not expected")


def make_engine(
    provider: FakeProvider | None = None,
    publisher: NullEventPublisher | None = None,
    scheduler: SchedulerService | None = None,
    *,
    app_config: Settings,
    database: Database,
    config_dir: Path,
) -> SyncEngine:
    return SyncEngine(
        tmdb_client=unused(TMDBClient),
        config_dir=config_dir,
        downloads=NoopDownloads(),
        provider_registry=NoopProviderRegistry(provider),
        scheduler=scheduler or SchedulerService(app_config=app_config),
        publisher=publisher or NullEventPublisher(),
        library_gate=LibraryGate(),
        local_assets=unused(LocalAssets),
        app_config=app_config,
        database=database,
    )


@pytest.mark.parametrize("mode", ["full", "incremental"])
async def test_sync_schedule_waits_for_a_busy_slot(
    tmp_path: Path,
    mode: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    publisher = RecordingPublisher()
    engine = make_engine(
        publisher=publisher,
        app_config=app_config,
        database=database,
        config_dir=tmp_path,
    )
    order: list[str] = []
    release = asyncio.Event()

    async def manual(_context: JobContext) -> None:
        order.append("manual")
        await release.wait()

    async def run_scheduled(_context: JobContext) -> None:
        order.append(mode)

    def full_sync(
        _library_ids: list[str] | None, *, include_collections: bool = True
    ) -> Callable[..., Any]:
        return run_scheduled

    async def poll(*_args: object) -> None:
        order.append(mode)

    monkeypatch.setattr(engine, "_full_sync", full_sync)
    monkeypatch.setattr(engine, "_poll_new_media", poll)
    body = SyncScheduleWrite(
        name="Scheduled",
        cron_expression="0 3 * * *",
        config=SyncScheduleConfig.model_validate({"mode": mode}),
    )
    schedule = await engine.schedules.create(body)

    assert engine.job.start_with_context(manual)
    await engine.schedules.run_now(schedule.id)

    async def waiting_for_the_slot() -> bool:
        return [entry.run_status for entry in await engine.schedules.all()] == [
            "waiting"
        ]

    async with asyncio.timeout(2):
        await publisher.wait_until(waiting_for_the_slot)
    assert order == ["manual"]

    release.set()
    await asyncio.wait_for(engine.schedules.wait_for_pending_runs(), timeout=2)
    assert order == ["manual", mode]
    await engine.schedules.stop()


async def test_run_sync_broadcasts_progress_and_saves_completed_snapshot(
    tmp_path: Path,
) -> None:
    """run_sync drives its lifecycle through the managed job context."""
    provider = FakeProvider()
    probe = JobProbe()

    await sync_runner_module.run_sync(
        probe.context,
        library_ids=["1"],
        provider_registry=NoopProviderRegistry(provider),
        reconciler=FakeReconciler(),
        config_dir=tmp_path,
        tmdb_seasons=NoTmdbShows(),
        collections=NoCollections(),
    )

    assert provider.calls == [{"library_ids": ["1"]}]
    assert probe.names() == [
        "sync.started",
        "sync.progress",
        "sync.progress",
        "sync.progress",
        "sync.progress",
        "sync.completed",
    ]
    assert "total" not in probe.events[0][1]
    # The staged listing fixes the total before the first item is reconciled.
    listed = len(normalized_items())
    assert probe.events[2][1]["total"] == listed
    assert probe.events[2][1]["done"] == 0
    assert (
        JobLogEntry.model_validate(probe.events[3][1]["log"]).format()
        == "Added One - pulled"
    )
    assert (
        JobLogEntry.model_validate(probe.events[4][1]["log"]).format()
        == "Unchanged Two - checked"
    )
    assert {payload["total"] for _, payload in probe.events[2:]} == {listed}

    last_event, last_payload = probe.terminal()
    assert last_event == "sync.completed"
    assert last_payload["done"] == 2
    assert last_payload["added"] == 1
    assert last_payload["unchanged"] == 1
    assert last_payload["errors"] == 0
    assert last_payload["finished_at"]
    assert last_payload["job"]["status"] == "completed"


async def test_run_sync_progress_counters_survive_a_throttled_callback(
    tmp_path: Path,
) -> None:
    """A quiet item reported once per ten must still count as ten unchanged.

    The reconciler only calls back on every tenth up-to-date item, so counting
    callbacks understated 'unchanged' by 10x until the terminal event corrected
    it. The counters travel with the report, so they cannot drift.
    """

    class ThrottledProvider(FakeProvider):
        @override
        async def iter_items(
            self,
            library_ids: list[str] | None = None,
        ) -> AsyncIterator[list[ServerItem]]:
            yield []

    class ThrottledReconciler(FakeReconciler):
        @override
        async def reconcile_listed(
            self,
            server_items: list[ServerItem],
            *,
            library_ids: list[str] | None = None,
            tally: SyncTally | None = None,
            progress_cb: SyncProgressCallback | None = None,
            stop_check: SyncStopCheck | None = None,
        ) -> SyncResult:
            assert progress_cb is not None
            assert tally is not None
            tally.done = 10
            tally.total = 100
            tally.added = 0
            tally.unchanged = 10
            tally.errors = 0
            await progress_cb(log_entry(JobOutcome.UNCHANGED, "Quiet", "no change"))
            return SyncResult(
                tally=SyncTally(added=0, unchanged=10, errors=0),
                created_item_ids=[],
            )

    probe = JobProbe()

    await sync_runner_module.run_sync(
        probe.context,
        provider_registry=NoopProviderRegistry(ThrottledProvider()),
        reconciler=ThrottledReconciler(),
        config_dir=tmp_path,
        tmdb_seasons=NoTmdbShows(),
        collections=NoCollections(),
    )

    _, progress_payload = probe.events[-2]
    assert progress_payload["unchanged"] == 10
    assert progress_payload["done"] == 10


class QuietProvider(FakeProvider):
    """Provider that reconciles nothing and never inspects the stop check."""

    @override
    async def iter_items(
        self,
        library_ids: list[str] | None = None,
    ) -> AsyncIterator[list[ServerItem]]:
        yield []


class QuietReconciler(FakeReconciler):
    @override
    async def reconcile_listed(
        self,
        server_items: list[ServerItem],
        *,
        library_ids: list[str] | None = None,
        tally: SyncTally | None = None,
        progress_cb: SyncProgressCallback | None = None,
        stop_check: SyncStopCheck | None = None,
    ) -> SyncResult:
        return SyncResult(
            tally=SyncTally(added=0, unchanged=0, errors=0),
            created_item_ids=[],
        )


async def test_run_sync_reports_stopped_when_cancellation_is_requested(
    tmp_path: Path,
) -> None:
    """A cancelled run must end 'stopped', not 'completed'."""
    probe = JobProbe(stop_requested=True)

    await sync_runner_module.run_sync(
        probe.context,
        provider_registry=NoopProviderRegistry(QuietProvider()),
        reconciler=QuietReconciler(),
        config_dir=tmp_path,
        tmdb_seasons=NoTmdbShows(),
        collections=NoCollections(),
    )

    assert probe.names()[-1] == "sync.stopped"
    _, payload = probe.terminal()
    assert payload["job"]["status"] == "stopped"


async def test_run_sync_provider_error_fails_the_job(tmp_path: Path) -> None:
    """A provider error is reported as an error count, not a failed run.

    The reconciliation error is handled inside the run so partial progress is
    still reported; only an error outside that boundary fails the job.
    """

    class ExplodingProvider(FakeProvider):
        @override
        async def iter_items(
            self,
            library_ids: list[str] | None = None,
        ) -> AsyncIterator[list[ServerItem]]:
            raise ValueError("provider exploded")
            yield []

    probe = JobProbe()

    await sync_runner_module.run_sync(
        probe.context,
        provider_registry=NoopProviderRegistry(ExplodingProvider()),
        reconciler=FakeReconciler(),
        config_dir=tmp_path,
        tmdb_seasons=NoTmdbShows(),
        collections=NoCollections(),
    )

    assert probe.names()[-1] == "sync.failed"
    _, payload = probe.terminal()
    assert payload["errors"] == 1


async def test_run_sync_reports_failed_when_the_run_itself_raises(
    tmp_path: Path,
) -> None:
    """An error outside the reconciliation boundary ends the job 'failed'."""

    class ExplodingRegistry(NoopProviderRegistry):
        @property
        @override
        def provider(self) -> Any:
            raise ValueError("registry unavailable")

    probe = JobProbe()

    await sync_runner_module.run_sync(
        probe.context,
        provider_registry=ExplodingRegistry(),
        reconciler=FakeReconciler(),
        config_dir=tmp_path,
        tmdb_seasons=NoTmdbShows(),
        collections=NoCollections(),
    )

    assert probe.names()[-1] == "sync.failed"
    _, payload = probe.terminal()
    assert payload["errors"] == 1
    assert payload["job"]["error"]["message"]


async def test_start_background_sync_rejects_duplicate_running_task(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    engine = make_engine(
        FakeProvider(), app_config=app_config, database=database, config_dir=tmp_path
    )
    release = asyncio.Event()

    async def slow_sync(_context: JobContext, **kwargs: Any) -> None:
        await release.wait()

    # Patch the module-level _run_sync name that start_background_sync calls.
    monkeypatch.setattr(module, "_run_sync", slow_sync)
    assert engine.start_background_sync(library_ids=["1"]) is True
    assert engine.job.running is True
    assert engine.start_background_sync(library_ids=["1"]) is False

    release.set()
    task = engine.job.task
    if task is not None:
        await task
    await engine.job.wait_idle()
    assert engine.job.running is False


@pytest.mark.parametrize("phase", ["collection listing", "TMDB collection lookup"])
async def test_full_sync_stop_interrupts_collection_requests_and_frees_the_slot(
    phase: str,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    entered = asyncio.Event()
    cancelled = asyncio.Event()
    app_config.TMDB_API_KEY = SecretStr("key")

    async def wait_for_cancel() -> None:
        entered.set()
        try:
            await asyncio.Future[None]()
        finally:
            cancelled.set()

    class Provider(FakeProvider):
        @override
        async def list_collections(self) -> list[ServerCollection]:
            if phase == "collection listing":
                await wait_for_cancel()
            return [
                ServerCollection(
                    id="saga",
                    title="Saga",
                    server_link="https://server.test/saga",
                    member_ids=("server-42",),
                    media_type=MediaType.MOVIE,
                )
            ]

    class Tmdb(TMDBClient):
        def __init__(self) -> None:
            pass

        @override
        async def get_details(
            self, media_type: MediaType, tmdb_id: int
        ) -> TmdbDetails | None:
            await wait_for_cancel()
            return None

    publisher = RecordingPublisher()
    engine = SyncEngine(
        tmdb_client=Tmdb(),
        config_dir=tmp_path,
        downloads=NoopDownloads(),
        provider_registry=NoopProviderRegistry(Provider()),
        scheduler=SchedulerService(app_config=app_config),
        publisher=publisher,
        library_gate=LibraryGate(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        app_config=app_config,
        database=database,
    )
    try:
        assert engine.start_background_sync()
        await asyncio.wait_for(entered.wait(), 3)
        assert engine.job.request_stop()
        await asyncio.wait_for(engine.job.wait_idle(), 2)
        assert cancelled.is_set()
        assert not engine.job.running
        terminal = [
            name
            for name, _ in publisher.events
            if name in {"sync.completed", "sync.failed", "sync.stopped"}
        ]
        assert terminal == ["sync.stopped"]
    finally:
        await engine.stop()


@pytest.mark.parametrize("failure", [None, "fetch", "reconcile", "partial", "cancel"])
async def test_incremental_sync_forwards_items_and_preserves_failed_checkpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
    failure: str | None,
) -> None:
    checkpoint = datetime(2026, 1, 1, tzinfo=UTC)
    now = datetime(2026, 2, 1, tzinfo=UTC)
    monkeypatch.setattr(module, "utc_now", lambda: now)
    items = normalized_items()
    reconciled: list[list[ServerItem]] = []
    queued: list[list[int]] = []

    class Provider(FakeProvider):
        @override
        async def iter_items_since(
            self, since: datetime, library_ids: list[str] | None = None
        ) -> AsyncIterator[list[ServerItem]]:
            assert since == checkpoint
            assert library_ids == ["movies"]
            if failure == "cancel":
                raise asyncio.CancelledError
            if failure == "fetch":
                raise OSError("provider enumeration failed")
            yield items

    engine = make_engine(
        Provider(), app_config=app_config, database=database, config_dir=tmp_path
    )

    async def recent(server_items: list[ServerItem], **kwargs: Any) -> SyncResult:
        assert server_items is items
        reconciled.append(server_items)
        if failure == "reconcile":
            raise OSError("outer reconciliation failed")
        tally: SyncTally = kwargs["tally"]
        tally.added += 2
        tally.unchanged += 1
        tally.errors += int(failure == "partial")
        return SyncResult(tally=tally, created_item_ids=[10, 12])

    async def downloads(item_ids: list[int], **kwargs: Any) -> QueuedDownloads:
        assert kwargs["database"] is database
        assert kwargs["downloads"] is engine.downloads
        assert kwargs["include_art"] is True
        assert kwargs["theme_order"] == "off"
        queued.append(item_ids)
        return QueuedDownloads(art=1)

    monkeypatch.setattr(engine.reconciler, "sync_recent", recent)
    monkeypatch.setattr(module, "queue_overturedb_downloads_for_items", downloads)
    body = SyncScheduleWrite(
        name="New media",
        cron_expression="*/15 * * * *",
        config=SyncScheduleConfig(
            mode="incremental", library_ids=["movies"], download_overturedb_art=True
        ),
    )
    schedule = await engine.schedules.create(body)
    async with database.write_session() as session:
        record = await session.get(SavedSchedule, schedule.id)
        assert record is not None
        record.state = {"checkpoint": checkpoint.isoformat()}
        session.add(record)

    await engine.schedules.run_now(schedule.id)
    await asyncio.wait_for(engine.schedules.wait_for_pending_runs(), timeout=2)
    await engine.job.wait_idle()

    assert bool(reconciled) is (failure not in {"fetch", "cancel"})
    assert queued == ([[10, 12]] if failure in {None, "partial"} else [])
    [saved] = await engine.schedules.all()
    assert saved.state.checkpoint == (now if failure is None else checkpoint)
    if failure is None:
        assert saved.state.last_duration_seconds is not None
        assert saved.state.last_items_added == 2
        assert saved.state.last_downloads == 1
    await engine.schedules.stop()


async def test_first_incremental_poll_only_sets_the_checkpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    app_config: Settings,
    database: Database,
) -> None:
    now = datetime(2026, 2, 1, tzinfo=UTC)
    monkeypatch.setattr(module, "utc_now", lambda: now)

    class Provider(FakeProvider):
        @override
        async def iter_items_since(
            self, since: datetime, library_ids: list[str] | None = None
        ) -> AsyncIterator[list[ServerItem]]:
            raise AssertionError("the first poll must not enumerate the server")
            yield []

    engine = make_engine(
        Provider(), app_config=app_config, database=database, config_dir=tmp_path
    )
    body = SyncScheduleWrite(
        name="New media",
        cron_expression="*/15 * * * *",
        config=SyncScheduleConfig(mode="incremental"),
    )
    schedule = await engine.schedules.create(body)

    await engine.schedules.run_now(schedule.id)
    await asyncio.wait_for(engine.schedules.wait_for_pending_runs(), timeout=2)

    [saved] = await engine.schedules.all()
    assert saved.state.checkpoint == now
    assert saved.state.last_items_added is None
    assert saved.last_run_at is not None
    await engine.schedules.stop()


@pytest.mark.parametrize("boundary", ["fetch", "reconcile", "registry"])
async def test_full_sync_oserror_has_one_terminal_event(
    tmp_path: Path, boundary: str
) -> None:
    class Provider(FakeProvider):
        @override
        async def iter_items(
            self, library_ids: list[str] | None = None
        ) -> AsyncIterator[list[ServerItem]]:
            if boundary == "fetch":
                raise OSError("enumeration failed")
            yield self.items

    class Reconciler(FakeReconciler):
        @override
        async def reconcile_listed(
            self, server_items: list[ServerItem], **kwargs: Any
        ) -> SyncResult:
            assert boundary != "fetch", (
                "failed enumeration must never reconcile or remove items"
            )
            assert server_items == normalized_items()
            raise OSError("outer reconciliation failed")

    class Registry(NoopProviderRegistry):
        @property
        @override
        def provider(self) -> Any:
            if boundary == "registry":
                raise OSError("registry failed")
            return Provider()

    probe = JobProbe()
    await sync_runner_module.run_sync(
        probe.context,
        library_ids=["1"],
        provider_registry=Registry(),
        reconciler=Reconciler(),
        config_dir=tmp_path,
        tmdb_seasons=NoTmdbShows(),
        collections=NoCollections(),
    )
    event, payload = probe.terminal()
    assert event == "sync.failed"
    assert payload["errors"] == 1
    assert (
        len(
            [
                name
                for name in probe.names()
                if name in {"sync.completed", "sync.stopped", "sync.failed"}
            ]
        )
        == 1
    )


@pytest.mark.parametrize("fetch_fails", [False, True])
async def test_full_engine_reconciles_normalized_items_only_after_successful_fetch(
    tmp_path: Path,
    app_config: Settings,
    database: Database,
    fetch_fails: bool,
) -> None:
    async with database.write_session() as session:
        session.add_all(
            [
                MediaItem(
                    id=1,
                    media_type=MediaType.MOVIE,
                    title="Old",
                    library_id="1",
                    server_item_id="old",
                ),
                MediaItem(
                    id=2,
                    media_type=MediaType.MOVIE,
                    title="Outside",
                    library_id="2",
                    server_item_id="outside",
                ),
            ]
        )

    class Provider(FakeProvider):
        @override
        async def iter_items(
            self, library_ids: list[str] | None = None
        ) -> AsyncIterator[list[ServerItem]]:
            assert library_ids == ["1"]
            if fetch_fails:
                raise OSError("enumeration failed")
            yield self.items

    publisher = RecordingPublisher()
    phash = PhashService(app_config=app_config)
    engine = SyncEngine(
        tmdb_client=unused(TMDBClient),
        config_dir=tmp_path,
        downloads=NoopDownloads(),
        provider_registry=NoopProviderRegistry(Provider()),
        scheduler=SchedulerService(app_config=app_config),
        publisher=publisher,
        library_gate=LibraryGate(),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        app_config=app_config,
        database=database,
    )
    try:
        assert engine.start_background_sync(library_ids=["1"])
        task = engine.job.task
        assert task is not None
        await asyncio.wait_for(task, 3)
        async with database.read_session() as session:
            rows = {
                item.server_item_id: item
                for item in (await session.exec(select(MediaItem))).all()
            }
        assert rows["outside"].server_removed_at is None
        assert (rows["old"].server_removed_at is not None) is (not fetch_fails)
        assert ("server-42" in rows) is (not fetch_fails)
        if not fetch_fails:
            item = rows["server-42"]
            assert (item.title, item.year, item.tmdb_id, item.library_id) == (
                "Forwarded movie",
                2026,
                42,
                "1",
            )
        terminal = [
            (name, payload)
            for name, payload in publisher.events
            if name in {"sync.completed", "sync.failed", "sync.stopped"}
        ]
        assert len(terminal) == 1
        assert terminal[0][1]["errors"] == int(fetch_fails)
        if fetch_fails:
            assert all(
                not name.startswith("library.item.") for name, _ in publisher.events
            )
    finally:
        phash.shutdown()


@pytest.mark.parametrize("include_collections", [True, False])
async def test_full_sync_collection_phase_respects_target(
    tmp_path: Path, *, include_collections: bool
) -> None:
    class CollectionsProbe(NoCollections):
        def __init__(self) -> None:
            self.called = False

        @override
        async def run(self, *_args: object, **_kwargs: object) -> None:
            self.called = True

    collections = CollectionsProbe()
    provider = FakeProvider()
    probe = JobProbe()
    await sync_runner_module.run_sync(
        probe.context,
        library_ids=["1"],
        include_collections=include_collections,
        provider_registry=NoopProviderRegistry(provider),
        reconciler=FakeReconciler(),
        config_dir=tmp_path,
        tmdb_seasons=NoTmdbShows(),
        collections=collections,
    )
    assert provider.calls == [{"library_ids": ["1"]}]
    assert collections.called is include_collections
    assert probe.names()[-1] == "sync.completed"
