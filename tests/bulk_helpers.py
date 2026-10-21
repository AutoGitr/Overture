"""Shared bulk-run fixtures and controlled collaborators."""

lazy from typing import Any, override

lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.art_slots import write_art_slot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import PublicDatasetItem
lazy from overture.db.session import Database
lazy from overture.domain import (
    ArtType,
    MediaType,
)
lazy from overture.integrations.proxy import ProxyClientManager
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.progress_log import JobLogEntry
lazy from overture.jobs.runner import JobContext
lazy from overture.services.art import bulk as art_bulk
lazy from overture.services.art.bulk_work import ArtTarget, BulkArtWork
lazy from overture.services.art.candidates import ArtCandidates
lazy from overture.services.art.matcher import ArtMatcher
lazy from overture.services.art.phash import PhashService
lazy from overture.services.bulk_common import AssetPlan
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.public_dataset.index import PublicDatasetIndex
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.themes import bulk as theme_bulk
lazy from overture.services.themes.youtube_resolver import YouTubeResolver
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


def make_bulk_downloads(*, app_config: Settings, database: Database) -> DownloadService:
    return make_download_service(
        NullEventPublisher(),
        provider_registry=NoopProviderRegistry(),
        asset_storage=AssetStorage(app_config=app_config),
        phash=PhashService(app_config=app_config),
        image_clients=unused(ProxyClientManager),
        youtube_resolver=unused(YouTubeResolver),
        app_config=app_config,
        database=database,
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
    )


class RecordingStamper:
    """Captures the targets a run stamps instead of writing to the database."""

    def __init__(self) -> None:
        self.checked: list[int] = []

    async def add(self, item_id: int, *, season_id: int | None = None) -> None:
        self.checked.append(item_id)

    async def flush(self) -> None:
        pass


def bind_stamper(monkeypatch: pytest.MonkeyPatch, module: Any) -> RecordingStamper:
    stamper = RecordingStamper()

    def _factory(*_args: object, **_kwargs: object) -> RecordingStamper:
        return stamper

    monkeypatch.setattr(module, "CheckedStamper", _factory)
    return stamper


def use_art_work(monkeypatch: pytest.MonkeyPatch, work: BulkArtWork) -> None:
    """Run the art runner over *work* as its only planned batch."""
    plan = AssetPlan[ArtTarget]()
    by_item: dict[int, tuple[MediaItem, list[ArtTarget]]] = {}
    for item, art_type, season in work.targets:
        by_item.setdefault(item.id or 0, (item, []))[1].append(
            (art_type, season.id if season else None)
        )
    for item, targets in by_item.values():
        plan.visit(item, targets)

    async def planned(*_args: object, **_kwargs: object) -> AssetPlan[ArtTarget]:
        return plan

    async def loaded(*_args: object, **_kwargs: object) -> BulkArtWork:
        return work

    monkeypatch.setattr(art_bulk, "plan_bulk_art", planned)
    monkeypatch.setattr(art_bulk, "load_art_batch", loaded)


def use_theme_work(
    monkeypatch: pytest.MonkeyPatch, work: theme_bulk.BulkThemeWork
) -> None:
    """Run the theme runner over *work* as its only planned batch."""
    plan = AssetPlan[theme_bulk.ThemeTarget]()
    for item in work.items:
        plan.visit(item, [None])

    async def planned(
        *_args: object, **_kwargs: object
    ) -> AssetPlan[theme_bulk.ThemeTarget]:
        return plan

    async def loaded(*_args: object, **_kwargs: object) -> theme_bulk.BulkThemeWork:
        return work

    monkeypatch.setattr(theme_bulk, "plan_bulk_themes", planned)
    monkeypatch.setattr(theme_bulk, "load_theme_batch", loaded)


def public_index(item_id: int, **fields: Any) -> PublicDatasetIndex:
    """Build an index holding one dataset row for *item_id*."""
    return PublicDatasetIndex(
        {item_id: PublicDatasetItem(id=99, media_type=MediaType.MOVIE, **fields)}, {}
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
    item = MediaItem(**defaults)
    for art_type, fields in (art or {}).items():
        write_art_slot(item, ArtType(art_type), **fields)
    return item
