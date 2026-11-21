"""Fixing server-audit findings, and verifying the server took each fix."""

lazy from collections import deque
lazy from collections.abc import Collection, Mapping, Sequence
lazy from dataclasses import replace
lazy from pathlib import Path
lazy from typing import Any, cast, override

lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.ledger import read_asset
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType, ServerAsset, ServerType
lazy from overture.jobs.kinds import JobKind
lazy from overture.jobs.lifecycle import ManagedJobLifecycle
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from overture.media_servers.plex import PlexProvider
lazy from overture.schemas.server_audit import (
    AuditStatus,
    FixAuditRequest,
    ServerAuditRefreshTarget,
    ServerAuditResult,
    ServerAuditThemeDeleteTarget,
)
lazy from overture.services.art.collection_art import CollectionArtService
lazy from overture.services.art.phash import PhashService
lazy from overture.services.downloads.theme import DownloadThemeHandler
lazy from overture.services.server_audit import fix as module
lazy from overture.services.server_audit.compare import AuditContext
lazy from overture.services.server_audit.fix import (
    PENDING,
    VERIFIED,
    AuditRowKey,
    RowFix,
)
lazy from overture.services.server_audit.work import AuditTarget, CollectionAuditTarget
lazy from overture.services.server_identity import ServerCopy
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.services.themes.youtube_resolver import ThemeAudio, YouTubeResolver
lazy from overture.utils.time import utc_now
lazy from overture.ws.events import validate_event_payload
lazy from tests.collection_helpers import stored_collection
lazy from tests.factories import seed_theme
lazy from tests.media_servers import TEST_SERVER_ID, configure, server_of
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    JobProbe,
    NoopProviderRegistry,
    StaticImageClients,
    make_local_assets,
    make_runtime,
    make_server_copies,
    unused,
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
            server_id=TEST_SERVER_ID,
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
        collection_art=unused(CollectionArtService),
        provider_registry=NoopProviderRegistry(),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        database=database,
        server_copies=make_server_copies(
            app_config=app_config,
            image_clients=StaticImageClients(),
            config_dir=tmp_path,
            phash=phash,
        ),
        theme_handler=unused(DownloadThemeHandler),
        publisher=NullEventPublisher(),
    )


async def _add_items(database: Database, *titles: str) -> None:
    async with database.write_session() as session:
        for item_id, title in enumerate(titles, start=1):
            session.add(MediaItem(id=item_id, media_type=MediaType.MOVIE, title=title))


def _resolve_to(monkeypatch: pytest.MonkeyPatch, ids: Mapping[int, str | None]) -> None:
    async def resolve(
        item_id: int, *_args: object, provider_registry: Any, **_kwargs: object
    ) -> list[ServerCopy]:
        found = ids[item_id]
        provider = provider_registry.get(TEST_SERVER_ID)
        return [] if found is None else [ServerCopy(provider, found)]

    monkeypatch.setattr(module, "resolve_owners", resolve)


async def _run(
    probe: JobProbe,
    *,
    art: Sequence[ServerAuditRefreshTarget] = (),
    themes: Sequence[ServerAuditThemeDeleteTarget] = (),
    provider: Any,
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
    poster = ("art", 1, None, "poster", 1)
    background = ("art", 1, None, "background", 1)

    marks = await _run(
        probe,
        art=[
            ServerAuditRefreshTarget(server_id=1, item_id=1, art_type=ArtType.POSTER),
            ServerAuditRefreshTarget(
                server_id=1, item_id=1, art_type=ArtType.BACKGROUND
            ),
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
    assert (
        payload["done"],
        payload["total"],
        payload["log_targets"].get("Matched", 0),
    ) == (2, 2, 2)


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
        art=[ServerAuditRefreshTarget(server_id=1, item_id=1, art_type=ArtType.POSTER)],
        provider=FakeProvider(),
        context=_context(tmp_path, app_config=app_config, database=database),
    )

    assert marks[-1] == {
        ("art", 1, None, "poster", 1): RowFix(error="Still differs after refresh: d=12")
    }
    _, payload = probe.terminal()
    assert (
        payload["done"],
        payload["log_targets"].get("Mismatch", 0),
        payload["log_targets"].get("Matched", 0),
    ) == (1, 1, 0)


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
        art=[ServerAuditRefreshTarget(server_id=1, item_id=1, art_type=ArtType.POSTER)],
        provider=FakeProvider(),
        context=_context(tmp_path, app_config=app_config, database=database),
    )

    assert marks == [{("art", 1, None, "poster", 1): PENDING}]
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
    first = ("theme", 1, "jf-1", "theme-a", 1)
    second = ("theme", 1, "jf-1", "theme-b", 1)

    marks = await _run(
        probe,
        themes=[
            ServerAuditThemeDeleteTarget(
                server_id=1, item_id=1, server_item_id="jf-1", theme_id="theme-a"
            ),
            ServerAuditThemeDeleteTarget(
                server_id=1, item_id=1, server_item_id="jf-1", theme_id="theme-b"
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
                server_id=1, item_id=1, server_item_id="plex-1", theme_id="plex-1"
            )
        ],
        provider=provider,
        context=_context(tmp_path, app_config=app_config, database=database),
    )

    assert provider.calls == [("delete", "plex-1", "plex-1")]
    assert marks[-1] == {
        ("theme", 1, "plex-1", "plex-1", 1): RowFix(
            error="Media server returned an error"
        )
    }
    assert server.checks == []
    assert probe.terminal()[1]["log_targets"].get("Error", 0) == 1


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
            ServerAuditRefreshTarget(server_id=1, item_id=1, art_type=ArtType.POSTER),
            ServerAuditRefreshTarget(server_id=1, item_id=2, art_type=ArtType.POSTER),
            ServerAuditRefreshTarget(server_id=1, item_id=3, art_type=ArtType.POSTER),
        ],
        provider=provider,
        context=_context(tmp_path, app_config=app_config, database=database),
    )

    errors = {key: fix.error for key, fix in marks[-1].items()}
    assert (
        errors["art", 1, None, "poster", 1] == "Could not resolve media-server item ID"
    )
    assert errors["art", 2, None, "poster", 1]
    assert errors["art", 3, None, "poster", 1] == "Item not found"
    assert server.checks == []
    _, payload = probe.terminal()
    assert (payload["done"], payload["log_targets"].get("Error", 0)) == (3, 3)


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
                    "server_id": 1,
                    "refresh_error": "Still differs after refresh: d=12",
                },
                {
                    "kind": "theme",
                    "item_id": 1,
                    "art_type": "theme",
                    "server_id": 1,
                    "server_item_id": "plex-1",
                    "theme_id": "plex-1",
                },
            ],
        },
    )

    response = await runtime.server_audit.fix(
        FixAuditRequest(
            snapshot_finished_at="finish",
            targets=[
                ServerAuditRefreshTarget(
                    server_id=1, item_id=1, art_type=ArtType.POSTER
                )
            ],
            themes=[
                ServerAuditThemeDeleteTarget(
                    server_id=1, item_id=1, server_item_id="plex-1", theme_id="plex-1"
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
            {
                "kind": "art",
                "item_id": 1,
                "art_type": "poster",
                "server_id": 1,
                "refreshed": True,
            },
            {
                "kind": "theme",
                "item_id": 1,
                "art_type": "theme",
                "server_id": 1,
                "server_item_id": "plex-1",
                "theme_id": "plex-1",
                "refreshed": True,
            },
        ],
    }


class Reuploads(CollectionArtService):
    """Record which collection images a fix sends again."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, ArtType]] = []

    @override
    async def reupload(self, collection_id: int, art_type: ArtType) -> None:
        self.sent.append((collection_id, art_type))


async def test_a_collection_image_is_uploaded_again_then_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with database.write_session() as session:
        session.add(
            stored_collection(
                id=4,
                server_item_id="box",
                media_type=MediaType.MOVIE,
                title="Saga",
                last_synced_at=utc_now(),
            )
        )

    async def audited(
        target: CollectionAuditTarget, **_kwargs: object
    ) -> tuple[CollectionAuditTarget, list[ServerAuditResult]]:
        assert target == CollectionAuditTarget(4, ServerAsset.POSTER)
        return target, [
            ServerAuditResult(
                kind="art",
                collection_id=4,
                art_type=target.asset,
                title="Saga",
                status=AuditStatus.PHASH_MATCH,
                server_id=TEST_SERVER_ID,
            )
        ]

    monkeypatch.setattr(module, "audit_target", audited)
    reuploads = Reuploads()
    provider = FakeProvider()

    marks = await _run(
        JobProbe(lifecycle=LIFECYCLE),
        art=[
            ServerAuditRefreshTarget(
                server_id=1, collection_id=4, art_type=ArtType.POSTER
            )
        ],
        provider=provider,
        context=replace(
            _context(tmp_path, app_config=app_config, database=database),
            collection_art=reuploads,
        ),
    )

    row = ("collection", 4, None, "poster", 1)
    assert reuploads.sent == [(4, ArtType.POSTER)]
    # Nothing of an item is refreshed for a collection.
    assert provider.calls == []
    assert marks == [{row: PENDING}, {row: VERIFIED}]


async def test_a_collection_image_fixed_across_servers_uploads_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with database.write_session() as session:
        session.add(
            stored_collection(
                id=4,
                server_item_id="box",
                media_type=MediaType.MOVIE,
                title="Saga",
                last_synced_at=utc_now(),
            )
        )

    async def audited(
        target: CollectionAuditTarget, **_kwargs: object
    ) -> tuple[CollectionAuditTarget, list[ServerAuditResult]]:
        assert target == CollectionAuditTarget(4, ServerAsset.POSTER)
        return target, [
            ServerAuditResult(
                kind="art",
                collection_id=4,
                art_type=target.asset,
                title="Saga",
                status=AuditStatus.PHASH_MATCH,
                server_id=server_id,
            )
            for server_id in (1, 2)
        ]

    monkeypatch.setattr(module, "audit_target", audited)
    reuploads = Reuploads()

    marks = await _run(
        JobProbe(lifecycle=LIFECYCLE),
        art=[
            ServerAuditRefreshTarget(
                server_id=server_id, collection_id=4, art_type=ArtType.POSTER
            )
            for server_id in (1, 2)
        ],
        provider=FakeProvider(),
        context=replace(
            _context(tmp_path, app_config=app_config, database=database),
            collection_art=reuploads,
        ),
    )

    first = ("collection", 4, None, "poster", 1)
    second = ("collection", 4, None, "poster", 2)
    assert reuploads.sent == [(4, ArtType.POSTER)]
    assert marks == [
        {first: PENDING, second: PENDING},
        {first: VERIFIED, second: VERIFIED},
    ]


class _FakeCollectionThemeResolver:
    def __init__(self, audio_bytes: bytes, fingerprint: str) -> None:
        self._audio_bytes = audio_bytes
        self._fingerprint = fingerprint

    async def download_audio(
        self,
        youtube_id: str,
        min_duration: int = 30,
        max_duration: int = 300,
        progress_callback: object = None,
        *,
        normalize_loudness: bool = False,
    ) -> ThemeAudio:
        del youtube_id, min_duration, max_duration, progress_callback
        del normalize_loudness
        return ThemeAudio(
            audio_bytes=self._audio_bytes,
            title="Saga Theme",
            duration=90,
            fingerprint=self._fingerprint,
        )


async def test_a_plex_collection_theme_is_uploaded_again_then_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    uploaded: list[tuple[str, bytes]] = []

    class PlexThemeProvider(PlexProvider):
        @override
        async def upload_collection_theme(
            self, server_item_id: str, mp3_bytes: bytes
        ) -> str:
            uploaded.append((server_item_id, mp3_bytes))
            return "/library/metadata/box/theme/2"

    async with database.write_session() as session:
        session.add(
            seed_theme(
                stored_collection(
                    id=4,
                    server_item_id="box",
                    media_type=MediaType.MOVIE,
                    title="Saga",
                    last_synced_at=utc_now(),
                ),
                "VENZKx1iFzA",
                uploaded_as="/library/metadata/box/theme/1",
            )
        )

    async def audited(
        target: CollectionAuditTarget, **_kwargs: object
    ) -> tuple[CollectionAuditTarget, list[ServerAuditResult]]:
        assert target == CollectionAuditTarget(4, ServerAsset.THEME)
        return target, [
            ServerAuditResult(
                kind="theme",
                collection_id=4,
                art_type=ServerAsset.THEME,
                title="Saga",
                status=AuditStatus.THEME_MATCH,
                server_id=TEST_SERVER_ID,
                server_item_id="box",
            )
        ]

    monkeypatch.setattr(module, "audit_target", audited)
    handler = DownloadThemeHandler(
        asset_storage=unused(AssetStorage),
        youtube_resolver=cast(
            "YouTubeResolver", _FakeCollectionThemeResolver(b"new-mp3", "new-fp")
        ),
        database=database,
    )
    marks = await _run(
        JobProbe(lifecycle=LIFECYCLE),
        themes=[
            ServerAuditThemeDeleteTarget(
                server_id=1,
                collection_id=4,
                server_item_id="box",
                theme_id="box",
            )
        ],
        provider=PlexThemeProvider(
            server=server_of(app_config),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
        context=replace(
            _context(tmp_path, app_config=app_config, database=database),
            theme_handler=handler,
        ),
    )

    row_key = ("collection", 4, None, "theme", 1)
    assert uploaded == [("box", b"new-mp3")]
    async with database.read_session() as session:
        stored = await session.get(type(stored_collection(server_item_id="x")), 4)
        assert stored is not None
        assert read_asset(stored, ServerAsset.THEME).fingerprint == "new-fp"
    assert marks == [{row_key: PENDING}, {row_key: VERIFIED}]


async def test_a_jellyfin_collection_theme_is_written_to_folder_then_verified(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    refreshed: list[str] = []

    class JellyfinThemeProvider(JellyfinProvider):
        @override
        async def refresh_item(
            self, item_id: str, *, unlock: Collection[ServerAsset]
        ) -> None:
            del unlock
            refreshed.append(item_id)

    folder = tmp_path / "Saga [boxset]"
    folder.mkdir()
    configure(app_config, type=ServerType.JELLYFIN, collections_path=tmp_path)
    async with database.write_session() as session:
        session.add(
            seed_theme(
                stored_collection(
                    id=4,
                    server_item_id="box",
                    media_type=MediaType.MOVIE,
                    title="Saga",
                    server_path="/config/collections/Saga [boxset]",
                    last_synced_at=utc_now(),
                ),
                "VENZKx1iFzA",
            )
        )

    async def audited(
        target: CollectionAuditTarget, **_kwargs: object
    ) -> tuple[CollectionAuditTarget, list[ServerAuditResult]]:
        assert target == CollectionAuditTarget(4, ServerAsset.THEME)
        assert (folder / "theme.mp3").read_bytes() == b"jf-mp3"
        return target, [
            ServerAuditResult(
                kind="theme",
                collection_id=4,
                art_type=ServerAsset.THEME,
                title="Saga",
                status=AuditStatus.THEME_MATCH,
                server_id=TEST_SERVER_ID,
                server_item_id="box",
            )
        ]

    monkeypatch.setattr(module, "audit_target", audited)
    handler = DownloadThemeHandler(
        asset_storage=unused(AssetStorage),
        youtube_resolver=cast(
            "YouTubeResolver", _FakeCollectionThemeResolver(b"jf-mp3", "jf-fp")
        ),
        database=database,
    )
    marks = await _run(
        JobProbe(lifecycle=LIFECYCLE),
        themes=[
            ServerAuditThemeDeleteTarget(
                server_id=1,
                collection_id=4,
                server_item_id="box",
            )
        ],
        provider=JellyfinThemeProvider(
            server=server_of(app_config, ServerType.JELLYFIN),
            server_id=TEST_SERVER_ID,
            app_config=app_config,
        ),
        context=replace(
            _context(tmp_path, app_config=app_config, database=database),
            theme_handler=handler,
        ),
    )

    row_key = ("collection", 4, None, "theme", 1)
    assert refreshed == ["box"]
    assert marks == [{row_key: PENDING}, {row_key: VERIFIED}]
