"""Fixing server-audit findings, and verifying the server took each fix."""

lazy from collections import deque
lazy from collections.abc import Collection, Mapping, Sequence
lazy from dataclasses import replace
lazy from pathlib import Path
lazy from typing import Any

lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType, ServerAsset
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.schemas.server_audit import (
    AuditStatus,
    FixAuditRequest,
    ServerAuditRefreshTarget,
    ServerAuditResult,
    ServerAuditThemeDeleteTarget,
)
lazy from overture.services.art.phash import PhashService
lazy from overture.services.server_audit import fix as module
lazy from overture.services.server_audit.compare import AuditContext
lazy from overture.services.server_audit.fix import (
    PENDING,
    VERIFIED,
    AuditRowKey,
    RowFix,
)
lazy from overture.services.server_audit.work import AuditTarget
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.ws.events import validate_event_payload
lazy from tests.runtime_helpers import (
    JobProbe,
    NoopProviderRegistry,
    StaticImageClients,
    make_local_assets,
    make_runtime,
)

LIFECYCLE = ManagedJobLifecycle(JobKind.SERVER_AUDIT_FIX)


class FakeProvider:
    """Record what a fix asks of the media server."""

    def __init__(
        self,
        *,
        refresh_error: Exception | None = None,
        delete_error: Exception | None = None,
    ) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self._refresh_error = refresh_error
        self._delete_error = delete_error

    async def refresh_item(
        self, item_id: str, *, unlock: Collection[ServerAsset]
    ) -> None:
        if self._refresh_error is not None:
            raise self._refresh_error
        self.calls.append(("refresh", item_id, sorted(unlock)))

    async def delete_theme(self, server_item_id: str, theme_id: str | None) -> None:
        self.calls.append(("delete", server_item_id, theme_id))
        if self._delete_error is not None:
            raise self._delete_error


class ServerView:
    """What the fake server shows per audited file: one difference per check.

    The last entry repeats once the list runs out; ``None`` is a match.
    """

    def __init__(
        self, differences: Mapping[tuple[int, str], Sequence[str | None]]
    ) -> None:
        self._differences = {key: deque(value) for key, value in differences.items()}
        self.checks: list[tuple[int, str]] = []

    async def audit_target(
        self, target: AuditTarget, **_kwargs: object
    ) -> tuple[AuditTarget, list[ServerAuditResult]]:
        key = (target.item_id, target.asset)
        self.checks.append(key)
        remaining = self._differences[key]
        difference = remaining.popleft() if len(remaining) > 1 else remaining[0]
        result = ServerAuditResult(
            kind="art",
            item_id=target.item_id,
            art_type=target.asset,
            title=f"item {target.item_id}",
            status=AuditStatus.PHASH_MATCH
            if difference is None
            else AuditStatus.PHASH_MISMATCH,
            reason=difference,
        )
        return target, [result]


@pytest.fixture(autouse=True)
def immediate_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(module, "CHECK_INTERVAL_SECONDS", 0)


def _context(
    tmp_path: Path, *, app_config: Settings, database: Database
) -> AuditContext:
    phash = PhashService(app_config=app_config)
    return AuditContext(
        config_dir=tmp_path,
        provider_registry=NoopProviderRegistry(),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        image_clients=StaticImageClients(),
        app_config=app_config,
        database=database,
    )


async def _add_items(database: Database, *titles: str) -> None:
    async with database.write_session() as session:
        for item_id, title in enumerate(titles, start=1):
            session.add(MediaItem(id=item_id, media_type=MediaType.MOVIE, title=title))


def _resolve_to(monkeypatch: pytest.MonkeyPatch, ids: Mapping[int, str | None]) -> None:
    async def resolve(item_id: int, *_args: object, **_kwargs: object) -> str | None:
        return ids[item_id]

    monkeypatch.setattr(module, "resolve_owner_server_id", resolve)


async def _run(
    probe: JobProbe,
    *,
    art: Sequence[ServerAuditRefreshTarget] = (),
    themes: Sequence[ServerAuditThemeDeleteTarget] = (),
    provider: FakeProvider,
    context: AuditContext,
) -> list[dict[AuditRowKey, RowFix]]:
    marks: list[dict[AuditRowKey, RowFix]] = []

    async def mark(fixes: Mapping[AuditRowKey, RowFix]) -> None:
        if fixes:
            marks.append(dict(fixes))

    await module.run_audit_fix(
        art,
        themes,
        probe.context,
        audit_context=replace(
            context, provider_registry=NoopProviderRegistry(provider)
        ),
        mark=mark,
    )
    for event, payload in probe.events:
        validate_event_payload(event, payload)
    return marks


async def test_art_rows_turn_verified_only_once_the_server_shows_the_local_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await _add_items(database, "Movie")
    _resolve_to(monkeypatch, {1: "plex-1"})
    # The poster is still the old one at the first check.
    server = ServerView({(1, "poster"): ["d=12", None], (1, "background"): [None]})
    monkeypatch.setattr(module, "audit_target", server.audit_target)
    provider = FakeProvider()
    probe = JobProbe(lifecycle=LIFECYCLE)
    poster = ("art", 1, None, "poster")
    background = ("art", 1, None, "background")

    marks = await _run(
        probe,
        art=[
            ServerAuditRefreshTarget(item_id=1, art_type=ArtType.POSTER),
            ServerAuditRefreshTarget(item_id=1, art_type=ArtType.BACKGROUND),
        ],
        provider=provider,
        context=_context(tmp_path, app_config=app_config, database=database),
    )

    # One refresh for the item, unlocking only the slots being fixed.
    assert provider.calls == [("refresh", "plex-1", ["background", "poster"])]
    # Each row settles on its own check: the background first, then the poster.
    assert marks == [
        {poster: PENDING, background: PENDING},
        {background: VERIFIED},
        {poster: VERIFIED},
    ]
    event, payload = probe.terminal()
    assert event == "server.audit.fix.completed"
    assert (payload["done"], payload["total"], payload["verified"]) == (2, 2, 2)


async def test_rows_the_server_never_takes_end_unchanged_with_the_latest_difference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    monkeypatch.setattr(module, "IDLE_TIMEOUT_SECONDS", 0)
    await _add_items(database, "Movie")
    _resolve_to(monkeypatch, {1: "plex-1"})
    monkeypatch.setattr(
        module, "audit_target", ServerView({(1, "poster"): ["d=12"]}).audit_target
    )
    probe = JobProbe(lifecycle=LIFECYCLE)

    marks = await _run(
        probe,
        art=[ServerAuditRefreshTarget(item_id=1, art_type=ArtType.POSTER)],
        provider=FakeProvider(),
        context=_context(tmp_path, app_config=app_config, database=database),
    )

    assert marks[-1] == {
        ("art", 1, None, "poster"): RowFix(error="Still differs after refresh: d=12")
    }
    _, payload = probe.terminal()
    assert (payload["done"], payload["unchanged"], payload["verified"]) == (1, 1, 0)


async def test_a_stopped_fix_leaves_unsettled_rows_without_an_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await _add_items(database, "Movie")
    _resolve_to(monkeypatch, {1: "plex-1"})
    server = ServerView({(1, "poster"): ["d=12"]})
    monkeypatch.setattr(module, "audit_target", server.audit_target)
    probe = JobProbe(lifecycle=LIFECYCLE, stop_requested=True)

    marks = await _run(
        probe,
        art=[ServerAuditRefreshTarget(item_id=1, art_type=ArtType.POSTER)],
        provider=FakeProvider(),
        context=_context(tmp_path, app_config=app_config, database=database),
    )

    assert marks == [{("art", 1, None, "poster"): PENDING}]
    assert server.checks == []
    assert probe.terminal()[0] == "server.audit.fix.stopped"


async def test_themes_are_deleted_before_one_refresh_that_unlocks_the_theme(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await _add_items(database, "Show")
    monkeypatch.setattr(
        module, "audit_target", ServerView({(1, "theme"): [None]}).audit_target
    )
    provider = FakeProvider()
    probe = JobProbe(lifecycle=LIFECYCLE)
    first = ("theme", 1, "jf-1", "theme-a")
    second = ("theme", 1, "jf-1", "theme-b")

    marks = await _run(
        probe,
        themes=[
            ServerAuditThemeDeleteTarget(
                item_id=1, server_item_id="jf-1", theme_id="theme-a"
            ),
            ServerAuditThemeDeleteTarget(
                item_id=1, server_item_id="jf-1", theme_id="theme-b"
            ),
        ],
        provider=provider,
        context=_context(tmp_path, app_config=app_config, database=database),
    )

    assert provider.calls == [
        ("delete", "jf-1", "theme-a"),
        ("delete", "jf-1", "theme-b"),
        ("refresh", "jf-1", ["theme"]),
    ]
    assert marks[-1] == {first: VERIFIED, second: VERIFIED}
    # Both server themes belong to one local file, so the run fixes one target.
    assert probe.terminal()[1]["total"] == 1


async def test_a_failed_theme_delete_skips_the_refresh_and_marks_its_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await _add_items(database, "Show")
    server = ServerView({(1, "theme"): [None]})
    monkeypatch.setattr(module, "audit_target", server.audit_target)
    provider = FakeProvider(
        delete_error=MediaServerError("Media server returned an error")
    )
    probe = JobProbe(lifecycle=LIFECYCLE)

    marks = await _run(
        probe,
        themes=[
            ServerAuditThemeDeleteTarget(
                item_id=1, server_item_id="plex-1", theme_id="plex-1"
            )
        ],
        provider=provider,
        context=_context(tmp_path, app_config=app_config, database=database),
    )

    assert provider.calls == [("delete", "plex-1", "plex-1")]
    assert marks[-1] == {
        ("theme", 1, "plex-1", "plex-1"): RowFix(error="Media server returned an error")
    }
    assert server.checks == []
    assert probe.terminal()[1]["errors"] == 1


async def test_fix_failures_settle_as_errors_without_a_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await _add_items(database, "Unresolved", "Refused")
    _resolve_to(monkeypatch, {1: None, 2: "plex-2"})
    server = ServerView({})
    monkeypatch.setattr(module, "audit_target", server.audit_target)
    provider = FakeProvider(refresh_error=MediaServerError("Media server is offline"))
    probe = JobProbe(lifecycle=LIFECYCLE)

    marks = await _run(
        probe,
        art=[
            ServerAuditRefreshTarget(item_id=1, art_type=ArtType.POSTER),
            ServerAuditRefreshTarget(item_id=2, art_type=ArtType.POSTER),
            ServerAuditRefreshTarget(item_id=3, art_type=ArtType.POSTER),
        ],
        provider=provider,
        context=_context(tmp_path, app_config=app_config, database=database),
    )

    errors = {key: fix.error for key, fix in marks[-1].items()}
    assert errors["art", 1, None, "poster"] == "Could not resolve media-server item ID"
    assert errors["art", 2, None, "poster"]
    assert errors["art", 3, None, "poster"] == "Item not found"
    assert server.checks == []
    _, payload = probe.terminal()
    assert (payload["done"], payload["errors"]) == (3, 3)


async def test_the_service_fixes_art_and_themes_in_one_run_and_marks_the_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    await _add_items(database, "Movie")
    _resolve_to(monkeypatch, {1: "plex-1"})
    monkeypatch.setattr(
        module,
        "audit_target",
        ServerView({(1, "poster"): [None], (1, "theme"): [None]}).audit_target,
    )
    provider = FakeProvider()
    runtime = make_runtime(
        config_dir=tmp_path,
        app_config=app_config,
        database=database,
        provider_registry=NoopProviderRegistry(provider),
    )
    audit = runtime.background_jobs.server_audit
    audit.save_snapshot(
        "server.audit.completed",
        {
            "finished_at": "finish",
            "results": [
                {
                    "kind": "art",
                    "item_id": 1,
                    "art_type": "poster",
                    "refresh_error": "Still differs after refresh: d=12",
                },
                {
                    "kind": "theme",
                    "item_id": 1,
                    "art_type": "theme",
                    "server_item_id": "plex-1",
                    "theme_id": "plex-1",
                },
            ],
        },
    )

    response = await runtime.server_audit.fix(
        FixAuditRequest(
            snapshot_finished_at="finish",
            targets=[ServerAuditRefreshTarget(item_id=1, art_type=ArtType.POSTER)],
            themes=[
                ServerAuditThemeDeleteTarget(
                    item_id=1, server_item_id="plex-1", theme_id="plex-1"
                )
            ],
        )
    )
    await runtime.background_jobs.server_audit_fix.wait_idle()

    assert response.status == "started"
    # One item is refreshed once, unlocking both fixed assets.
    assert provider.calls == [
        ("delete", "plex-1", "plex-1"),
        ("refresh", "plex-1", ["poster", "theme"]),
    ]
    assert audit.final_snapshot()[1] == {
        "finished_at": "finish",
        "results": [
            {"kind": "art", "item_id": 1, "art_type": "poster", "refreshed": True},
            {
                "kind": "theme",
                "item_id": 1,
                "art_type": "theme",
                "server_item_id": "plex-1",
                "theme_id": "plex-1",
                "refreshed": True,
            },
        ],
    }
