"""Export drafts and saved selections as OvertureDB source files."""

lazy import json
lazy import sqlite3
lazy from contextlib import closing
lazy from pathlib import Path
lazy from tempfile import TemporaryDirectory
lazy from typing import Any, cast, override
lazy from zipfile import ZIP_DEFLATED, ZipFile

lazy from fastapi.responses import FileResponse
lazy from sqlalchemy.orm import QueryableAttribute, selectinload
lazy from sqlmodel import col, select
lazy from starlette.types import Receive, Scope, Send

lazy from ...db.art_slots import read_art_slot
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...db.models.public_dataset import PublicDatasetCollection
lazy from ...db.models.season import Season
lazy from ...db.session import PAGE_SIZE, Database
lazy from ...domain import ArtType, CatalogMediaType, MediaType, ThemeBulkSource
lazy from ...repositories.collections import CollectionRepository
lazy from ...repositories.public_dataset import PublicDatasetRepository
lazy from ...repositories.public_dataset_drafts import PublicDatasetDraftRepository
lazy from ...utils.art_urls import art_refusals
lazy from ...utils.errors import PublicServiceError
lazy from ...utils.temporary import create_operation_directory
lazy from ...utils.threads import owned_thread
lazy from .schema.contract import (
    catalog_art_url,
    entry_identities,
    entry_repo_path,
    validate_entry,
)


def _initialize(directory: Path) -> None:
    with closing(sqlite3.connect(directory / "export.sqlite")) as connection:
        connection.executescript(
            "CREATE TABLE files (path TEXT PRIMARY KEY, content TEXT); "
            "CREATE TABLE identities (media TEXT, provider TEXT, value TEXT, "
            "drafted INTEGER, PRIMARY KEY(media, provider, value));"
        )


def _catalog_art_url(url: str | None) -> str | None:
    """Return a saved selection in its catalog form, or None outside the catalog."""
    if not url:
        return None
    try:
        return catalog_art_url(url)
    except ValueError:
        return None


def _item_entry(item: MediaItem) -> dict[str, Any] | None:
    """Return a library item's selections as a catalog entry, if it has any."""
    poster = _catalog_art_url(read_art_slot(item, ArtType.POSTER).url)
    background = _catalog_art_url(read_art_slot(item, ArtType.BACKGROUND).url)
    seasons = [
        {"season_num": season.season_num, "poster_url": url}
        for season in sorted(item.seasons, key=lambda season: season.season_num)
        if (url := _catalog_art_url(read_art_slot(season, ArtType.SEASON_POSTER).url))
    ]
    if not (poster or background or item.youtube_id or seasons):
        return None
    entry: dict[str, Any] = {
        "media_type": item.media_type.value,
        "title": item.title,
        "year": item.year,
        "tmdb_id": item.tmdb_id,
        "tvdb_id": item.tvdb_id,
        "imdb_id": item.imdb_id,
        "poster_url": poster,
        "background_url": background,
        "youtube_id_overturedb": item.youtube_id,
        "youtube_id_themerrdb": None,
    }
    if item.media_type == MediaType.SHOW:
        entry["seasons"] = seasons
    return entry


def _collection_entry(
    collection: MediaCollection, catalog: PublicDatasetCollection | None
) -> dict[str, Any] | None:
    """Return a matched collection's art and theme as a catalog entry, if any.

    A ThemerrDB theme is not OvertureDB's to take, so it is left out.
    """
    if collection.tmdb_collection_id is None:
        return None
    poster = _catalog_art_url(read_art_slot(collection, ArtType.POSTER).url)
    background = _catalog_art_url(read_art_slot(collection, ArtType.BACKGROUND).url)
    theme = collection.youtube_id
    if collection.youtube_id_source is ThemeBulkSource.THEMERRDB or (
        catalog and theme == catalog.youtube_id_themerrdb
    ):
        theme = None
    if not (poster or background or theme):
        return None
    return {
        "media_type": CatalogMediaType.COLLECTION.value,
        "title": catalog.title if catalog else collection.title,
        "tmdb_id": collection.tmdb_collection_id,
        "poster_url": poster,
        "background_url": background,
        "youtube_id_overturedb": theme,
        "youtube_id_themerrdb": None,
    }


def _stage_batch(
    directory: Path,
    entries: list[dict[str, Any]],
    *,
    drafts: bool = False,
    covered_identities: list[tuple[str, str, str]] | None = None,
) -> None:
    """Stage valid entries; a draft takes precedence over library selections.

    Raises:
        PublicServiceError: When two staged entries claim one identity.
    """
    with closing(sqlite3.connect(directory / "export.sqlite")) as connection:
        for entry in entries:
            try:
                validate_entry(entry)
            except ValueError:
                continue
            keys = [
                (media, field, str(value))
                for media, field, value in entry_identities(entry)
            ]
            if not drafts and any(
                connection.execute(
                    "SELECT 1 FROM identities WHERE media = ? AND provider = ? "
                    "AND value = ? AND drafted",
                    key,
                ).fetchone()
                for key in keys
            ):
                continue
            path = entry_repo_path(entry)
            content = json.dumps(entry, ensure_ascii=False, indent=2) + "\n"
            previous = connection.execute(
                "SELECT content FROM files WHERE path = ?", (path,)
            ).fetchone()
            if previous is not None and previous[0] == content:
                continue
            try:
                connection.executemany(
                    "INSERT INTO identities VALUES (?, ?, ?, ?)",
                    [(*key, drafts) for key in keys],
                )
                connection.execute("INSERT INTO files VALUES (?, ?)", (path, content))
            except sqlite3.IntegrityError as exc:
                raise PublicServiceError(
                    422, "Resolve conflicting library selections before exporting"
                ) from exc
        if covered_identities:
            connection.executemany(
                "INSERT OR IGNORE INTO identities VALUES (?, ?, ?, 1)",
                covered_identities,
            )
        connection.commit()


#: The export summary in the archive; the bulk import reads only its JSON files.
REPORT_NAME = "EXPORT-REPORT.txt"


def _archive(directory: Path, left_out: list[str]) -> Path:
    target = directory / "overturedb-selections.zip"
    with (
        closing(sqlite3.connect(directory / "export.sqlite")) as connection,
        ZipFile(target, "w", compression=ZIP_DEFLATED) as archive,
    ):
        for path, content in connection.execute(
            "SELECT path, content FROM files ORDER BY path"
        ):
            archive.writestr(path, content)
        if left_out:
            archive.writestr(
                REPORT_NAME,
                "Left out of this export:\n"
                + "".join(f"- {line}\n" for line in left_out),
            )
    return target


def _left_out(title: str, owner: MediaItem | MediaCollection) -> list[str]:
    """The selected art OvertureDB would refuse, as lines of the export summary."""
    return [
        f"{title}: {line}"
        for line in art_refusals(
            read_art_slot(owner, ArtType.POSTER).url,
            read_art_slot(owner, ArtType.BACKGROUND).url,
        )
    ]


async def export_selections(database: Database, directory: Path) -> Path:
    """Page detached selections; never keep a session during archive I/O.

    Drafts made in the catalog view go first, then library selections, then
    the themes chosen for matched collections.
    """
    await owned_thread(_initialize, directory)
    left_out: list[str] = []
    async with database.read_session() as session:
        drafts = await PublicDatasetDraftRepository(session).list_all()
    await owned_thread(
        _stage_batch,
        directory,
        [draft.entry for draft in drafts],
        drafts=True,
        covered_identities=[
            (draft.media_type.value, name, str(value))
            for draft in drafts
            for name in ("tmdb_id", "tvdb_id", "imdb_id")
            if (value := getattr(draft, name)) is not None
        ],
    )
    after = 0
    while True:
        async with database.read_session() as session:
            items = list(
                (
                    await session.exec(
                        select(MediaItem)
                        .where(
                            col(MediaItem.server_removed_at).is_(None),
                            col(MediaItem.id) > after,
                        )
                        .options(
                            selectinload(
                                cast(
                                    "QueryableAttribute[list[Season]]",
                                    MediaItem.seasons,
                                )
                            )
                        )
                        .order_by(col(MediaItem.id))
                        .limit(PAGE_SIZE)
                    )
                ).all()
            )
        if not items:
            break
        entries = [entry for item in items if (entry := _item_entry(item))]
        left_out.extend(line for item in items for line in _left_out(item.title, item))
        await owned_thread(_stage_batch, directory, entries)
        after = items[-1].id or after
    async with database.read_session() as session:
        collections = await CollectionRepository(session).list_listed()
        catalog = await PublicDatasetRepository(session).collections_by_tmdb_id(
            {row.tmdb_collection_id for row in collections if row.tmdb_collection_id}
        )
    entries = [
        entry
        for row in collections
        if (entry := _collection_entry(row, catalog.get(row.tmdb_collection_id or 0)))
    ]
    left_out.extend(
        line
        for row in collections
        if row.tmdb_collection_id is not None
        for line in _left_out(row.title, row)
    )
    await owned_thread(_stage_batch, directory, entries)
    return await owned_thread(_archive, directory, left_out)


class _ArchiveResponse(FileResponse):
    """An export archive, whose operation directory goes once it is sent."""

    def __init__(self, path: Path, directory: TemporaryDirectory[str]) -> None:
        super().__init__(path, media_type="application/zip", filename=path.name)
        self.directory = directory

    @override
    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await super().__call__(scope, receive, send)
        finally:
            await owned_thread(self.directory.cleanup)


async def export_archive(database: Database, config_dir: Path) -> FileResponse:
    """Export saved selections as a zip archive, without holding it in memory."""
    directory = create_operation_directory(config_dir)
    try:
        path = await export_selections(database, Path(directory.name))
        return _ArchiveResponse(path, directory)
    except BaseException:
        await owned_thread(directory.cleanup)
        raise
