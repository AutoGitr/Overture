"""Media item query helpers."""

lazy from collections.abc import Collection
lazy from datetime import datetime
lazy from itertools import batched
lazy from pathlib import Path
lazy from typing import Any, cast

lazy from sqlalchemy.orm import QueryableAttribute, raiseload
lazy from sqlalchemy.sql.elements import ColumnElement
lazy from sqlmodel import and_, case, col, delete, exists, or_, select, update
lazy from sqlmodel.ext.asyncio.session import AsyncSession
lazy from sqlmodel.sql.expression import Select, SelectOfScalar

lazy from ..catalog_contract.contract import IDENTITY_FIELDS
lazy from ..db.models.asset import Asset, AssetDelivery
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.media_item_copy import MediaItemCopy
lazy from ..db.models.season import Season
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import (
    ItemRecordOperation,
    MediaType,
    ServerAsset,
    guid_int,
    guid_text,
    media_sort_key,
    text_sort_key,
)
lazy from .copies import in_libraries, on_server


def _matching(for_update: bool) -> SelectOfScalar[MediaItem]:
    """Select media items, with their assets for an update.

    A lookup that only identifies the row skips loading them; reading them
    from such a row raises rather than finding none.
    """
    stmt = select(MediaItem)
    return (
        stmt
        if for_update
        else stmt.options(
            raiseload(cast("QueryableAttribute[list[Asset]]", MediaItem.assets))
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

    async def find_by_copy(
        self,
        server_id: int,
        server_item_id: str,
        media_type: str,
        *,
        exclude_item_ids: set[int] | None = None,
        for_update: bool = True,
    ) -> MediaItem | None:
        """Return the title a server keeps as *server_item_id*."""
        stmt = _matching(for_update).where(
            col(MediaItem.media_type) == media_type,
            col(MediaItem.id).in_(
                select(MediaItemCopy.media_item_id).where(
                    col(MediaItemCopy.server_id) == server_id,
                    col(MediaItemCopy.server_item_id) == server_item_id,
                )
            ),
        )
        if exclude_item_ids:
            stmt = stmt.where(col(MediaItem.id).notin_(exclude_item_ids))
        return (await self.session.exec(stmt.limit(1))).first()

    async def find_by_external_guids(
        self,
        guids: dict[str, str],
        media_type: str,
        *,
        server_id: int | None = None,
        folder_path: str | None = None,
        exclude_item_ids: set[int] | None = None,
        for_update: bool = True,
    ) -> MediaItem | None:
        """Return a media item by external GUIDs, preferring TMDB then TVDB.

        A server's item never matches a title another server holds in another
        folder: those are other files of the same title, each with its own
        artwork. A title without a copy on *server_id* comes first, so each
        server's copies spread over the titles before doubling up.

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
        stmt = _matching(for_update).where(
            col(MediaItem.media_type) == media_type,
            or_(*(clause for _rank, clause in matches)),
        )
        if exclude_item_ids:
            stmt = stmt.where(col(MediaItem.id).notin_(exclude_item_ids))

        order_clauses: list[ColumnElement[Any]] = []
        if folder_path is not None and server_id is not None:
            elsewhere = exists().where(
                col(MediaItemCopy.media_item_id) == col(MediaItem.id),
                col(MediaItemCopy.server_id) != server_id,
            )
            stmt = stmt.where(
                ~and_(
                    col(MediaItem.folder_path).is_not(None),
                    col(MediaItem.folder_path).notin_(_folder_variants(folder_path)),
                    elsewhere,
                )
            )
        if server_id is not None:
            order_clauses.append(on_server(server_id).asc())
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

    async def find_by_folder_path(
        self,
        folder_path: str,
        media_type: str,
        *,
        exclude_item_ids: set[int] | None = None,
        for_update: bool = True,
    ) -> MediaItem | None:
        """Return a media item by filesystem folder path and type."""
        stmt = _matching(for_update).where(
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
            _matching(for_update=False)
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
        stmt = _bulk_scope(
            select(MediaItem),
            library_ids,
            item_ids=item_ids,
            include_unmonitored=include_unmonitored,
            after_id=after_id,
        )
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.exec(stmt)
        return sorted(
            result.all(),
            key=lambda item: media_sort_key(item.media_type, item.title, item.id),
        )

    async def bulk_target_ids_keeping_files(
        self,
        library_ids: list[str] | None,
        *,
        art: bool,
        item_ids: list[int] | None,
        include_unmonitored: bool,
        after_id: int,
        limit: int,
    ) -> list[int]:
        """Return the IDs of bulk targets whose saved selection has a recorded file.

        *art* asks about artwork, of the item or its seasons; otherwise about
        the theme.
        """
        kept = (
            col(Asset.kind).in_(
                [kind for kind in ServerAsset if (kind is ServerAsset.THEME) is not art]
            ),
            or_(
                col(Asset.url).is_not(None),
                col(Asset.upload_hash).is_not(None),
                col(Asset.youtube_id).is_not(None),
            ),
            select(AssetDelivery.id)
            .where(
                col(AssetDelivery.asset_id) == Asset.id,
                col(AssetDelivery.server_id).is_(None),
                col(AssetDelivery.observed_hash).is_not(None),
            )
            .exists(),
        )
        keeps = or_(
            select(Asset.id)
            .where(col(Asset.media_item_id) == MediaItem.id, *kept)
            .exists(),
            select(Asset.id)
            .join(Season, col(Season.id) == col(Asset.season_id))
            .where(col(Season.media_item_id) == MediaItem.id, *kept)
            .exists(),
        )
        stmt = _bulk_scope(
            select(MediaItem.id),
            library_ids,
            item_ids=item_ids,
            include_unmonitored=include_unmonitored,
            after_id=after_id,
        ).where(keeps)
        return [
            item_id for item_id in await self.session.exec(stmt.limit(limit)) if item_id
        ]

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
            stmt = stmt.where(in_libraries([library_id]))
        if library_ids is not None:
            stmt = stmt.where(in_libraries(library_ids))
        stmt = stmt.where(col(MediaItem.id) > after_id).order_by(col(MediaItem.id))
        if limit is not None:
            stmt = stmt.limit(limit)
        result = await self.session.exec(stmt)
        return list(result.all())

    async def visible_ids_by_identity(
        self,
        media_type: MediaType,
        identities: list[tuple[str, int | str]] | None = None,
    ) -> dict[tuple[str, int | str], int]:
        """Return visible item IDs keyed by each ``(field, value)`` they carry."""
        columns = [col(getattr(MediaItem, field)) for field in IDENTITY_FIELDS]
        stmt = cast("Select[Any]", select(col(MediaItem.id), *columns)).where(
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
        for item_id, *values in await self.session.exec(stmt):
            for field, value in zip(IDENTITY_FIELDS, values, strict=True):
                if value is not None:
                    found.setdefault((field, value), item_id)
        return found

    async def titles_needing_tmdb_facts(
        self,
        checked_before: datetime,
        *,
        library_ids: list[str] | None = None,
        item_ids: list[int] | None = None,
    ) -> list[tuple[int, MediaType, int]]:
        """``(id, media_type, tmdb_id)`` of visible titles never or long ago read."""
        stmt = select(MediaItem.id, MediaItem.media_type, MediaItem.tmdb_id).where(
            col(MediaItem.server_removed_at).is_(None),
            col(MediaItem.tmdb_id).is_not(None),
            or_(
                col(MediaItem.tmdb_checked_id).is_(None),
                col(MediaItem.tmdb_checked_id) != col(MediaItem.tmdb_id),
                col(MediaItem.tmdb_checked_at) < checked_before,
            ),
        )
        if library_ids:
            stmt = stmt.where(in_libraries(library_ids))
        if item_ids is not None:
            stmt = stmt.where(col(MediaItem.id).in_(item_ids))
        return [
            (item_id, MediaType(media_type), tmdb_id)
            for item_id, media_type, tmdb_id in await self.session.exec(stmt)
            if item_id is not None and tmdb_id is not None
        ]

    async def list_unconnected_tmdb_shows(self) -> list[MediaItem]:
        """Return saved TMDB shows whose seasons are not supplied by a server."""
        result = await self.session.exec(
            select(MediaItem)
            .where(
                col(MediaItem.media_type) == MediaType.SHOW,
                col(MediaItem.tmdb_id).is_not(None),
                ~exists().where(col(MediaItemCopy.media_item_id) == col(MediaItem.id)),
                col(MediaItem.server_removed_at).is_(None),
            )
            .order_by(col(MediaItem.id))
        )
        return list(result.all())

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
        """Stamp many items as synced at once; each copy notes its own verification."""
        if not item_ids:
            return
        await self.session.exec(
            update(MediaItem)
            .where(col(MediaItem.id).in_(item_ids))
            .values(last_synced_at=when)
        )

    async def bulk_operate(
        self, item_ids: Collection[int], operation: ItemRecordOperation
    ) -> list[int]:
        """Delete items or set their monitoring, bounded to SQLite's parameter limit.

        Assets change only through the ledger, so their removal is not here.
        """
        affected: list[int] = []
        for batch in batched(dict.fromkeys(item_ids), CHUNK_SIZE, strict=False):
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
            if operation == "delete":
                await self.session.exec(delete(MediaItem).where(target))
            else:
                await self.session.exec(
                    update(MediaItem)
                    .where(target)
                    .values(monitored=operation == "monitor")
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


def _bulk_scope[S: SelectOfScalar[Any]](
    stmt: S,
    library_ids: list[str] | None,
    *,
    item_ids: list[int] | None,
    include_unmonitored: bool,
    after_id: int,
) -> S:
    """Narrow *stmt* to the present items a bulk run targets, by ID from *after_id*."""
    stmt = stmt.where(
        col(MediaItem.server_removed_at).is_(None),
        col(MediaItem.folder_path).is_not(None),
    )
    if item_ids is not None:
        stmt = stmt.where(col(MediaItem.id).in_(item_ids))
    if not include_unmonitored:
        stmt = stmt.where(col(MediaItem.monitored).is_(True))
    if library_ids:
        stmt = stmt.where(in_libraries(library_ids))
    return stmt.where(col(MediaItem.id) > after_id).order_by(col(MediaItem.id))
