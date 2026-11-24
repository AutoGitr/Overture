"""Comparing local theme files with the themes a media server plays."""

lazy import asyncio
lazy from datetime import date
lazy from pathlib import Path
lazy from typing import override

lazy import httpx2
lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.ledger import (
    ContentFacts,
    Destination,
    FileFacts,
    read_asset,
    record_content,
    record_file,
)
lazy from overture.db.session import Database
lazy from overture.domain import (
    AssetStatus,
    DeliveryChannel,
    MediaType,
    ServerAsset,
    ServerType,
)
lazy from overture.media_servers.adapters import ServerTheme
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from overture.media_servers.plex import PlexProvider
lazy from overture.protocols import EventPublisher
lazy from overture.schemas.server_audit import (
    AuditStatus,
    ServerAuditRequest,
    ServerAuditResult,
)
lazy from overture.services import server_copies
lazy from overture.services.art.collection_art import CollectionArtService
lazy from overture.services.art.phash import PhashService
lazy from overture.services.downloads.theme import DownloadThemeHandler
lazy from overture.services.server_audit import collection_assets, themes
lazy from overture.services.server_audit.compare import audit_target, differences
lazy from overture.services.server_audit.context import AuditContext
lazy from overture.services.server_audit.work import (
    AuditTarget,
    CollectionAuditTarget,
    plan_collection_audit,
)
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.utils.hashing import compute_bytes_hash
lazy from overture.utils.time import utc_now
lazy from tests.collection_helpers import stored_collection
lazy from tests.factories import seed_theme
lazy from tests.http_mock import mock_client_factory
lazy from tests.media_servers import TEST_SERVER_ID, configure, served_item, server_of
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    StaticImageClients,
    make_local_assets,
    make_server_copies,
    unused,
)

LOCAL_AUDIO = b"local theme audio"
RETAGGED_AUDIO = b"local theme audio, other tags"
UNREADABLE = b"not audio"
THEME_URL = "http://plex.local:32400/library/metadata/s1/theme"


class ThemeProvider:
    """A media server that reports *themes* for its one item."""

    def __init__(self, themes: list[ServerTheme]) -> None:
        self.themes = themes

    async def get_theme_songs(self, server_item_id: str) -> list[ServerTheme]:
        assert server_item_id == "s1"
        return self.themes

    def get_download_headers(self, url: str) -> dict[str, str]:
        return {}


@pytest.fixture
def probed(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Time each probed file by its content; record what was probed."""
    durations = {LOCAL_AUDIO: 60.0, b"other theme": 124.0, b"same length": 61.5}
    calls: list[bytes] = []

    async def probe(path: Path) -> float | None:
        data = await asyncio.to_thread(path.read_bytes)
        calls.append(data)
        return durations.get(data)

    # The local file is read by the audit, a served theme by the server copies.
    for reader in (themes, collection_assets, server_copies):
        monkeypatch.setattr(reader, "ffprobe_duration", probe)
    return calls


@pytest.fixture
def hashed(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """Hash each file's audio as ffmpeg would; record what was hashed.

    A retagged copy of the local file holds the same audio.
    """
    audio = {RETAGGED_AUDIO: LOCAL_AUDIO, UNREADABLE: None}
    calls: list[bytes] = []

    async def audio_hash(path: Path) -> str | None:
        data = await asyncio.to_thread(path.read_bytes)
        calls.append(data)
        packets = audio.get(data, data)
        return compute_bytes_hash(packets) if packets is not None else None

    for reader in (themes, server_copies):
        monkeypatch.setattr(reader, "audio_hash", audio_hash)
    return calls


async def _audit(
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
    themes: list[ServerTheme],
    served: bytes | None = None,
    local: bytes = LOCAL_AUDIO,
    recorded_duration: int | None = None,
    recorded_size: int | None = None,
) -> tuple[ServerAuditResult, list[ServerAuditResult]]:
    folder = tmp_path / "Movie (2000)"
    folder.mkdir()
    theme = folder / "theme.mp3"
    theme.write_bytes(local)
    stat = theme.stat()
    async with database.write_session() as session:
        session.add(
            seed_theme(
                served_item(
                    id=1,
                    media_type=MediaType.MOVIE,
                    title="Movie",
                    folder_path=str(folder),
                    server_item_id="s1",
                ),
                file_hash="recorded",
                file_mtime_ns=stat.st_mtime_ns,
                file_size=recorded_size or stat.st_size,
                file_duration=recorded_duration,
            )
        )

    factory, _ = mock_client_factory(
        lambda _request: (
            httpx2.Response(404)
            if served is None
            else httpx2.Response(200, content=served)
        )
    )
    phash = PhashService(app_config=app_config)
    context = AuditContext(
        provider_registry=NoopProviderRegistry(ThemeProvider(themes)),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        database=database,
        collection_art=unused(CollectionArtService),
        server_copies=make_server_copies(
            app_config=app_config,
            image_clients=StaticImageClients(factory()),
            config_dir=tmp_path / "config",
            phash=phash,
        ),
        theme_handler=unused(DownloadThemeHandler),
        publisher=NullEventPublisher(),
    )
    _, results = await audit_target(AuditTarget(1), context=context)
    actionable = differences(results)
    return (actionable or results)[0], actionable


PLEX_THEME = ServerTheme(id="s1", url=THEME_URL)


@pytest.mark.parametrize("served", [LOCAL_AUDIO, RETAGGED_AUDIO])
async def test_a_served_theme_of_the_local_audio_matches_whatever_its_tags(
    tmp_path: Path,
    probed: list[bytes],
    hashed: list[bytes],
    served: bytes,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    result, actionable = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        themes=[PLEX_THEME],
        served=served,
    )

    assert actionable == []
    assert (result.status, result.reason) == ("theme_match", "Same audio")
    assert hashed == [LOCAL_AUDIO, served]
    assert probed == []


@pytest.mark.parametrize(
    ("served", "reason", "server_duration"),
    [
        (
            b"other theme",
            "Media server plays a different file; duration differs by 64.0s",
            124.0,
        ),
        (
            b"same length",
            "Media server plays a different file of the same length",
            61.5,
        ),
    ],
)
async def test_a_served_theme_of_other_audio_differs_and_both_files_are_timed(
    tmp_path: Path,
    probed: list[bytes],
    hashed: list[bytes],
    served: bytes,
    reason: str,
    server_duration: float,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    result, actionable = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        themes=[PLEX_THEME],
        served=served,
    )

    assert actionable == [result]
    assert result.status == "theme_mismatch"
    assert result.reason == reason
    assert result.local_duration == 60.0
    assert result.server_duration == server_duration
    assert result.theme_id == "s1"
    assert probed == [served, LOCAL_AUDIO]


async def test_a_theme_that_cannot_be_downloaded_is_unknown(
    tmp_path: Path,
    probed: list[bytes],
    hashed: list[bytes],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    result, actionable = await _audit(
        tmp_path, app_config=app_config, database=database, themes=[PLEX_THEME]
    )

    assert actionable == [result]
    assert result.status == "theme_unknown"
    assert result.reason == "Could not download the media-server theme"
    assert result.local_duration == 60.0


async def test_a_served_theme_without_readable_audio_is_unknown(
    tmp_path: Path,
    probed: list[bytes],
    hashed: list[bytes],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    result, actionable = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        themes=[PLEX_THEME],
        served=UNREADABLE,
    )

    assert actionable == [result]
    assert result.status == "theme_unknown"
    assert result.reason == "Could not read the media-server theme audio"
    assert result.local_duration == 60.0


async def test_a_local_theme_without_readable_audio_is_unknown_without_download(
    tmp_path: Path,
    probed: list[bytes],
    hashed: list[bytes],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    result, actionable = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        themes=[PLEX_THEME],
        served=LOCAL_AUDIO,
        local=UNREADABLE,
    )

    assert actionable == [result]
    assert result.status == "theme_unknown"
    assert result.reason == "Could not read the local theme audio"
    assert hashed == [UNREADABLE]


async def test_a_theme_played_from_the_local_path_matches_without_reading_it(
    tmp_path: Path,
    probed: list[bytes],
    hashed: list[bytes],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    local = tmp_path / "Movie (2000)" / "theme.mp3"
    result, actionable = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        themes=[ServerTheme(id="t1", title="Theme", path=str(local), duration=9.0)],
    )

    assert actionable == []
    assert (result.status, result.reason) == ("theme_match", "Same file")
    assert probed == []
    assert hashed == []


async def test_a_theme_played_from_another_path_differs_whatever_its_length(
    tmp_path: Path, probed: list[bytes], *, app_config: Settings, database: Database
) -> None:
    other = tmp_path / "Movie (2000)" / "theme-music" / "extra.mp3"
    result, actionable = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        themes=[ServerTheme(id="t1", title="Extra", path=str(other), duration=61.0)],
    )

    assert actionable == [result]
    assert result.status == "theme_mismatch"
    assert result.reason == ("Media server plays a different file of the same length")
    assert (result.local_duration, result.server_duration) == (
        60.0,
        61.0,
    )
    assert probed == [LOCAL_AUDIO]


async def test_a_theme_without_a_reported_file_is_unknown(
    tmp_path: Path, probed: list[bytes], *, app_config: Settings, database: Database
) -> None:
    result, actionable = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        themes=[ServerTheme(id="t1", title="Theme", path=None, duration=60.0)],
    )

    assert actionable == [result]
    assert result.status == "theme_unknown"
    assert result.reason == "Media server did not report the theme's file"


async def test_a_missing_server_theme_shows_the_local_duration(
    tmp_path: Path, probed: list[bytes], *, app_config: Settings, database: Database
) -> None:
    result, actionable = await _audit(
        tmp_path, app_config=app_config, database=database, themes=[]
    )

    assert actionable == [result]
    assert result.status == "theme_server_missing"
    assert result.local_duration == 60.0


async def test_the_recorded_length_of_an_unchanged_file_is_not_probed_again(
    tmp_path: Path, probed: list[bytes], *, app_config: Settings, database: Database
) -> None:
    result, _ = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        themes=[],
        recorded_duration=75,
    )

    assert result.local_duration == 75
    assert probed == []


async def test_a_file_changed_since_it_was_recorded_is_probed(
    tmp_path: Path, probed: list[bytes], *, app_config: Settings, database: Database
) -> None:
    result, _ = await _audit(
        tmp_path,
        app_config=app_config,
        database=database,
        themes=[],
        recorded_duration=75,
        recorded_size=1,
    )

    assert result.local_duration == 60.0
    assert probed == [LOCAL_AUDIO]


class _RecordingPublisher(EventPublisher):
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    @override
    async def broadcast(
        self, event: str, payload: object = None, *, before_publish: object = None
    ) -> None:
        self.events.append((event, payload))

    @override
    async def broadcast_built(self, builder: object) -> bool:
        return False


@pytest.mark.parametrize(
    ("themes", "served", "expected_status", "expected_asset_status", "expected_ref"),
    [
        (
            [ServerTheme(id="/library/metadata/box/theme/1", url=THEME_URL)],
            RETAGGED_AUDIO,
            AuditStatus.THEME_MATCH,
            AssetStatus.COMPLETE,
            "/library/metadata/box/theme/1",
        ),
        (
            [ServerTheme(id="/library/metadata/box/theme/2", url=THEME_URL)],
            b"other theme",
            AuditStatus.THEME_MISMATCH,
            AssetStatus.PARTIAL,
            "/library/metadata/box/theme/2",
        ),
        (
            [],
            LOCAL_AUDIO,
            AuditStatus.THEME_SERVER_MISSING,
            AssetStatus.PARTIAL,
            None,
        ),
    ],
)
async def test_plex_collection_theme_audit_checks_served_audio_and_updates_delivery(
    tmp_path: Path,
    probed: list[bytes],
    hashed: list[bytes],
    themes: list[ServerTheme],
    served: bytes,
    expected_status: AuditStatus,
    expected_asset_status: AssetStatus,
    expected_ref: str | None,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    del probed, hashed

    class PlexCollectionProvider(PlexProvider):
        @override
        async def get_theme_songs(self, server_item_id: str) -> list[ServerTheme]:
            assert server_item_id == "box"
            return themes

    copy = Destination(TEST_SERVER_ID, "box", DeliveryChannel.UPLOAD)
    async with database.write_session() as session:
        row = stored_collection(
            id=1,
            server_item_id="box",
            media_type=MediaType.MOVIE,
            title="Saga",
            last_synced_at=utc_now(),
        )
        seed_theme(
            row,
            "yt-saga",
            content_hash="theme-bytes",
            uploaded_as="/library/metadata/box/theme/1",
            destination=copy,
        )
        record_content(
            row,
            ServerAsset.THEME,
            ContentFacts(
                "theme-bytes",
                fingerprint=compute_bytes_hash(LOCAL_AUDIO),
                duration=60,
            ),
        )
        session.add(row)

    assert (
        await plan_collection_audit(
            ServerAuditRequest(check_collections=True, check_themes=False),
            database=database,
            today=date(2026, 1, 1),
        )
        == []
    )
    assert await plan_collection_audit(
        ServerAuditRequest(check_collections=True),
        database=database,
        today=date(2026, 1, 1),
    ) == [CollectionAuditTarget(1, ServerAsset.THEME)]

    publisher = _RecordingPublisher()
    factory, _ = mock_client_factory(lambda _req: httpx2.Response(200, content=served))
    phash = PhashService(app_config=app_config)
    context = AuditContext(
        provider_registry=NoopProviderRegistry(
            PlexCollectionProvider(
                server=server_of(app_config),
                server_id=TEST_SERVER_ID,
                app_config=app_config,
            )
        ),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        server_copies=make_server_copies(
            app_config=app_config,
            image_clients=StaticImageClients(factory()),
            config_dir=tmp_path / "config",
            phash=phash,
        ),
        database=database,
        collection_art=unused(CollectionArtService),
        publisher=publisher,
        theme_handler=unused(DownloadThemeHandler),
    )
    _, [result] = await audit_target(
        CollectionAuditTarget(1, ServerAsset.THEME), context=context
    )
    assert result.status is expected_status
    async with database.read_session() as session:
        stored = await session.get(type(row), 1)
        assert stored is not None
        asset = read_asset(stored, ServerAsset.THEME)
        assert asset.status is expected_asset_status
        assert asset.deliveries[0].observed_ref == expected_ref
    if expected_asset_status is AssetStatus.PARTIAL:
        assert publisher.events == [
            ("collection.updated", {"collection_id": 1, "titles": False})
        ]
    else:
        assert publisher.events == []


@pytest.mark.parametrize(
    ("disk_bytes", "expected_status", "expected_asset_status"),
    [
        (LOCAL_AUDIO, AuditStatus.THEME_MATCH, AssetStatus.COMPLETE),
        (b"other theme", AuditStatus.THEME_MISMATCH, AssetStatus.PARTIAL),
        (None, AuditStatus.THEME_SERVER_MISSING, AssetStatus.PARTIAL),
    ],
)
async def test_jellyfin_collection_theme_audit_inspects_folder_and_updates_delivery(
    tmp_path: Path,
    probed: list[bytes],
    disk_bytes: bytes | None,
    expected_status: AuditStatus,
    expected_asset_status: AssetStatus,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    del probed
    folder = tmp_path / "Saga [boxset]"
    folder.mkdir()
    theme_path = folder / "theme.mp3"
    theme_path.write_bytes(LOCAL_AUDIO)
    stat = theme_path.stat()
    expected_hash = compute_bytes_hash(LOCAL_AUDIO)
    configure(app_config, type=ServerType.JELLYFIN, collections_path=tmp_path)
    copy = Destination(TEST_SERVER_ID, "box", DeliveryChannel.FILE)
    async with database.write_session() as session:
        row = stored_collection(
            id=1,
            server_item_id="box",
            media_type=MediaType.MOVIE,
            title="Saga",
            server_path="/config/collections/Saga [boxset]",
            last_synced_at=utc_now(),
        )
        seed_theme(
            row,
            "yt-saga",
            file_hash=expected_hash,
            content_hash=expected_hash,
            file_mtime_ns=stat.st_mtime_ns,
            file_size=stat.st_size,
            file_duration=60,
            destination=copy,
        )
        session.add(row)

    if disk_bytes is None:
        theme_path.unlink()
    elif disk_bytes != LOCAL_AUDIO:
        theme_path.write_bytes(disk_bytes)

    publisher = _RecordingPublisher()
    factory, _ = mock_client_factory(lambda _req: httpx2.Response(404))
    phash = PhashService(app_config=app_config)
    context = AuditContext(
        provider_registry=NoopProviderRegistry(
            JellyfinProvider(
                server=server_of(app_config, ServerType.JELLYFIN),
                server_id=TEST_SERVER_ID,
                app_config=app_config,
            )
        ),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        server_copies=make_server_copies(
            app_config=app_config,
            image_clients=StaticImageClients(factory()),
            config_dir=tmp_path / "config",
            phash=phash,
        ),
        database=database,
        collection_art=unused(CollectionArtService),
        publisher=publisher,
        theme_handler=unused(DownloadThemeHandler),
    )
    _, [result] = await audit_target(
        CollectionAuditTarget(1, ServerAsset.THEME), context=context
    )
    assert result.status is expected_status
    async with database.read_session() as session:
        stored = await session.get(type(row), 1)
        assert stored is not None
        asset = read_asset(stored, ServerAsset.THEME)
        assert asset.status is expected_asset_status
    if expected_asset_status is AssetStatus.PARTIAL:
        assert publisher.events == [
            ("collection.updated", {"collection_id": 1, "titles": False})
        ]
    else:
        assert publisher.events == []


async def test_local_theme_reuses_recorded_fingerprint_until_file_changes(
    tmp_path: Path,
    probed: list[bytes],
    hashed: list[bytes],
    *,
    app_config: Settings,
    database: Database,
) -> None:
    del probed
    folder = tmp_path / "Movie (2000)"
    folder.mkdir()
    theme = folder / "theme.mp3"
    theme.write_bytes(LOCAL_AUDIO)
    stat = theme.stat()
    fingerprint = compute_bytes_hash(LOCAL_AUDIO)
    async with database.write_session() as session:
        item = served_item(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
            folder_path=str(folder),
            server_item_id="s1",
        )
        record_file(
            item,
            ServerAsset.THEME,
            FileFacts(
                "recorded",
                stat.st_mtime_ns,
                stat.st_size,
                fingerprint=fingerprint,
                duration=60,
            ),
        )
        session.add(item)

    factory, _ = mock_client_factory(
        lambda _request: httpx2.Response(200, content=RETAGGED_AUDIO)
    )
    phash = PhashService(app_config=app_config)
    context = AuditContext(
        provider_registry=NoopProviderRegistry(ThemeProvider([PLEX_THEME])),
        asset_storage=AssetStorage(app_config=app_config),
        local_assets=make_local_assets(
            app_config=app_config, database=database, phash=phash
        ),
        phash=phash,
        database=database,
        collection_art=unused(CollectionArtService),
        server_copies=make_server_copies(
            app_config=app_config,
            image_clients=StaticImageClients(factory()),
            config_dir=tmp_path / "config",
            phash=phash,
        ),
        theme_handler=unused(DownloadThemeHandler),
        publisher=NullEventPublisher(),
    )

    _, [result] = await audit_target(AuditTarget(1), context=context)
    assert result.status is AuditStatus.THEME_MATCH
    assert hashed == [RETAGGED_AUDIO]

    hashed.clear()
    theme.write_bytes(RETAGGED_AUDIO)
    _, [changed] = await audit_target(AuditTarget(1), context=context)
    assert changed.status is AuditStatus.THEME_MATCH
    assert hashed == [RETAGGED_AUDIO, RETAGGED_AUDIO]
