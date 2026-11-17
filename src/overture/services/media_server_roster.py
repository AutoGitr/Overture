"""Which media servers Overture talks to, as MEDIA_SERVERS names them."""

lazy import logging

lazy from sqlmodel import col, select, update
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..config import MediaServerConfig
lazy from ..db.models.job_result import JobRun
lazy from ..db.models.library import Library
lazy from ..db.models.media_server import MediaServer
lazy from ..db.session import Database
lazy from ..jobs.kinds import JobKind
lazy from ..media_servers.registry import ProviderRegistry
lazy from ..repositories.collections import CollectionRepository
lazy from ..repositories.copies import CopyRepository
lazy from ..utils.time import utc_now

logger = logging.getLogger(__name__)

#: Runs whose findings name servers' items and collections.
_SERVER_RUNS = (JobKind.SERVER_AUDIT, JobKind.SERVER_AUDIT_FIX)


def _claim(
    server: MediaServerConfig, rows: list[MediaServer], *, lead: bool
) -> tuple[MediaServer | None, MediaServer | None]:
    """Return the row *server* is, and the row whose name it takes over, if any.

    A server is the row of its name while the address there is its own. A row
    let go of, at its address, is a renamed server or one coming back; the row
    an upgrade found, of no known kind, goes to the server at its address, or
    to the lead when it recorded none.
    """
    named = next((row for row in rows if row.key == server.key), None)
    if named is not None and named.identity == server.identity:
        return named, None
    returning = next(
        (
            row
            for row in rows
            if row is not named
            and row.removed_at is not None
            and row.identity == server.identity
        ),
        None,
    )
    if returning is None and lead:
        returning = next(
            (row for row in rows if row.server_type is None and not row.identity),
            None,
        )
    return returning, named


class MediaServerRoster:
    """Record the configured media servers when Overture starts.

    Each configured server keeps its row, and so its libraries, copies and
    collections, across renames and reorders. A server that leaves
    MEDIA_SERVERS is let go of: its libraries and the titles only it held are
    hidden, and the collections it held that Overture does not manage are
    forgotten. What Overture manages keeps its parts on that server, to take
    up again if the server returns, or to move to the libraries its titles turn
    up in on another server.
    """

    def __init__(
        self, *, database: Database, provider_registry: ProviderRegistry
    ) -> None:
        self._database = database
        self._registry = provider_registry

    async def reconcile(self) -> None:
        """Match the configured servers to their rows and attach the registry."""
        async with self._database.write_session() as session:
            rows = list((await session.exec(select(MediaServer))).all())
            kept: list[MediaServer] = []
            for index, server in enumerate(self._registry.servers):
                row, displaced = _claim(server, rows, lead=index == 0)
                if displaced is not None:
                    # Another server at another address took this name.
                    displaced.key = None
                    session.add(displaced)
                    await session.flush()
                if row is None:
                    row = MediaServer(identity=server.identity, title=server.title)
                    rows.append(row)
                    logger.info("Media server %s added", server.title)
                elif row.removed_at is not None or row.key != server.key:
                    logger.info("Media server %s taken up again", server.title)
                row.key = server.key
                row.title = server.title
                row.server_type = server.type
                row.identity = server.identity
                row.removed_at = None
                session.add(row)
                kept.append(row)
            await session.flush()
            left = [row for row in rows if row not in kept and row.removed_at is None]
            await self._let_go(session, left)
            await self._restore(session, [row.id or 0 for row in kept])
        self._registry.attach({row.key or "": row.id or 0 for row in kept})

    async def _let_go(self, session: AsyncSession, left: list[MediaServer]) -> None:
        """Hide what servers that left MEDIA_SERVERS held."""
        if not left:
            return
        now = utc_now()
        ids = [row.id or 0 for row in left]
        for row in left:
            row.removed_at = now
            session.add(row)
            logger.info(
                "Media server %s is no longer in MEDIA_SERVERS; what it held is "
                "hidden until it returns",
                row.title,
            )
        await session.exec(
            update(Library)
            .where(col(Library.server_id).in_(ids), col(Library.removed_at).is_(None))
            .values(removed_at=now)
        )
        await CollectionRepository(session).forget_unmanaged_on(ids)
        await session.exec(
            update(JobRun)
            .where(col(JobRun.kind).in_(_SERVER_RUNS))
            .values(cleared=True)
        )

    async def _restore(self, session: AsyncSession, server_ids: list[int]) -> None:
        """Show again every title a configured server lists, hide the rest."""
        await CopyRepository(session).refresh_presence(server_ids, utc_now())
