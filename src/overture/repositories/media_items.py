"""Media item query helpers."""

lazy from collections.abc import Collection
lazy from datetime import datetime
lazy from itertools import batched
lazy from pathlib import Path
lazy from typing import Any, NamedTuple, cast

lazy from sqlalchemy.orm import QueryableAttribute, raiseload
lazy from sqlalchemy.sql.elements import ColumnElement
lazy from sqlmodel import case, col, delete, func, or_, select, update
lazy from sqlmodel.ext.asyncio.session import AsyncSession
lazy from sqlmodel.sql.expression import SelectOfScalar

lazy from ..db.completion import HOLDS_FILES
lazy from ..db.models.art import ArtSlot
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.season import Season
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import (
    MediaType,
    guid_int,
    guid_text,
    media_sort_key,
    text_sort_key,
)
lazy from ..schemas.library import BulkItemOperation
lazy from ..services.public_dataset.schema.contract import IDENTITY_FIELDS


class ServerItemFacts(NamedTuple):
    """What a collection needs to know about one of its member items."""

    id: int
    media_type: MediaType
    library_id: str | None
    tmdb_collection_id: int | None


def _matching(load_art: bool) -> SelectOfScalar[MediaItem]:
    """Select media items, with their artwork slots unless *load_art* is off.

    A lookup that only identifies the row skips loading its slots; reading
    them from such a row raises rather than finding none.
    """
    stmt = select(MediaItem)
    return (
        stmt
        if load_art
        else stmt.options(
            raiseload(cast("QueryableAttribute[list[ArtSlot]]", MediaItem.art_slots))
        )
    )


def _folder_key(path: str) -> str:
    """Return a folder path with one separator style and no trailing separator."""
    return path.rstrip("/\\").replace("\\", "/")


def _folder_variants(path: str) -> set[str]:
    """Return every spelling a stored folder path may have for *path*."""
    stripped = path.rstrip("/\\")
    posix, windows = stripped.replace("\\", "/"), stripped.replace("/", "\\")
    return {
        path,
        stripped,
        f"{stripped}/",
        f"{stripped}\\",
        posix,
        windows,
        f"{posix}/",
        f"{windows}\\",
    }


class MediaItemRepository:
    """Centralize recurring media-item persistence operations."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def find_by_server_id(
        self,
        server_item_id: str,
        media_type: str,
        *,
        exclude_item_ids: set[int] | None = None,
        load_art: bool = True,
    ) -> MediaItem | None:
        """Return a media item by media-server ID and type."""
        stmt = _matching(load_art).where(
            col(MediaItem.server_item_id) == server_item_id,
            col(MediaItem.media_type) == media_type,
        )
        if exclude_item_ids:
            stmt = stmt.where(col(MediaItem.id).notin_(exclude_item_ids))
        stmt = stmt.order_by(col(MediaItem.server_removed_at).is_(None).desc()).limit(1)
        result = await self.session.exec(stmt)
        return result.first()

    async def find_by_external_guids(
        self,
        guids: dict[str, str],
        media_type: str,
        *,
        server_item_id: str | None = None,
        exclude_item_ids: set[int] | None = None,
        load_art: bool = True,
    ) -> MediaItem | None:
        """Return a media item by external GUIDs, preferring TMDB then TVDB.

        ORDER BY over a CASE preserves provider priority in a single query.
        """
        matches: list[tuple[int, ColumnElement[bool]]] = []
        for rank, (provider, column) in enumerate(
            (
                ("tmdb", col(MediaItem.tmdb_id)),
                ("tvdb", col(MediaItem.tvdb_id)),
                ("imdb", col(MediaItem.imdb_id)),
            )
        ):
            value = (
                guid_text(guids, provider)
                if provider == "imdb"
                else guid_int(guids, provider)
            )
            if value is not None:
                matches.append((rank, column == value))

        if not matches:
            return None

        priority = case(*((clause, rank) for rank, clause in matches), else_=None)
        stmt = _matching(load_art).where(
            col(MediaItem.media_type) == media_type,
            or_(*(clause for _rank, clause in matches)),
        )
        if exclude_item_ids:
            stmt = stmt.where(col(MediaItem.id).notin_(exclude_item_ids))

        order_clauses: list[ColumnElement[Any]] = []
        if server_item_id is not None:
            order_clauses.append(
                (col(MediaItem.server_item_id) == server_item_id).desc()
            )
        order_clauses.extend(
            (col(MediaItem.server_removed_at).is_(None).desc(), priority)
        )

        stmt = stmt.order_by(*order_clauses).limit(1)
        result = await self.session.exec(stmt)
        return result.first()

    async def ids_by_tmdb_ids(
        self, media_type: MediaType, tmdb_ids: Collection[int]
    ) -> dict[int, int]:
        """Return item IDs keyed by TMDB ID, preferring items still present."""
        if not tmdb_ids:
            return {}
        result = await self.session.exec(
            select(MediaItem.tmdb_id, MediaItem.id)
            .where(
                col(MediaItem.media_type) == media_type,
                col(MediaItem.tmdb_id).in_(tmdb_ids),
            )
            .order_by(col(MediaItem.server_removed_at).is_(None))
        )
        # Present items sort last, so they win.
        return {
            tmdb_id: item_id
            for tmdb_id, item_id in result.all()
            if tmdb_id is not None and item_id is not None
        }

    async def directors_by_version(
        self, server_item_ids: Collection[str]
    ) -> dict[tuple[str, str], str | None]:
        """Return stored movie directors keyed by server ID and director Etag."""
        if not server_item_ids:
            return {}
        result = await self.session.exec(
            select(
                MediaItem.server_item_id, MediaItem.director_etag, MediaItem.director
            ).where(
                col(MediaItem.media_type) == MediaType.MOVIE,
                col(MediaItem.server_item_id).in_(server_item_ids),
                col(MediaItem.director_etag).is_not(None),
            )
        )
        return {
            (server_id, etag): director
            for server_id, etag, director in result.all()
            if server_id is not None and etag is not None
        }

    async def find_by_folder_path(
        self,
        folder_path: str,
        media_type: str,
        *,
        exclude_item_ids: set[int] | None = None,
        load_art: bool = True,
    ) -> MediaItem | None:
        """Return a media item by filesystem folder path and type."""
        stmt = _matching(load_art).where(
            col(MediaItem.folder_path).in_(_folder_variants(folder_path)),
            col(MediaItem.media_type) == media_type,
        )
        if exclude_item_ids:
            stmt = stmt.where(col(MediaItem.id).notin_(exclude_item_ids))
        stmt = stmt.order_by(col(MediaItem.server_removed_at).is_(None).desc()).limit(1)
        result = await self.session.exec(stmt)
        return result.first()

    async def by_folder_paths(self, folders: Collection[str]) -> dict[str, MediaItem]:
        """Return the items stored at *folders*, keyed by the folder asked for.

        Separators and trailing slashes do not matter. A visible item wins
        over a removed one at the same folder.
        """
        wanted = {_folder_key(folder): folder for folder in folders}
        if not wanted:
            return {}
        rows = await self.session.exec(
            _matching(load_art=False)
            .where(
                col(MediaItem.folder_path).in_(
                    {
                        variant
                        for folder in folders
                        for variant in _folder_variants(folder)
                    }
                )
            )
            .order_by(col(MediaItem.server_removed_at).is_(None).desc())
        )
        found: dict[str, MediaItem] = {}
        for item in rows.all():
            if item.folder_path is not None:
                found.setdefault(wanted[_folder_key(item.folder_path)], item)
        return found

    async def list_bulk_targets(
        self,
        library_ids: list[str] | None = None,
        *,
        item_ids: list[int] | None = None,
        include_unmonitored: bool = False,
        after_id: int = 0,
        limit: int | None = None,
    ) -> list[MediaItem]:
        """Return present items in either scope, monitored unless opted out.

        Items without a local folder are left out: a bulk run writes files.
        """
        stmt = select(MediaItem).where(
            col(MediaItem.server_removed_at).is_(None), HOLDS_FILES
        )
        if item_ids is not None:
            stmt = stmt.where(col(MediaItem.id).in_(item_ids))
        if not include_unmonitored:
            stmt = stmt.where(col(MediaItem.monitored).is_(True))
        if library_ids:
            stmt = stmt.where(col(MediaItem.library_id).in_(library_ids))
        stmt = stmt.where(col(MediaItem.id) > after_id).order_by(col(MediaItem.id))
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.exec(stmt)
        return sorted(
            result.all(),
            key=lambda item: media_sort_key(item.media_type, item.title, item.id),
        )

    async def list_monitored_with_folder_paths(
        self,
        *,
        item_ids: Collection[int] | None = None,
        after_id: int = 0,
        limit: int | None = None,
    ) -> list[MediaItem]:
        """Return monitored, still-present media items with local folder paths."""
        stmt = select(MediaItem).where(
            col(MediaItem.monitored).is_(True),
            col(MediaItem.folder_path).is_not(None),
            col(MediaItem.server_removed_at).is_(None),
        )
        if item_ids is not None:
            stmt = stmt.where(col(MediaItem.id).in_(item_ids))
        stmt = stmt.where(col(MediaItem.id) > after_id).order_by(col(MediaItem.id))
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.exec(stmt)
        return sorted(
            result.all(),
            key=lambda item: media_sort_key(item.media_type, item.title, item.id),
        )

    async def list_visible_with_folder_paths(
        self,
        *,
        after_id: int = 0,
        limit: int | None = None,
        media_type: MediaType | None = None,
        library_id: str | None = None,
        library_ids: list[str] | None = None,
        item_ids: Collection[int] | None = None,
    ) -> list[MediaItem]:
        """Return visible items whose local files can be inspected."""
        stmt = select(MediaItem).where(
            col(MediaItem.folder_path).is_not(None),
            col(MediaItem.server_removed_at).is_(None),
        )
        if item_ids is not None:
            stmt = stmt.where(col(MediaItem.id).in_(item_ids))
        if media_type is not None:
            stmt = stmt.where(col(MediaItem.media_type) == media_type)
        if library_id is not None:
            stmt = stmt.where(col(MediaItem.library_id) == library_id)
        if library_ids is not None:
            stmt = stmt.where(col(MediaItem.library_id).in_(library_ids))
        stmt = stmt.where(col(MediaItem.id) > after_id).order_by(col(MediaItem.id))
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.exec(stmt)
        return list(result.all())

    async def list_visible_with_server_ids(
        self,
        library_ids: list[str] | None = None,
        *,
        after_id: int = 0,
        limit: int | None = None,
    ) -> list[MediaItem]:
        """Return visible media items that have media-server IDs."""
        stmt = select(MediaItem).where(
            col(MediaItem.server_item_id).is_not(None),
            col(MediaItem.server_removed_at).is_(None),
        )
        if library_ids:
            stmt = stmt.where(col(MediaItem.library_id).in_(library_ids))
        if after_id:
            stmt = stmt.where(col(MediaItem.id) > after_id)
        if limit is not None:
            stmt = stmt.order_by(col(MediaItem.id)).limit(limit)
        result = await self.session.exec(stmt)
        return sorted(
            result.all(),
            key=lambda item: media_sort_key(item.media_type, item.title, item.id),
        )

    async def facts_by_server_id(self) -> dict[str, ServerItemFacts]:
        """Return the visible linked items by media-server ID, without artwork."""
        stmt = _matching(load_art=False).where(
            col(MediaItem.server_item_id).is_not(None),
            col(MediaItem.server_removed_at).is_(None),
        )
        return {
            item.server_item_id: ServerItemFacts(
                item.id, item.media_type, item.library_id, item.tmdb_collection_id
            )
            for item in await self.session.exec(stmt)
            if item.server_item_id is not None and item.id is not None
        }

    async def visible_ids_by_identity(
        self,
        media_type: MediaType,
        identities: list[tuple[str, int | str]] | None = None,
    ) -> dict[tuple[str, int | str], int]:
        """Return visible item IDs keyed by each ``(field, value)`` they carry."""
        stmt = _matching(load_art=False).where(
            col(MediaItem.media_type) == media_type,
            col(MediaItem.server_removed_at).is_(None),
        )
        if identities is not None:
            if not identities:
                return {}
            stmt = stmt.where(
                or_(
                    *(
                        col(getattr(MediaItem, name)) == value
                        for name, value in identities
                    )
                )
            )
        found: dict[tuple[str, int | str], int] = {}
        for item in await self.session.exec(stmt):
            for field in IDENTITY_FIELDS:
                value = getattr(item, field)
                if value is not None and item.id is not None:
                    found.setdefault((field, value), item.id)
        return found

    async def tmdb_collection_ids(self, item_ids: list[int]) -> list[int | None]:
        """Return the TMDB collection of each visible item among *item_ids*."""
        found: list[int | None] = []
        for batch in batched(item_ids, CHUNK_SIZE, strict=False):
            stmt = select(MediaItem.tmdb_collection_id).where(
                col(MediaItem.id).in_(batch),
                col(MediaItem.server_removed_at).is_(None),
            )
            found.extend(await self.session.exec(stmt))
        return found

    async def movies_without_tmdb_collection_check(self) -> list[tuple[int, int]]:
        """Return ``(id, tmdb_id)`` of visible movies whose collection is unknown."""
        stmt = select(MediaItem.id, MediaItem.tmdb_id).where(
            col(MediaItem.media_type) == MediaType.MOVIE,
            col(MediaItem.server_removed_at).is_(None),
            col(MediaItem.tmdb_id).is_not(None),
            or_(
                col(MediaItem.tmdb_collection_checked_id).is_(None),
                col(MediaItem.tmdb_collection_checked_id) != col(MediaItem.tmdb_id),
            ),
        )
        return [
            (item_id, tmdb_id)
            for item_id, tmdb_id in await self.session.exec(stmt)
            if item_id is not None and tmdb_id is not None
        ]

    async def list_unconnected_tmdb_shows(self) -> list[MediaItem]:
        """Return saved TMDB shows whose seasons are not supplied by a server."""
        result = await self.session.exec(
            select(MediaItem)
            .where(
                col(MediaItem.media_type) == MediaType.SHOW,
                col(MediaItem.tmdb_id).is_not(None),
                col(MediaItem.server_item_id).is_(None),
                col(MediaItem.server_removed_at).is_(None),
            )
            .order_by(col(MediaItem.id))
        )
        return list(result.all())

    async def library_counts(
        self, media_type: MediaType | None = None
    ) -> dict[str, int]:
        """Return visible media item counts keyed by media-server library ID."""
        stmt = (
            select(MediaItem.library_id, func.count())
            .where(
                col(MediaItem.library_id).is_not(None),
                col(MediaItem.server_removed_at).is_(None),
            )
            .group_by(col(MediaItem.library_id))
        )
        if media_type:
            stmt = stmt.where(col(MediaItem.media_type) == media_type)

        result = await self.session.exec(stmt)
        return {str(library_id): count for library_id, count in result.all()}

    async def folder_paths(self) -> list[str]:
        """Return every stored media item folder path."""
        stmt = select(MediaItem.folder_path).where(
            col(MediaItem.folder_path).is_not(None)
        )
        result = await self.session.exec(stmt)
        return [path for path in result.all() if path]

    async def item_folders(self, item_ids: list[int]) -> list[tuple[str, str]]:
        """Return ``(folder_path, media_type)`` for present items with folders."""
        stmt = select(MediaItem.folder_path, MediaItem.media_type).where(
            col(MediaItem.id).in_(item_ids),
            col(MediaItem.folder_path).is_not(None),
            col(MediaItem.server_removed_at).is_(None),
        )
        result = await self.session.exec(stmt)
        return [(path, str(media_type)) for path, media_type in result.all() if path]

    async def folder_roots(self) -> dict[str, list[str]]:
        """Return unique parent roots from visible media item folder paths."""
        stmt = select(MediaItem.folder_path, MediaItem.media_type).where(
            col(MediaItem.folder_path).is_not(None),
            col(MediaItem.server_removed_at).is_(None),
        )
        result = await self.session.exec(stmt)

        roots: dict[str, set[str]] = {"movies": set(), "shows": set()}
        keys: dict[MediaType | str, str] = {
            MediaType.MOVIE: "movies",
            MediaType.SHOW: "shows",
        }

        for folder_path, media_type in result.all():
            key = keys.get(media_type)
            if not folder_path or key is None:
                continue
            parent = str(Path(folder_path.rstrip("/")).parent)
            if not parent or parent == folder_path:
                continue
            roots[key].add(parent)

        return {
            name: sorted(values, key=text_sort_key) for name, values in roots.items()
        }

    async def list_visible(
        self, media_type: MediaType | None = None
    ) -> list[MediaItem]:
        """Return all visible media items, optionally of one type."""
        stmt = select(MediaItem).where(col(MediaItem.server_removed_at).is_(None))
        if media_type:
            stmt = stmt.where(col(MediaItem.media_type) == media_type)
        result = await self.session.exec(stmt)
        return sorted(
            result.all(),
            key=lambda item: media_sort_key(item.media_type, item.title, item.id),
        )

    async def mark_matched(self, item_ids: set[int], when: datetime) -> None:
        """Stamp ``last_matched_at`` on many items with one statement."""
        if not item_ids:
            return
        await self.session.exec(
            update(MediaItem)
            .where(col(MediaItem.id).in_(item_ids))
            .values(last_matched_at=when)
        )

    async def mark_synced(self, item_ids: Collection[int], when: datetime) -> None:
        """Stamp many items as verified on and synced from the server at once."""
        if not item_ids:
            return
        await self.session.exec(
            update(MediaItem)
            .where(col(MediaItem.id).in_(item_ids))
            .values(server_verified_at=when, last_synced_at=when)
        )

    async def bulk_operate(self, body: BulkItemOperation) -> list[int]:
        """Use set-based statements, bounded to SQLite's parameter limit."""
        affected: list[int] = []
        for batch in batched(dict.fromkeys(body.item_ids), CHUNK_SIZE, strict=False):
            ids = [
                item_id
                for item_id in (
                    await self.session.exec(
                        select(col(MediaItem.id)).where(col(MediaItem.id).in_(batch))
                    )
                ).all()
                if item_id is not None
            ]
            if not ids:
                continue
            affected.extend(ids)
            target = col(MediaItem.id).in_(ids)
            if body.operation == "artwork":
                # Forget selections only: local files stay, and so do the facts
                # recorded about them. Rows left describing nothing are dropped.
                seasons = select(Season.id).where(col(Season.media_item_id).in_(ids))
                owned = or_(
                    col(ArtSlot.media_item_id).in_(ids),
                    col(ArtSlot.season_id).in_(seasons),
                )
                await self.session.exec(
                    update(ArtSlot)
                    .where(owned)
                    .values(url=None)
                    .execution_options(synchronize_session=False)
                )
                await self.session.exec(
                    delete(ArtSlot)
                    .where(owned, col(ArtSlot.file_hash).is_(None))
                    .execution_options(synchronize_session=False)
                )
            elif body.operation == "delete":
                await self.session.exec(delete(MediaItem).where(target))
            elif body.operation == "themes":
                # Mirrors clear_theme_selection: the local file and its facts stay.
                await self.session.exec(
                    update(MediaItem)
                    .where(target)
                    .values(
                        youtube_id=None,
                        youtube_id_source=None,
                        youtube_title=None,
                        youtube_duration=None,
                        theme_provenance_cleared=True,
                    )
                )
            else:
                await self.session.exec(
                    update(MediaItem)
                    .where(target)
                    .values(monitored=body.operation == "monitor")
                )
        return affected

    async def delete_removed_before(self, cutoff: datetime) -> int:
        """Delete items the media server dropped before *cutoff*.

        Seasons, artwork, and download jobs go with them through the cascading
        foreign keys, so this is the whole retention pass for a removed item.
        """
        stmt = delete(MediaItem).where(
            col(MediaItem.server_removed_at).is_not(None),
            col(MediaItem.server_removed_at) < cutoff,
        )
        result = await self.session.exec(stmt)
        return result.rowcount or 0
