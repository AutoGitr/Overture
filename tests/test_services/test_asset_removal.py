"""Removing art and themes: forgetting, deleting local files and server copies."""

lazy from collections.abc import Collection
lazy from pathlib import Path
lazy from typing import Any

lazy import pytest
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.art_slots import read_art_slot
lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import ArtType, MediaType, ServerAsset
lazy from overture.media_servers.adapters import ServerTheme
lazy from overture.schemas.removal import AssetRemoval, RemovalTarget
lazy from overture.services.storage.assets import AssetStorage, PathTraversalError
lazy from overture.utils.errors import PublicServiceError
lazy from tests.factories import seed_art_slot
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    database_for,
    make_runtime,
    one_session,
)

JPEG = b"\xff\xd8\xff\xe0jpeg"
PNG = b"\x89PNG\r\n\x1a\npng"
MP3 = b"ID3\x04mp3"


class Server:
    """A media server recording what it is asked to delete and refresh."""

    def __init__(
        self,
        *,
        art_deletion_unavailable: str | None = None,
        themes: list[ServerTheme] | None = None,
    ) -> None:
        self.art_deletion_unavailable = art_deletion_unavailable
        self.themes = themes or []
        self.deleted_art: list[tuple[str, ArtType]] = []
        self.deleted_themes: list[tuple[str, str | None]] = []
        self.refreshed: list[tuple[str, set[ServerAsset]]] = []

    async def delete_art(self, server_id: str, art_type: ArtType) -> None:
        self.deleted_art.append((server_id, art_type))

    async def get_theme_songs(self, server_item_id: str) -> list[ServerTheme]:
        return self.themes

    async def delete_theme(self, server_item_id: str, theme_id: str | None) -> None:
        self.deleted_themes.append((server_item_id, theme_id))

    async def refresh_item(
        self, item_id: str, *, unlock: Collection[ServerAsset]
    ) -> None:
        self.refreshed.append((item_id, set(unlock)))


@pytest.mark.parametrize(
    ("name", "data"),
    [("poster.jpg", JPEG), ("poster.png", PNG), ("theme.mp3", MP3)],
)
def test_a_managed_image_or_theme_is_deleted(
    tmp_path: Path, app_config: Settings, name: str, data: bytes
) -> None:
    (tmp_path / name).write_bytes(data)

    assert AssetStorage(app_config=app_config).delete_file(
        tmp_path / name, str(tmp_path)
    )
    assert not (tmp_path / name).exists()


@pytest.mark.parametrize(
    ("name", "data"),
    [
        # A file named like art whose bytes are something else stays.
        ("poster.jpg", b"#!/bin/sh"),
        ("poster.png", JPEG),
        ("theme.mp3", b"RIFFwav"),
        # Nothing but images and the theme is ever deleted, whatever it holds.
        ("movie.mkv", JPEG),
        ("notes.mp3", MP3),
    ],
)
def test_anything_else_is_never_deleted(
    tmp_path: Path, app_config: Settings, name: str, data: bytes
) -> None:
    (tmp_path / name).write_bytes(data)

    with pytest.raises(PathTraversalError):
        AssetStorage(app_config=app_config).delete_file(tmp_path / name, str(tmp_path))
    assert (tmp_path / name).read_bytes() == data


def test_a_link_or_a_path_outside_the_folder_is_never_deleted(
    tmp_path: Path, app_config: Settings
) -> None:
    folder, outside = tmp_path / "Movie", tmp_path / "Other"
    folder.mkdir()
    outside.mkdir()
    (outside / "poster.jpg").write_bytes(JPEG)
    (folder / "background.jpg").symlink_to(outside / "poster.jpg")
    storage = AssetStorage(app_config=app_config)

    for path in (folder / "background.jpg", folder / ".." / "Other" / "poster.jpg"):
        with pytest.raises(PathTraversalError):
            storage.delete_file(path, str(folder))
    assert (outside / "poster.jpg").read_bytes() == JPEG
    assert not storage.delete_file(folder / "poster.jpg", str(folder))


def _media_folder(folder: Path) -> None:
    folder.mkdir()
    (folder / "poster.jpg").write_bytes(JPEG)
    (folder / "theme.mp3").write_bytes(MP3)
    (folder / "movie.mkv").write_bytes(b"video")


async def _item(db_session: AsyncSession, folder: Path, **fields: Any) -> MediaItem:
    _media_folder(folder)
    item = MediaItem(
        id=1,
        media_type=MediaType.MOVIE,
        title="Movie",
        folder_path=str(folder),
        server_item_id="srv-1",
        youtube_id="abcDEF123_4",
        theme_file_hash="theme",
        theme_file_size=len(MP3),
        theme_file_mtime_ns=1,
        **fields,
    )
    seed_art_slot(
        item,
        ArtType.POSTER,
        url="https://image.tmdb.org/t/p/original/p.jpg",
        file_hash="poster",
        file_mtime_ns=1,
        file_size=len(JPEG),
    )
    db_session.add(item)
    await db_session.commit()
    return item


def _runtime(
    tmp_path: Path, db_session: AsyncSession, server: Server, app_config: Settings
):
    return make_runtime(
        config_dir=tmp_path / "config",
        provider_registry=NoopProviderRegistry(server),
        app_config=app_config,
        database=database_for(one_session(db_session)),
    )


async def test_options_say_what_each_choice_would_remove(
    tmp_path: Path, db_session: AsyncSession, app_config: Settings
) -> None:
    await _item(db_session, tmp_path / "Movie")
    runtime = _runtime(tmp_path, db_session, Server(), app_config)

    poster = await runtime.remover.options(
        RemovalTarget(asset=ArtType.POSTER, item_ids=[1])
    )
    assert (poster.forget.count, poster.delete_file.count) == (1, 1)
    assert poster.delete_from_server.count == 1
    background = await runtime.remover.options(
        RemovalTarget(asset=ArtType.BACKGROUND, item_ids=[1])
    )
    assert background.forget.unavailable == "Nothing is selected"
    assert background.delete_file.unavailable == "There is no local file"

    plex = _runtime(
        tmp_path,
        db_session,
        Server(art_deletion_unavailable="Plex's API cannot delete artwork"),
        app_config,
    )
    refused = await plex.remover.options(
        RemovalTarget(asset=ArtType.POSTER, item_ids=[1])
    )
    assert refused.delete_from_server.unavailable == "Plex's API cannot delete artwork"
    assert refused.delete_from_server.count == 0


async def test_deleting_art_removes_the_file_and_the_server_copy_and_keeps_the_rest(
    tmp_path: Path, db_session: AsyncSession, app_config: Settings
) -> None:
    folder = tmp_path / "Movie"
    await _item(db_session, folder)
    server = Server()
    runtime = _runtime(tmp_path, db_session, server, app_config)

    await runtime.art.remove(
        1,
        ArtType.POSTER,
        AssetRemoval(forget=False, delete_file=True, delete_from_server=True),
    )

    assert not (folder / "poster.jpg").exists()
    assert (folder / "movie.mkv").read_bytes() == b"video"
    assert (folder / "theme.mp3").read_bytes() == MP3
    assert server.deleted_art == [("srv-1", ArtType.POSTER)]
    assert server.refreshed == [("srv-1", {ServerAsset.POSTER})]
    item = await db_session.get(MediaItem, 1)
    assert item is not None
    await db_session.refresh(item)
    slot = read_art_slot(item, ArtType.POSTER)
    # The selection was kept: only the file and the server's copy went.
    assert (slot.url, slot.file_hash) == (
        "https://image.tmdb.org/t/p/original/p.jpg",
        None,
    )


async def test_a_server_that_cannot_delete_art_is_refused_before_anything_goes(
    tmp_path: Path, db_session: AsyncSession, app_config: Settings
) -> None:
    folder = tmp_path / "Movie"
    await _item(db_session, folder)
    runtime = _runtime(
        tmp_path,
        db_session,
        Server(art_deletion_unavailable="Plex's API cannot delete artwork"),
        app_config,
    )

    with pytest.raises(PublicServiceError) as raised:
        await runtime.art.remove(
            1, "art", AssetRemoval(delete_file=True, delete_from_server=True)
        )

    assert raised.value.status_code == 409
    assert (folder / "poster.jpg").read_bytes() == JPEG


async def test_deleting_a_theme_removes_only_mp3_theme_songs(
    tmp_path: Path, db_session: AsyncSession, app_config: Settings
) -> None:
    folder = tmp_path / "Movie"
    await _item(db_session, folder)
    server = Server(
        themes=[
            ServerTheme(id="t1", path="/media/Movie/theme.mp3"),
            ServerTheme(id="t2", path="/media/Movie/theme-music/song.flac"),
        ]
    )
    runtime = _runtime(tmp_path, db_session, server, app_config)

    await runtime.themes.remove(
        1, AssetRemoval(delete_file=True, delete_from_server=True)
    )

    assert not (folder / "theme.mp3").exists()
    assert server.deleted_themes == [("srv-1", "t1")]
    assert server.refreshed == [("srv-1", {ServerAsset.THEME})]
    item = await db_session.get(MediaItem, 1)
    assert item is not None
    await db_session.refresh(item)
    assert (item.youtube_id, item.theme_file_hash) == (None, None)
