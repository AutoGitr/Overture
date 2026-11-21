"""Shared bulk-run fixtures and controlled collaborators."""

lazy from dataclasses import dataclass, field
lazy from pathlib import Path
lazy from typing import Any, override

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.catalog import CatalogItem
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    MediaType,
    ServerAsset,
)
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.progress_log import JobLogEntry
lazy from overture.jobs.runner import JobContext
lazy from overture.services.art.candidates import ArtCandidates
lazy from overture.services.art.collection_art import CollectionArtService
lazy from overture.services.art.matcher import ArtMatcher
lazy from overture.services.art.phash import PHASH_HEX_LENGTH, PhashService
lazy from overture.services.asset_runs import run as asset_run
lazy from overture.services.asset_runs.plan import AssetPlan, Target, slot
lazy from overture.services.asset_runs.sources import BatchFacts
lazy from overture.services.catalog.index import CatalogIndex
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.schedule_store import CATALOG_SCHEDULE, save_schedule
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
lazy from overture.utils.audio import ThemeAudioMetadata
lazy from tests.factories import seed_asset
lazy from tests.media_servers import served_item
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    JobProbe,
    NoopProviderRegistry,
    make_download_service,
    make_local_assets,
    unused,
)


class Context(JobProbe):
    def __init__(self, kind: JobKind = JobKind.BULK_ART) -> None:
        super().__init__(lifecycle=ManagedJobLifecycle(kind))

    @property
    @override
    def events(self) -> list[tuple[str, Any]]:
        return [
            (event.rsplit(".", 1)[1], payload)
            for event, payload in super().events
            if event.startswith(f"{self.context.lifecycle.kind.event_prefix}.")
        ]


def as_job_context(context: Context) -> JobContext:
    return context.context


def progress_logs(context: Context) -> list[str]:
    """Return every progress entry the run published, in order, as lines."""
    return [
        JobLogEntry.model_validate(payload["log"]).format()
        for *_rest, payload in context.events
        if "log" in payload
    ]


def make_bulk_downloads(
    *,
    app_config: Settings,
    database: Database,
    provider: object | None = None,
    collection_art: CollectionArtService | None = None,
) -> DownloadService:
    return make_download_service(
        NullEventPublisher(),
        provider_registry=NoopProviderRegistry(provider),
        asset_storage=AssetStorage(app_config=app_config),
        phash=PhashService(app_config=app_config),
        image_clients=unused(ProxyClientManager),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
        collection_art=collection_art,
    )


def art_matcher(*, app_config: Settings, database: Database) -> ArtMatcher:
    asset_storage = AssetStorage(app_config=app_config)
    provider_registry = NoopProviderRegistry()
    return ArtMatcher(
        phash=PhashService(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, asset_storage=asset_storage
        ),
        provider_registry=provider_registry,
        candidates=unused(ArtCandidates),
        image_clients=unused(ProxyClientManager),
        app_config=app_config,
        database=database,
        compare_concurrency=2,
    )


class RecordingStamper:
    """Captures the owners a run stamps instead of writing to the database."""

    def __init__(self) -> None:
        self.checked: list[int] = []

    async def add(
        self,
        *,
        item_id: int | None = None,
        season_id: int | None = None,
        collection_id: int | None = None,
    ) -> None:
        checked = item_id if item_id is not None else collection_id
        if checked is not None:
            self.checked.append(checked)

    async def flush(self) -> None:
        pass


def bind_stamper(monkeypatch: pytest.MonkeyPatch) -> RecordingStamper:
    stamper = RecordingStamper()

    def _factory(*_args: object, **_kwargs: object) -> RecordingStamper:
        return stamper

    monkeypatch.setattr(asset_run, "CheckedStamper", _factory)
    return stamper


@dataclass(frozen=True, slots=True)
class BulkArtWork:
    """One batch of art slots a test runs, and OvertureDB's entries for them."""

    targets: list[tuple[MediaItem, ArtType, Season | None]]
    public_index: CatalogIndex = field(default_factory=CatalogIndex.empty)


@dataclass(frozen=True, slots=True)
class BulkThemeWork:
    """One batch of titles whose themes a test runs."""

    items: list[MediaItem]
    search_format: str
    public_index: CatalogIndex = field(default_factory=CatalogIndex.empty)
    #: YouTube IDs that failed to download before, by item ID.
    failed_themes: dict[int, set[str]] = field(default_factory=dict[int, set[str]])


def use_targets(
    monkeypatch: pytest.MonkeyPatch, targets: list[Target], facts: BatchFacts
) -> None:
    """Run an Assets job over *targets* as its only planned batch."""
    plan = AssetPlan()
    by_owner: dict[int, tuple[MediaItem, list[Any]]] = {}
    for target in targets:
        title = target.title
        assert title is not None
        by_owner.setdefault(title.id or 0, (title, []))[1].append(slot(target))
    for owner, slots in by_owner.values():
        plan.visit(owner, slots)

    async def planned(*_args: object, **_kwargs: object) -> AssetPlan:
        return plan

    async def loaded(
        *_args: object, **_kwargs: object
    ) -> tuple[list[Target], BatchFacts]:
        return targets, facts

    monkeypatch.setattr(asset_run, "plan_run", planned)
    monkeypatch.setattr(asset_run, "_load", loaded)


def use_art_work(monkeypatch: pytest.MonkeyPatch, work: BulkArtWork) -> None:
    """Run the art runner over *work* as its only planned batch."""
    use_targets(
        monkeypatch,
        [
            Target(season, art_type.server_asset, item)
            if season is not None
            else Target(item, art_type.server_asset)
            for item, art_type, season in work.targets
        ],
        BatchFacts(work.public_index),
    )


def use_theme_work(monkeypatch: pytest.MonkeyPatch, work: BulkThemeWork) -> None:
    """Run the theme runner over *work* as its only planned batch."""
    use_targets(
        monkeypatch,
        [Target(item, ServerAsset.THEME) for item in work.items],
        BatchFacts(work.public_index, work.failed_themes, work.search_format),
    )


async def enable_catalog(session: AsyncSession) -> None:
    """Switch OvertureDB on, as the user does with Enable OvertureDB."""
    await save_schedule(session, CATALOG_SCHEDULE, enabled=True)
    await session.commit()


async def disable_catalog(session: AsyncSession) -> None:
    """Switch OvertureDB off, which it is not unless the user says so."""
    await save_schedule(session, CATALOG_SCHEDULE, enabled=False)
    await session.commit()


def public_index(item_id: int, **fields: Any) -> CatalogIndex:
    """Build an index holding one catalog row for *item_id*."""
    return CatalogIndex(
        {item_id: CatalogItem(id=99, media_type=MediaType.MOVIE, **fields)}, {}
    )


def movie_item(
    art: dict[str, dict[str, Any]] | None = None,
    **overrides: Any,
) -> MediaItem:
    """Build a detached movie MediaItem, optionally with artwork slots filled."""
    defaults: dict[str, Any] = {
        "id": 1,
        "title": "Movie",
        "media_type": MediaType.MOVIE,
        "folder_path": "/media/Movie",
        "last_matched_at": None,
    }
    defaults.update(overrides)
    item = served_item(**defaults)
    for art_type, fields in (art or {}).items():
        seed_asset(item, ArtType(art_type), **fields)
    return item


#: The bytes the fake catalog image has; a local file with them is identical.
CATALOG_BYTES = b"catalog artwork"


def fast_fingerprints(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> PhashService:
    """Fingerprint files without the decoding pool; the matrix never compares."""
    phash = PhashService(app_config=app_config)

    async def fingerprint(_path: str) -> str:
        return "0" * PHASH_HEX_LENGTH

    monkeypatch.setattr(phash, "compute_from_file", fingerprint)
    return phash


async def no_tags(_path: Path) -> ThemeAudioMetadata:
    """Stand in for ffprobe on a file without embedded provenance."""
    return ThemeAudioMetadata(duration=30)


def write_existing_asset(
    storage: AssetStorage,
    folder: Path,
    asset: str,
    season: Season | None,
    *,
    identical: bool,
) -> None:
    if asset == "theme":
        (folder / "theme.mp3").write_bytes(b"existing theme")
        return
    path = Path(
        storage.resolve_art_paths(
            str(folder),
            ArtType(asset),
            season_folder_path=season.folder_path if season else None,
            season_num=1 if season else None,
        )[0]
    )
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(CATALOG_BYTES if identical else b"existing artwork")
