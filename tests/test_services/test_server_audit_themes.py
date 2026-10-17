"""Comparing local theme files with the themes a media server plays."""

lazy import asyncio
lazy from pathlib import Path

lazy import httpx2
lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import MediaType
lazy from overture.media_servers.adapters import ServerTheme
lazy from overture.schemas.server_audit import ServerAuditResult
lazy from overture.services.art.phash import PhashService
lazy from overture.services.server_audit import compare as module
lazy from overture.services.server_audit.compare import (
    AuditContext,
    audit_target,
    differences,
)
lazy from overture.services.server_audit.work import AuditTarget
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.utils.file import compute_bytes_hash
lazy from tests.http_mock import mock_client_factory
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    StaticImageClients,
    make_local_assets,
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

    monkeypatch.setattr(module, "ffprobe_duration", probe)
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

    monkeypatch.setattr(module, "audio_hash", audio_hash)
    return calls


async def _audit(
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
    themes: list[ServerTheme],
    served: bytes | None = None,
    local: bytes = LOCAL_AUDIO,
) -> tuple[ServerAuditResult, list[ServerAuditResult]]:
    folder = tmp_path / "Movie (2000)"
    folder.mkdir()
    (folder / "theme.mp3").write_bytes(local)
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=1,
                media_type=MediaType.MOVIE,
                title="Movie",
                folder_path=str(folder),
                server_item_id="s1",
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
        image_clients=StaticImageClients(factory()),
        app_config=app_config,
        database=database,
        config_dir=tmp_path / "config",
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
