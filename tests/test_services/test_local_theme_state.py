"""Local theme presence reconciliation coverage."""

lazy import asyncio
lazy from pathlib import Path
lazy from unittest.mock import AsyncMock

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import MediaType, ThemeIdSource
lazy from overture.services.local_assets.theme import refresh_theme
lazy from overture.services.storage.assets import AssetStorage, FolderListing
lazy from overture.utils.audio import ThemeAudioMetadata
lazy from overture.utils.file import compute_file_hash
lazy from tests.runtime_helpers import make_local_assets


async def _refresh(item_id: int, storage: AssetStorage, database: Database) -> bool:
    """Refresh the theme of the item as it is stored now."""
    async with database.read_session() as session:
        item = await session.get(MediaItem, item_id)
    assert item is not None
    return await refresh_theme(item, storage, database, listing=FolderListing())


async def test_reconcile_local_theme_files_tracks_additions_and_removals(
    db_session: AsyncSession,
    tmp_path: Path,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    added_folder = tmp_path / "Added"
    removed_folder = tmp_path / "Removed"
    added_folder.mkdir()
    removed_folder.mkdir()
    (added_folder / "theme.mp3").write_bytes(b"theme")

    added = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Added",
        folder_path=str(added_folder),
    )
    removed = MediaItem(
        id=2,
        media_type=MediaType.MOVIE,
        title="Removed",
        folder_path=str(removed_folder),
        theme_file_hash="stale-hash",
    )
    db_session.add_all([added, removed])
    await db_session.commit()

    await make_local_assets(app_config=app_config, database=database).reconcile(
        art=False, source="test"
    )

    await db_session.refresh(added)
    await db_session.refresh(removed)
    assert added.theme_file_hash is not None
    assert removed.theme_file_hash is None


async def test_reconcile_local_theme_files_recovers_id3_provenance(
    db_session: AsyncSession,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    show_folder = tmp_path / "Show"
    show_folder.mkdir()
    (show_folder / "theme.mp3").write_bytes(b"audio-data")

    item = MediaItem(
        id=10,
        media_type=MediaType.SHOW,
        title="Show",
        folder_path=str(show_folder),
        theme_file_hash="stale-hash",
        youtube_id=None,
    )
    db_session.add(item)
    await db_session.commit()

    async def fake_probe(_path: Path) -> ThemeAudioMetadata:
        return ThemeAudioMetadata(
            duration=35.0,
            youtube_id="abcDEF123_4",
            youtube_id_source=ThemeIdSource.SOURCE_URL,
            title="Show Theme",
        )

    monkeypatch.setattr(
        "overture.services.local_assets.theme.ffprobe_theme_metadata",
        fake_probe,
    )

    await make_local_assets(app_config=app_config, database=database).reconcile(
        art=False, source="test"
    )

    await db_session.refresh(item)
    assert item.youtube_id == "abcDEF123_4"
    assert item.youtube_id_source is ThemeIdSource.SOURCE_URL
    assert item.youtube_title == "Show Theme"
    assert item.youtube_duration == 35
    assert item.theme_file_hash is not None


@pytest.mark.parametrize("youtube_id", [None, "abcDEF123_4"])
@pytest.mark.parametrize("probe_fails_first", [False, True])
async def test_refresh_recovers_complete_metadata_and_caches_unchanged_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    youtube_id: str | None,
    *,
    probe_fails_first: bool,
    app_config: Settings,
    database: Database,
) -> None:
    path = tmp_path / "theme.mp3"
    path.write_bytes(b"theme audio")
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=20,
                media_type=MediaType.MOVIE,
                title="Movie",
                folder_path=str(tmp_path),
                youtube_id=youtube_id,
                youtube_id_source=ThemeIdSource.DOWNLOAD if youtube_id else None,
            )
        )
    storage = AssetStorage(app_config=app_config)
    probe = AsyncMock(
        return_value=ThemeAudioMetadata(
            duration=35,
            youtube_id="abcDEF123_4",
            youtube_id_source=ThemeIdSource.SOURCE_URL,
            title="Theme",
        )
    )
    monkeypatch.setattr(
        "overture.services.local_assets.theme.ffprobe_theme_metadata", probe
    )
    hash_file = AsyncMock(wraps=storage.file_hash_async)
    monkeypatch.setattr(storage, "file_hash_async", hash_file)

    if probe_fails_first:
        probe.side_effect = [None, probe.return_value]
        assert await _refresh(20, storage, database)
    assert await _refresh(20, storage, database)
    assert not await _refresh(20, storage, database)
    assert hash_file.await_count == (2 if probe_fails_first else 1)
    assert probe.await_count == (2 if probe_fails_first else 1)
    async with database.read_session() as session:
        item = await session.get(MediaItem, 20)
        assert item is not None
        assert item.youtube_id == "abcDEF123_4"
        assert item.youtube_id_source is (
            ThemeIdSource.DOWNLOAD if youtube_id else ThemeIdSource.SOURCE_URL
        )
        assert item.youtube_title == "Theme"
        assert item.youtube_duration == 35
        assert item.theme_file_hash == compute_file_hash(path)

    path.unlink()
    assert await _refresh(20, storage, database)
    async with database.read_session() as session:
        item = await session.get(MediaItem, 20)
        assert item is not None
        assert item.theme_file_hash is None
        assert item.theme_file_mtime_ns is None
        assert item.theme_file_size is None


async def test_cleared_provenance_survives_reconciliation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    (tmp_path / "theme.mp3").write_bytes(b"tagged audio")
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=30,
                media_type=MediaType.MOVIE,
                title="Movie",
                folder_path=str(tmp_path),
                theme_provenance_cleared=True,
            )
        )
    probe = AsyncMock(
        return_value=ThemeAudioMetadata(
            duration=35,
            youtube_id="abcDEF123_4",
            title="Theme",
        )
    )
    monkeypatch.setattr(
        "overture.services.local_assets.theme.ffprobe_theme_metadata", probe
    )
    assert await _refresh(30, AssetStorage(app_config=app_config), database)
    probe.assert_not_awaited()
    async with database.read_session() as session:
        item = await session.get(MediaItem, 30)
        assert item is not None
        assert item.youtube_id is None
        assert item.youtube_title is None
        assert item.youtube_duration is None
        assert item.theme_file_hash is not None


@pytest.mark.parametrize("concurrent_clear", [False, True])
async def test_file_inspection_releases_writer_lock_and_preserves_concurrent_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    concurrent_clear: bool,
    app_config: Settings,
    database: Database,
) -> None:
    (tmp_path / "theme.mp3").write_bytes(b"tagged audio")
    async with database.write_session() as session:
        session.add(
            MediaItem(
                id=40,
                media_type=MediaType.MOVIE,
                title="Movie",
                folder_path=str(tmp_path),
            )
        )

    storage = AssetStorage(app_config=app_config)
    original_hash = storage.file_hash_async

    async def hash_file(path: Path) -> str | None:
        assert not database.write_lock.locked()
        return await original_hash(path)

    async def probe(_path: Path) -> ThemeAudioMetadata:
        assert not database.write_lock.locked()
        async with asyncio.timeout(1), database.write_session() as session:
            item = await session.get(MediaItem, 40)
            assert item is not None
            if concurrent_clear:
                item.theme_provenance_cleared = True
            else:
                item.youtube_id = "dQw4w9WgXcQ"
                item.theme_file_hash = "new-download"
        return ThemeAudioMetadata(duration=35, youtube_id="abcDEF123_4", title="Old")

    monkeypatch.setattr(storage, "file_hash_async", hash_file)
    monkeypatch.setattr(
        "overture.services.local_assets.theme.ffprobe_theme_metadata", probe
    )
    assert not await _refresh(40, storage, database)
    async with database.read_session() as session:
        item = await session.get(MediaItem, 40)
        assert item is not None
        assert item.youtube_id == (None if concurrent_clear else "dQw4w9WgXcQ")
        assert item.theme_provenance_cleared == concurrent_clear
        assert item.theme_file_hash == (None if concurrent_clear else "new-download")
