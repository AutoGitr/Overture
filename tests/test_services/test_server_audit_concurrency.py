"""Server audit runs targets together but reports them in plan order."""

lazy import asyncio
lazy from dataclasses import replace
lazy from pathlib import Path
lazy from typing import Any, cast

lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.art_slots import ArtFileFacts
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaServerState, ServerAsset
lazy from overture.schemas.server_audit import (
    AuditStatus,
    ServerAuditRequest,
    ServerAuditResult,
)
lazy from overture.services.art.phash import PHASH_HEX_LENGTH, PhashService
lazy from overture.services.server_audit import compare as server_audit
lazy from overture.services.server_audit.compare import AuditContext
lazy from overture.services.server_audit.work import AuditTarget
lazy from overture.services.storage.assets import AssetStorage
lazy from tests.runtime_helpers import (
    JobProbe,
    NoopProviderRegistry,
    StaticImageClients,
    make_local_assets,
)


def _audit_context(
    tmp_path: Path, *, app_config: Settings, database: Database, phash: PhashService
) -> AuditContext:
    registry = NoopProviderRegistry(object())
    return AuditContext(
        config_dir=tmp_path,
        provider_registry=registry,
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        image_clients=StaticImageClients(),
        app_config=app_config,
        database=database,
    )


async def test_server_audit_reports_overlapping_targets_in_plan_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    targets = [AuditTarget(item_id, ArtType.POSTER) for item_id in range(1, 6)]
    running = 0
    peak = 0

    async def fake_plan(*_args: object, **_kwargs: object) -> list[AuditTarget]:
        return targets

    async def fake_audit(target: AuditTarget, *_args: object, **_kwargs: object) -> Any:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        # Earlier targets take more event-loop turns, so they finish last.
        for _ in range(6 - target.item_id):
            await asyncio.sleep(0)
        running -= 1
        return ServerAuditResult(
            kind="art",
            item_id=target.item_id,
            art_type=ServerAsset.POSTER,
            status=AuditStatus.PHASH_MISMATCH,
            title=f"Movie {target.item_id}",
            hamming=4,
        )

    monkeypatch.setattr(server_audit, "plan_audit", fake_plan)
    monkeypatch.setattr(server_audit, "_audit_art_one", fake_audit)
    probe = JobProbe()

    await server_audit.run_server_audit(
        ServerAuditRequest(),
        probe.context,
        audit_context=_audit_context(
            tmp_path,
            app_config=app_config,
            database=database,
            phash=PhashService(app_config=app_config),
        ),
    )

    reported = [
        result["item_id"]
        for event, payload in probe.events
        if event.endswith(".progress")
        for result in cast("list[dict[str, Any]]", payload.get("results") or [])
    ]
    assert reported == [1, 2, 3, 4, 5]
    assert peak > 1


async def testlocal_fingerprint_reuses_the_record_until_the_file_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    poster = tmp_path / "poster.jpg"
    poster.write_bytes(b"poster")
    stat = poster.stat()
    recorded = "a" * PHASH_HEX_LENGTH
    known = ArtFileFacts(
        file_hash="hash",
        phash=recorded,
        width=None,
        height=None,
        file_mtime_ns=stat.st_mtime_ns,
        file_size=stat.st_size,
    )
    phash = PhashService(app_config=app_config)
    computed: list[str] = []

    async def fingerprint(path: str) -> str:
        computed.append(path)
        return "b" * PHASH_HEX_LENGTH

    monkeypatch.setattr(phash, "compute_from_file", fingerprint)
    context = _audit_context(
        tmp_path, app_config=app_config, database=database, phash=phash
    )

    assert (
        await server_audit.local_fingerprint(poster, tmp_path, known, context)
        == recorded
    )
    assert computed == []

    poster.write_bytes(b"a changed poster")

    assert (
        await server_audit.local_fingerprint(poster, tmp_path, known, context)
        == "b" * PHASH_HEX_LENGTH
    )
    assert computed == [str(poster)]


async def test_server_audit_fails_at_once_while_the_media_server_is_down(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    class DownProvider:
        async def test_connection(self) -> bool:
            return False

    async def unplanned(*_args: object, **_kwargs: object) -> list[AuditTarget]:
        raise AssertionError("A run against a down server must not plan targets")

    monkeypatch.setattr(server_audit, "plan_audit", unplanned)
    context = _audit_context(
        tmp_path,
        app_config=app_config,
        database=database,
        phash=PhashService(app_config=app_config),
    )
    registry = NoopProviderRegistry(DownProvider())
    registry.health.record(MediaServerState.REJECTED, "check MEDIA_SERVER_API_KEY")
    probe = JobProbe()

    await server_audit.run_server_audit(
        ServerAuditRequest(),
        probe.context,
        audit_context=replace(context, provider_registry=registry),
    )

    assert probe.names()[-1].endswith(".failed")
    _, payload = probe.terminal()
    assert payload["job"]["error"]["message"] == "check MEDIA_SERVER_API_KEY"
