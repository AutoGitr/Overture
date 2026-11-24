"""Media servers' copies of titles and seasons."""

lazy from collections.abc import Collection, Iterable, Sequence
lazy from datetime import datetime
lazy from itertools import batched
lazy from typing import Any, NamedTuple, cast

lazy from sqlalchemy.sql.elements import ColumnElement
lazy from sqlmodel import col, exists, select, update
lazy from sqlmodel.ext.asyncio.session import AsyncSession
lazy from sqlmodel.sql.expression import Select

lazy from ..db.models.library import Library
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.media_item_copy import MediaItemCopy, SeasonCopy
lazy from ..db.models.media_server import MediaServer
lazy from ..db.models.season import Season
lazy from ..db.session import CHUNK_SIZE
lazy from ..domain import MediaType, TermKind
lazy from .terms import TermRepository


class ServerItemFacts(NamedTuple):
    """What a collection needs to know about one of its member items."""

    id: int
    media_type: MediaType
    library_id: str
    tmdb_collection_id: int | None


def _live() -> ColumnElement[bool]:
    return col(MediaItemCopy.removed_at).is_(None)


def in_libraries(library_ids: Collection[str]) -> ColumnElement[bool]:
    """Whether a title has a copy its server lists in one of *library_ids*."""
    return col(MediaItem.id).in_(
        select(MediaItemCopy.media_item_id).where(
            col(MediaItemCopy.library_id).in_(library_ids), _live()
        )
    )


def on_server(server_id: int) -> ColumnElement[bool]:
    """Whether a title has a copy on a server, listed now or not."""
    return exists().where(
        col(MediaItemCopy.media_item_id) == col(MediaItem.id),
        col(MediaItemCopy.server_id) == server_id,
    )


class CopyRepository:
    """Read and record the copies media servers hold of titles and seasons."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def of_items(
        self, item_ids: Collection[int]
    ) -> dict[int, list[MediaItemCopy]]:
        """Return each title's copies, by title, in no particular order."""
        found: dict[int, list[MediaItemCopy]] = {item_id: [] for item_id in item_ids}
        for batch in batched(item_ids, CHUNK_SIZE, strict=False):
            rows = await self.session.exec(
                select(MediaItemCopy).where(col(MediaItemCopy.media_item_id).in_(batch))
            )
            for copy in rows.all():
                found[copy.media_item_id].append(copy)
        return found

    async def listed_copies(
        self, item_ids: Collection[int]
    ) -> dict[int, list[MediaItemCopy]]:
        """Return the copies configured servers list of each title, in listed
        libraries, the lead first.

        The lead copy, on the earliest server in MEDIA_SERVERS, stands for the
        title: its details are the title's.
        """
        return await self._configured(
            item_ids,
            col(MediaItemCopy.library_id).in_(
                select(Library.id).where(col(Library.removed_at).is_(None))
            ),
        )

    async def _configured(
        self, item_ids: Collection[int], *where: ColumnElement[bool]
    ) -> dict[int, list[MediaItemCopy]]:
        """Each title's live copies on configured servers, in MEDIA_SERVERS order."""
        found: dict[int, list[MediaItemCopy]] = {}
        for batch in batched(item_ids, CHUNK_SIZE, strict=False):
            rows = await self.session.exec(
                select(MediaItemCopy)
                .join(MediaServer, col(MediaServer.id) == col(MediaItemCopy.server_id))
                .where(
                    col(MediaItemCopy.media_item_id).in_(batch),
                    _live(),
                    col(MediaServer.position).is_not(None),
                    *where,
                )
                .order_by(col(MediaServer.position))
            )
            for copy in rows.all():
                found.setdefault(copy.media_item_id, []).append(copy)
        return found

    async def of_item(self, item_id: int) -> list[MediaItemCopy]:
        """Return a title's copies."""
        return (await self.of_items([item_id]))[item_id]

    async def find(
        self, server_id: int, media_type: MediaType, server_item_id: str
    ) -> MediaItemCopy | None:
        """Return the copy a server keeps under *server_item_id*."""
        return (
            await self.session.exec(
                select(MediaItemCopy).where(
                    col(MediaItemCopy.server_id) == server_id,
                    col(MediaItemCopy.media_type) == media_type,
                    col(MediaItemCopy.server_item_id) == server_item_id,
                )
            )
        ).first()

    async def identities(
        self,
        server_id: int,
        library_ids: Collection[str] | None,
        *,
        after_id: int,
        limit: int,
    ) -> list[tuple[int, int, MediaType, str]]:
        """A page of a server's listed copies: ``(copy, title, type, server ID)``."""
        stmt = (
            select(
                col(MediaItemCopy.id),
                col(MediaItemCopy.media_item_id),
                col(MediaItemCopy.media_type),
                col(MediaItemCopy.server_item_id),
            )
            .where(
                col(MediaItemCopy.server_id) == server_id,
                _live(),
                col(MediaItemCopy.id) > after_id,
            )
            .order_by(col(MediaItemCopy.id))
            .limit(limit)
        )
        if library_ids:
            stmt = stmt.where(col(MediaItemCopy.library_id).in_(library_ids))
        return [
            (copy_id, item_id, media_type, server_item_id)
            for copy_id, item_id, media_type, server_item_id in await self.session.exec(
                stmt
            )
            if copy_id is not None
        ]

    async def facts_by_server_id(self, server_id: int) -> dict[str, ServerItemFacts]:
        """What collections need of the visible titles a server lists, by its IDs."""
        columns: list[Any] = [
            MediaItemCopy.server_item_id,
            MediaItemCopy.media_item_id,
            MediaItemCopy.media_type,
            MediaItemCopy.library_id,
            MediaItem.tmdb_collection_id,
        ]
        rows = await self.session.exec(
            cast("Select[Any]", select(*columns))
            .join(MediaItem, col(MediaItem.id) == col(MediaItemCopy.media_item_id))
            .where(
                col(MediaItemCopy.server_id) == server_id,
                _live(),
                col(MediaItem.server_removed_at).is_(None),
            )
        )
        return {
            server_item_id: ServerItemFacts(item_id, media_type, library_id, franchise)
            for server_item_id, item_id, media_type, library_id, franchise in cast(
                "Iterable[Any]", rows
            )
        }

    async def directors_by_version(
        self, server_id: int, server_item_ids: Collection[str]
    ) -> dict[tuple[str, str], tuple[str, ...]]:
        """Return stored movie directors keyed by a server's ID and director Etag."""
        versions: dict[int, tuple[str, str]] = {}
        for batch in batched(server_item_ids, CHUNK_SIZE, strict=False):
            rows = await self.session.exec(
                select(
                    MediaItemCopy.media_item_id,
                    MediaItemCopy.server_item_id,
                    MediaItemCopy.director_etag,
                ).where(
                    col(MediaItemCopy.server_id) == server_id,
                    col(MediaItemCopy.media_type) == MediaType.MOVIE,
                    col(MediaItemCopy.server_item_id).in_(batch),
                    col(MediaItemCopy.director_etag).is_not(None),
                )
            )
            for item_id, server_item_id, etag in rows.all():
                if etag:
                    versions[item_id] = (server_item_id, etag)
        directors = await TermRepository(self.session).values_by_item(
            versions, TermKind.DIRECTOR
        )
        return {
            version: tuple(directors.get(item_id, ()))
            for item_id, version in versions.items()
        }

    async def leads_first(self, item_id: int) -> list[MediaItemCopy]:
        """A title's listed copies on the configured servers, the lead first."""
        return (await self._configured([item_id])).get(item_id, [])

    async def season_copies(self, season_id: int) -> dict[int, str]:
        """Each server's ID of a season, by server."""
        rows = await self.session.exec(
            select(SeasonCopy.server_id, SeasonCopy.server_item_id).where(
                col(SeasonCopy.season_id) == season_id
            )
        )
        return dict(rows.all())

    async def season_copies_on(
        self, season_ids: Collection[int], server_id: int
    ) -> dict[int, SeasonCopy]:
        """One server's copies of the seasons, by season."""
        rows = await self.session.exec(
            select(SeasonCopy).where(
                col(SeasonCopy.season_id).in_(season_ids),
                col(SeasonCopy.server_id) == server_id,
            )
        )
        return {copy.season_id: copy for copy in rows.all()}

    async def keep_season_id(
        self, season_id: int, server_id: int, server_item_id: str
    ) -> str | None:
        """Record a server's ID of a season found by asking it; one recorded wins.

        Returns the ID kept, or ``None`` when the season went meanwhile.
        """
        current = await self.session.get(SeasonCopy, (season_id, server_id))
        if current is not None:
            return current.server_item_id
        if await self.session.get(Season, season_id) is None:
            return None
        self.session.add(
            SeasonCopy(
                season_id=season_id, server_id=server_id, server_item_id=server_item_id
            )
        )
        return server_item_id

    async def set_season_copy(
        self,
        season_id: int,
        server_id: int,
        server_item_id: str | None,
        poster_version: str | None,
    ) -> None:
        """Record a server's ID of a season and the poster it shows, or forget
        its copy when the ID is ``None``."""
        current = await self.session.get(SeasonCopy, (season_id, server_id))
        if server_item_id is None:
            if current is not None:
                await self.session.delete(current)
            return
        if current is None:
            current = SeasonCopy(
                season_id=season_id, server_id=server_id, server_item_id=server_item_id
            )
        current.server_item_id = server_item_id
        current.poster_version = poster_version
        self.session.add(current)

    async def relabel(
        self,
        library_id: str,
        item_ids: Collection[int],
        label: str,
        wanted: Collection[int],
    ) -> None:
        """Put *label* on the copies in a library of *wanted* titles, off the rest."""
        folded = label.casefold()
        rows = await self.session.exec(
            select(MediaItemCopy).where(
                col(MediaItemCopy.library_id) == library_id,
                col(MediaItemCopy.media_item_id).in_(item_ids),
            )
        )
        for copy in rows.all():
            labels = [held for held in copy.labels if held.casefold() != folded]
            copy.labels = [*labels, label] if copy.media_item_id in wanted else labels
            self.session.add(copy)

    async def refresh_presence(self, server_ids: Sequence[int], now: datetime) -> None:
        """Hide titles no configured server lists; show those one lists again.

        A title chosen from TMDB alone has no copies and is left as it is.
        """
        listed = exists().where(
            col(MediaItemCopy.media_item_id) == col(MediaItem.id),
            col(MediaItemCopy.server_id).in_(server_ids),
            _live(),
            col(MediaItemCopy.library_id).in_(
                select(Library.id).where(col(Library.removed_at).is_(None))
            ),
        )
        held = exists().where(col(MediaItemCopy.media_item_id) == col(MediaItem.id))
        await self.session.exec(
            update(MediaItem)
            .where(col(MediaItem.server_removed_at).is_(None), held, ~listed)
            .values(server_removed_at=now)
        )
        await self.session.exec(
            update(MediaItem)
            .where(col(MediaItem.server_removed_at).is_not(None), listed)
            .values(server_removed_at=None)
        )

    async def mark_removed(self, copy_ids: Collection[int], now: datetime) -> list[int]:
        """Mark copies their server stopped listing; return titles left with none."""
        if not copy_ids:
            return []
        await self.session.exec(
            update(MediaItemCopy)
            .where(col(MediaItemCopy.id).in_(copy_ids), _live())
            .values(removed_at=now)
        )
        affected = select(MediaItemCopy.media_item_id).where(
            col(MediaItemCopy.id).in_(copy_ids)
        )
        other = exists().where(
            col(MediaItemCopy.media_item_id) == col(MediaItem.id), _live()
        )
        gone = list(
            (
                await self.session.exec(
                    select(MediaItem.id).where(
                        col(MediaItem.id).in_(affected),
                        col(MediaItem.server_removed_at).is_(None),
                        ~other,
                    )
                )
            ).all()
        )
        if gone:
            await self.session.exec(
                update(MediaItem)
                .where(col(MediaItem.id).in_(gone))
                .values(server_removed_at=now, last_synced_at=now)
            )
        return [item_id for item_id in gone if item_id is not None]

    async def leads(self, item_ids: Collection[int]) -> dict[int, MediaItemCopy]:
        """Return each title's lead copy: listed, on the earliest configured server."""
        return {
            item_id: copies[0]
            for item_id, copies in (await self._configured(item_ids)).items()
        }
