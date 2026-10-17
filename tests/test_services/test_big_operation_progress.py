"""Live progress payload coverage for large scan operations."""

lazy from collections.abc import Iterator
lazy from pathlib import Path
lazy from typing import Any, cast

lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, ServerAsset
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import JobContext
lazy from overture.schemas.asset_manager import ScanRequest
lazy from overture.schemas.server_audit import (
    AuditStatus,
    ServerAuditRequest,
    ServerAuditResult,
)
lazy from overture.services.art.phash import PhashService
lazy from overture.services.asset_manager import scan as asset_scan
lazy from overture.services.server_audit import compare as server_audit
lazy from overture.services.server_audit.compare import AuditContext
lazy from overture.services.server_audit.work import AuditTarget
lazy from overture.services.storage.assets import AssetStorage
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    StaticImageClients,
    make_local_assets,
)


class Context:
    started_at = "2026-01-01T00:00:00+00:00"
    lifecycle = ManagedJobLifecycle(JobKind.SERVER_AUDIT)

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []
        self.publisher = NullEventPublisher()

    def stop_requested(self) -> bool:
        return False

    async def publish_lifecycle(
        self,
        status: str,
        **payload: object,
    ) -> None:
        self.events.append((status, payload))


def as_job_context(context: Context) -> JobContext:
    return cast("JobContext", context)


async def test_asset_scan_streams_new_issues_and_terminal_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    issue = {
        "folder": "/media/Movie",
        "current_path": "/media/Movie/cover.jpg",
        "current_filename": "cover.jpg",
        "suggested_path": "/media/Movie/poster.jpg",
        "suggested_filename": "poster.jpg",
        "type": "poster",
        "conflict": False,
        "width": 1000,
        "height": 1500,
    }

    def fake_build_scan_work(
        _movie_folders: list[str], _show_folders: list[str], database: Path
    ) -> int:
        return 1

    def fake_scan_work_batch(database: Path, offset: int) -> list[tuple[Path, str]]:
        return [(Path("/media/Movie"), "movie")] if offset == 0 else []

    def fake_scan_media_folder(
        _folder: Path, _media_type: str, _art_types: list[str], *, app_config: Settings
    ) -> list[dict[str, Any]]:
        return [issue]

    monkeypatch.setattr(asset_scan, "build_scan_work", fake_build_scan_work)
    monkeypatch.setattr(asset_scan, "scan_work_batch", fake_scan_work_batch)
    monkeypatch.setattr(asset_scan, "scan_media_folder", fake_scan_media_folder)

    context = Context()
    await asset_scan.run_scan(
        ScanRequest(),
        as_job_context(context),
        app_config=app_config,
        local_assets=make_local_assets(
            app_config=app_config,
            database=database,
            asset_storage=AssetStorage(app_config=app_config),
        ),
        database=database,
        config_dir=tmp_path,
    )

    progress = context.events[-2][1]
    completed = context.events[-1][1]
    assert progress["issues"] == [issue]
    assert completed["done"] == 1
    assert completed["total"] == 1
    assert completed["issues_found"] == 1


async def test_asset_scan_batches_many_issues_in_one_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    def fake_build_scan_work(
        _movie_folders: list[str], _show_folders: list[str], _database: Path
    ) -> int:
        return 1

    def fake_scan_work_batch(_database: Path, offset: int) -> list[tuple[Path, str]]:
        return [(Path("/media/Movie"), "movie")] if offset == 0 else []

    def fake_scan_media_folder(
        _folder: Path, _media_type: str, _art_types: list[str], *, app_config: Settings
    ) -> Iterator[dict[str, Any]]:
        for index in range(250):
            yield {"current_path": f"/media/Movie/{index}.jpg", "type": "poster"}

    monkeypatch.setattr(asset_scan, "build_scan_work", fake_build_scan_work)
    monkeypatch.setattr(asset_scan, "scan_work_batch", fake_scan_work_batch)
    monkeypatch.setattr(asset_scan, "scan_media_folder", fake_scan_media_folder)

    context = Context()
    await asset_scan.run_scan(
        ScanRequest(),
        as_job_context(context),
        app_config=app_config,
        local_assets=make_local_assets(
            app_config=app_config,
            database=database,
            asset_storage=AssetStorage(app_config=app_config),
        ),
        database=database,
        config_dir=tmp_path,
    )
    progress = [payload for event, payload in context.events if event == "progress"]
    batches = [
        cast("list[dict[str, Any]]", payload["issues"])
        for payload in progress
        if payload.get("issues")
    ]
    assert [len(batch) for batch in batches] == [100, 100, 50]
    assert context.events[-1][1]["issues_found"] == 250


async def test_server_audit_streams_actionable_results_and_terminal_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    result = ServerAuditResult(
        kind="art",
        item_id=1,
        art_type=ServerAsset.POSTER,
        status=AuditStatus.PHASH_MISMATCH,
        title="Movie",
        hamming=4,
    )

    async def fake_plan(*_args: object, **_kwargs: object) -> list[AuditTarget]:
        return [AuditTarget(1, ArtType.POSTER)]

    async def fake_audit(*_args: object, **_kwargs: object) -> ServerAuditResult:
        return result

    monkeypatch.setattr(server_audit, "plan_audit", fake_plan)
    monkeypatch.setattr(server_audit, "_audit_art_one", fake_audit)

    context = Context()
    registry = NoopProviderRegistry(object())
    audit_context = AuditContext(
        config_dir=tmp_path,
        provider_registry=registry,
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(app_config=app_config, database=database),
        phash=PhashService(app_config=app_config),
        image_clients=StaticImageClients(),
        app_config=app_config,
        database=database,
    )
    await server_audit.run_server_audit(
        ServerAuditRequest(),
        as_job_context(context),
        audit_context=audit_context,
    )

    planned = context.events[1][1]
    progress = context.events[-2][1]
    completed = context.events[-1][1]
    assert planned["total"] == 1
    assert planned["done"] == 0
    assert progress["results"] == [result]
    assert completed["done"] == 1
    assert completed["total"] == 1
    assert completed["results_found"] == 1
