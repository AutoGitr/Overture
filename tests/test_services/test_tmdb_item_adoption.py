"""A TMDB-chosen item keeps its selections when sync adopts it, then downloads them."""

lazy from pathlib import Path
lazy from typing import override

lazy import pytest
lazy from PIL import Image
lazy from sqlalchemy.ext.asyncio import async_sessionmaker
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.ledger import read_asset, select_art
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database
lazy from overture.domain import ArtType, MediaType, ServerAsset, ThemeIdSource
lazy from overture.jobs.progress_log import JobOutcome
lazy from overture.media_servers.adapters import ServerItem
lazy from overture.services.downloads.queue import JobTarget
lazy from overture.services.downloads.service import DownloadService
lazy from overture.services.sync.reconciler import LibraryReconciler
lazy from overture.utils.art_urls import PublicArtUrl
lazy from overture.utils.audio import ThemeAudioMetadata
lazy from overture.utils.locks import KeyedLock
lazy from tests.factories import file_hash_of, seed_theme, theme_file_hash, theme_of
lazy from tests.media_servers import copy_ids
lazy from tests.publishers import NullEventPublisher
lazy from tests.runtime_helpers import make_local_assets, row_id
lazy from tests.sync_helpers import sync_full

CHOSEN = "https://image.tmdb.org/t/p/original/chosen.jpg"


class RecordingDownloads(DownloadService):
    def __init__(self) -> None:
        self.jobs: list[JobTarget] = []
        self._asset_locks = KeyedLock[int | str]()

    @property
    @override
    def asset_locks(self) -> KeyedLock[int | str]:
        return self._asset_locks

    @override
    async def committed(self, session: AsyncSession) -> None:
        pass

    @override
    async def queue_job(
        self, session: AsyncSession, target: JobTarget, *, supersede: bool = True
    ) -> tuple[str, bool]:
        self.jobs.append(target)
        return f"job-{len(self.jobs)}", True


def _server_item(folder: Path) -> ServerItem:
    return ServerItem(
        id="plex-603",
        title="The Matrix",
        year=1999,
        guids={"tmdb": "603"},
        media_type=MediaType.MOVIE,
        poster_url="https://image.tmdb.org/t/p/original/server-poster.jpg",
        background_url="https://image.tmdb.org/t/p/original/server-bg.jpg",
        library_id="1:lib-1",
        folder_path=str(folder),
    )


@pytest.mark.parametrize("existing_files", [False, True])
async def test_adoption_keeps_the_choices_and_downloads_them(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
    existing_files: bool,
) -> None:
    async with isolated_session_factory() as session:
        item = seed_theme(
            MediaItem(
                media_type=MediaType.MOVIE,
                title="The Matrix",
                tmdb_id=603,
            ),
            "abcDEF123_4",
            source=ThemeIdSource.SELECTION,
        )
        select_art(item, ServerAsset.POSTER, PublicArtUrl(CHOSEN))
        session.add(item)
        await session.commit()
        item_id = row_id(item)
    folder = tmp_path / "The Matrix (1999)"
    folder.mkdir()
    if existing_files:
        Image.new("RGB", (40, 60), color="blue").save(folder / "poster.jpg")
        (folder / "theme.mp3").write_bytes(b"unrelated theme")

    async def probe(_path: Path) -> ThemeAudioMetadata:
        return ThemeAudioMetadata(
            duration=42,
            youtube_id="other1234567",
            youtube_id_source=ThemeIdSource.EMBEDDED_ID,
            title="Other theme",
        )

    monkeypatch.setattr(
        "overture.services.local_assets.theme.ffprobe_theme_metadata", probe
    )
    downloads = RecordingDownloads()
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    _, outcomes = await sync_full(reconciler, [_server_item(folder)])
    # A later sync fills the slots the user left empty.
    await sync_full(reconciler, [_server_item(folder)])

    assert outcomes[JobOutcome.ERROR] == 0, outcomes.lines
    async with isolated_session_factory() as session:
        (adopted,) = (await session.exec(select(MediaItem))).all()
        ids = await copy_ids(session)
    assert (adopted.id, ids[adopted.id or 0]) == (item_id, "plex-603")
    assert adopted.folder_path == str(folder)
    assert read_asset(adopted, ServerAsset.POSTER).url == CHOSEN
    assert bool(file_hash_of(read_asset(adopted, ServerAsset.POSTER))) == existing_files
    assert bool(theme_file_hash(adopted)) == existing_files
    assert (
        read_asset(adopted, ServerAsset.BACKGROUND).url
        == "https://image.tmdb.org/t/p/original/server-bg.jpg"
    )
    assert downloads.jobs == [
        JobTarget.art(item_id, ArtType.POSTER, CHOSEN),
        JobTarget.theme(item_id, "abcDEF123_4"),
    ]


async def test_adoption_does_not_download_a_theme_discovered_in_the_local_file(
    isolated_session_factory: async_sessionmaker[AsyncSession],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    async with isolated_session_factory() as session:
        item = MediaItem(media_type=MediaType.MOVIE, title="The Matrix", tmdb_id=603)
        session.add(item)
        await session.commit()
    (tmp_path / "theme.mp3").write_bytes(b"existing theme")

    async def probe(_path: Path) -> ThemeAudioMetadata:
        return ThemeAudioMetadata(
            duration=42,
            youtube_id="other1234567",
            youtube_id_source=ThemeIdSource.EMBEDDED_ID,
            title="Existing theme",
        )

    monkeypatch.setattr(
        "overture.services.local_assets.theme.ffprobe_theme_metadata", probe
    )
    downloads = RecordingDownloads()
    reconciler = LibraryReconciler(
        publisher=NullEventPublisher(),
        local_assets=make_local_assets(app_config=app_config, database=database),
        downloads=downloads,
        app_config=app_config,
        database=database,
    )

    _, outcomes = await sync_full(reconciler, [_server_item(tmp_path)])

    assert outcomes[JobOutcome.ERROR] == 0, outcomes.lines
    assert downloads.jobs == []
    async with isolated_session_factory() as session:
        (adopted,) = (await session.exec(select(MediaItem))).all()
        assert theme_of(adopted).youtube_id == "other1234567"
