"""Server-owned popup result snapshot."""

lazy from collections.abc import Callable
lazy from pathlib import Path
lazy from typing import Any, override

lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.jobs.runner import run_managed_job
lazy from overture.jobs.slot import ManagedBackgroundJob
lazy from overture.jobs.tally import BulkAssetTally
lazy from overture.schemas.asset_manager import AssetRenameResult, RenameStatus
lazy from overture.schemas.server_audit import (
    FixAuditRequest,
    ServerAuditThemeDeleteTarget,
)
lazy from overture.services import job_results, job_snapshots
lazy from overture.services.asset_manager.service import patch_rename_snapshot
lazy from overture.services.server_audit.fix import (
    PENDING,
    VERIFIED,
    RowFix,
    patch_audit_snapshot,
)
lazy from overture.utils.errors import PublicServiceError
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import JobProbe, NoopBackgroundJobs, make_runtime

SCAN_LIFECYCLE = ManagedJobLifecycle(JobKind.ASSET_SCAN)


class RecordingEvents(NullEventPublisher):
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    @override
    async def broadcast_built(
        self,
        builder: Callable[[], tuple[str, Any] | None],
    ) -> bool:
        built = builder()
        if built is None:
            return False
        self.events.append(built)
        return True


class SnapshotBackgroundJobs(NoopBackgroundJobs):
    def __init__(self, slot: ManagedBackgroundJob) -> None:
        super().__init__()
        self.slot = slot

    @override
    def values(self) -> tuple[ManagedBackgroundJob, ...]:
        return (self.slot,)


async def test_clear_snapshot_broadcasts_only_for_matching_terminal_result(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    slot = ManagedBackgroundJob(SCAN_LIFECYCLE, NullEventPublisher())
    slot.save_snapshot("assets.scan.completed", {"finished_at": "finish"})
    events = RecordingEvents()
    runtime = make_runtime(
        config_dir=tmp_path,
        background_jobs=SnapshotBackgroundJobs(slot),
        events=events,
        app_config=app_config,
        database=database,
    )

    stale = await job_snapshots.clear_snapshot(JobKind.ASSET_SCAN, "stale", runtime)
    cleared = await job_snapshots.clear_snapshot(JobKind.ASSET_SCAN, "finish", runtime)

    assert stale.status == "stale"
    assert cleared.status == "cleared"
    assert events.events == [
        (
            "job.snapshot.cleared",
            {"kind": JobKind.ASSET_SCAN, "finished_at": "finish"},
        )
    ]


def test_asset_rename_snapshot_keeps_successful_rows_marked() -> None:
    payload = {
        "issues": [
            {"current_path": "/media/cover.jpg", "conflict": False},
            {"current_path": "/media/fanart.jpg", "conflict": False},
        ]
    }

    patched = patch_rename_snapshot(
        payload,
        [
            AssetRenameResult(
                current_path="/media/cover.jpg", status=RenameStatus.RENAMED
            ),
            AssetRenameResult(
                current_path="/media/fanart.jpg",
                status=RenameStatus.ERROR,
                reason="failed",
            ),
        ],
    )

    assert patched["issues"] == [
        {"current_path": "/media/cover.jpg", "conflict": False, "renamed": True},
        {
            "current_path": "/media/fanart.jpg",
            "conflict": False,
            "rename_error": "failed",
        },
    ]


def test_server_audit_snapshot_marks_fix_outcomes_on_their_rows() -> None:
    payload = {
        "results": [
            {"kind": "art", "item_id": 1, "art_type": "poster"},
            {
                "kind": "art",
                "item_id": 1,
                "art_type": "background",
                "refresh_error": "Still differs after refresh: d=9",
            },
            {
                "kind": "theme",
                "item_id": 2,
                "server_item_id": "server-2",
                "theme_id": "theme-2",
            },
            {"kind": "art", "item_id": 3, "art_type": "poster"},
        ]
    }

    patched = patch_audit_snapshot(
        payload,
        {
            ("art", 1, None, "poster"): VERIFIED,
            ("art", 1, None, "background"): PENDING,
            ("theme", 2, "server-2", "theme-2"): RowFix(error="Item not found"),
        },
    )

    assert patched["results"] == [
        {"kind": "art", "item_id": 1, "art_type": "poster", "refreshed": True},
        {"kind": "art", "item_id": 1, "art_type": "background"},
        {
            "kind": "theme",
            "item_id": 2,
            "server_item_id": "server-2",
            "theme_id": "theme-2",
            "refresh_error": "Item not found",
        },
        {"kind": "art", "item_id": 3, "art_type": "poster"},
    ]


async def test_server_audit_rejects_destructive_targets_not_in_the_snapshot(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    events = NullEventPublisher()
    runtime = make_runtime(
        config_dir=tmp_path, events=events, app_config=app_config, database=database
    )
    runtime.background_jobs.server_audit.save_snapshot(
        "server.audit.completed",
        {
            "finished_at": "finish",
            "results": [
                {
                    "kind": "theme",
                    "item_id": 1,
                    "server_item_id": "server-1",
                    "theme_id": "theme-1",
                }
            ],
        },
    )

    with pytest.raises(PublicServiceError) as exc_info:
        await runtime.server_audit.fix(
            FixAuditRequest(
                snapshot_finished_at="finish",
                themes=[
                    ServerAuditThemeDeleteTarget(
                        item_id=2,
                        server_item_id="forged-server",
                        theme_id="forged-theme",
                    )
                ],
            ),
        )

    assert exc_info.value.status_code == 409


async def _persisted_run(database: Database, count: int) -> ManagedBackgroundJob:
    """A finished scan whose findings are stored with its run."""
    await job_results.persist(
        database,
        run_id="run-1",
        kind=JobKind.ASSET_SCAN,
        started_at="2026-01-01T00:00:00+00:00",
        event="assets.scan.completed",
        summary={"finished_at": "2026-01-01T00:05:00+00:00"},
        results=[{"current_path": f"/media/{index}.jpg"} for index in range(count)],
        log=[],
    )
    slot = ManagedBackgroundJob(SCAN_LIFECYCLE, NullEventPublisher())
    slot.save_snapshot(
        "assets.scan.completed",
        {"finished_at": "finish", "run_id": "run-1", "results_total": count},
    )
    return slot


def _path(row: dict[str, Any]) -> str:
    return str(row["current_path"])


async def test_snapshot_keys_are_found_among_every_stored_finding(
    monkeypatch: pytest.MonkeyPatch, database: Database
) -> None:
    monkeypatch.setattr(job_snapshots, "PAGE_SIZE", 2)
    slot = await _persisted_run(database, 5)

    await job_snapshots.require_snapshot_keys(
        slot,
        "finish",
        collection="issues",
        database=database,
        requested={"/media/0.jpg", "/media/4.jpg"},
        row_key=_path,
        stale_message="stale",
    )

    for finished_at, requested in (
        ("finish", {"/media/0.jpg", "/media/forged.jpg"}),
        ("other", {"/media/0.jpg"}),
    ):
        with pytest.raises(PublicServiceError) as exc_info:
            await job_snapshots.require_snapshot_keys(
                slot,
                finished_at,
                collection="issues",
                database=database,
                requested=requested,
                row_key=_path,
                stale_message="stale",
            )
        assert (exc_info.value.status_code, exc_info.value.message) == (409, "stale")


async def test_snapshot_patch_rewrites_changed_rows_of_every_page(
    monkeypatch: pytest.MonkeyPatch, database: Database
) -> None:
    monkeypatch.setattr(job_snapshots, "PAGE_SIZE", 2)
    slot = await _persisted_run(database, 5)
    events = RecordingEvents()

    def mark_odd(payload: dict[str, Any]) -> dict[str, Any]:
        return {
            "issues": [
                {**row, "renamed": True}
                if int(_path(row).removeprefix("/media/").removesuffix(".jpg")) % 2
                else row
                for row in payload["issues"]
            ]
        }

    await job_snapshots.patch_snapshot(
        slot,
        "finish",
        collection="issues",
        patcher=mark_odd,
        database=database,
        publisher=events,
    )
    await job_snapshots.patch_snapshot(
        slot,
        "stale",
        collection="issues",
        patcher=mark_odd,
        database=database,
        publisher=events,
    )

    stored = await job_results.results(database, "run-1")
    assert [row.get("renamed", False) for row in stored.items] == [
        False,
        True,
        False,
        True,
        False,
    ]
    assert events.events == [
        (
            "assets.scan.completed",
            {"finished_at": "finish", "run_id": "run-1", "results_total": 5},
        )
    ]


async def test_clearing_a_stored_snapshot_retires_its_findings(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    slot = await _persisted_run(database, 1)
    runtime = make_runtime(
        config_dir=tmp_path,
        background_jobs=SnapshotBackgroundJobs(slot),
        events=RecordingEvents(),
        app_config=app_config,
        database=database,
    )

    cleared = await job_snapshots.clear_snapshot(JobKind.ASSET_SCAN, "finish", runtime)

    assert cleared.status == "cleared"
    with pytest.raises(PublicServiceError) as exc_info:
        await job_results.results(database, "run-1")
    assert exc_info.value.status_code == 404


async def test_only_result_views_can_be_cleared(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> None:
    runtime = make_runtime(
        config_dir=tmp_path, app_config=app_config, database=database
    )

    with pytest.raises(PublicServiceError) as exc_info:
        await job_snapshots.clear_snapshot(JobKind.BACKUP, "finish", runtime)

    assert exc_info.value.status_code == 400


@pytest.mark.parametrize("restarted", [False, True])
async def test_clearing_theme_results_survives_a_restart(
    tmp_path: Path, restarted: bool, *, app_config: Settings, database: Database
) -> None:
    probe = JobProbe(lifecycle=ManagedJobLifecycle(JobKind.BULK_THEME))
    async with run_managed_job(
        probe.context, BulkAssetTally(), database=database
    ) as job:
        await job.started()
        await job.planned(1)
    event, payload = probe.terminal()
    if restarted:
        run = (await job_results.latest_runs(database))[JobKind.BULK_THEME]
        event, payload = run.event, run.summary
    slot = ManagedBackgroundJob(probe.context.lifecycle, NullEventPublisher())
    slot.save_snapshot(event, payload)
    runtime = make_runtime(
        config_dir=tmp_path,
        background_jobs=SnapshotBackgroundJobs(slot),
        events=RecordingEvents(),
        app_config=app_config,
        database=database,
    )

    cleared = await job_snapshots.clear_snapshot(
        JobKind.BULK_THEME, payload["finished_at"], runtime
    )

    assert cleared.status == "cleared"
    assert JobKind.BULK_THEME not in await job_results.latest_runs(database)
