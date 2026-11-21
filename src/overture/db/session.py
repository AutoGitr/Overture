"""Database engine, session factory, and table creation."""

lazy import asyncio
lazy import logging
lazy from collections.abc import AsyncGenerator, Awaitable, Callable
lazy from contextlib import asynccontextmanager
lazy from pathlib import Path

lazy from alembic import command
lazy from alembic.config import Config
lazy from alembic.runtime.migration import MigrationContext
lazy from alembic.script import ScriptDirectory
lazy from sqlalchemy import event
lazy from sqlalchemy.engine import Connection
lazy from sqlalchemy.engine.interfaces import DBAPIConnection
lazy from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
lazy from sqlalchemy.orm import Session as OrmSession
lazy from sqlalchemy.pool import AsyncAdaptedQueuePool
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from .ledger import verify_flush
lazy from .models.settings import SETTINGS_ROW_ID, AppSettings

logger = logging.getLogger(__name__)

_MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"

#: How long a statement waits for another connection's write lock before it
#: gives up. A backstop, not a tuning knob: every write transaction in the app
#: is a handful of rows, so a writer that waits even this long has found a bug
#: rather than a queue.
_BUSY_TIMEOUT_MS = 5_000

#: Connections the app keeps open. An assets run alone decides several
#: targets at a time in each of its lanes while the download workers, the
#: run's log and the browser's requests read too; every one of them holds a
#: connection only between awaits, and WAL readers never block each other,
#: so a connection each costs a page cache rather than any waiting.
_POOL_SIZE = 16

#: How long a session waits for a free connection. Waiting is queueing behind
#: other short sessions, which takes longer while blocking work competes for
#: the interpreter, not a fault to fail the work on.
_POOL_TIMEOUT_SECONDS = 60

PAGE_SIZE = 100
"""Rows per write transaction, and per page whose rows are worked on in turn.

Keeps every write transaction short, so writers waiting for the lock are not
held up.
"""

CHUNK_SIZE = 500
"""Rows per read-only chunk, and IDs per single statement.

A reader never blocks a writer in WAL mode, and one statement holds the write
lock only briefly, so these batches are sized for fewer round trips instead.
"""


def _on_connect(dbapi_conn: DBAPIConnection, _connection_record: object) -> None:
    """Take transaction control from the driver, and apply the pragmas.

    pysqlite decides transaction boundaries itself, and only ever puts one
    around DML. Two things follow, and both are bugs. A block that reads and
    then writes is two transactions, so what it read can change before it
    writes - which for ``sync_item`` means finding no local match and
    inserting a second copy of a row another writer just added. And if a
    transaction does open before the reads, they take a snapshot SQLite
    refuses to upgrade the moment another connection has committed: "database
    is locked", raised immediately and never retried, however long the busy
    timeout.

    Setting ``isolation_level`` to None stops the driver guessing, and
    :func:`_begin` states each transaction's intent instead - a writer takes
    the lock as it opens, before it has read anything.

    ``synchronous=NORMAL`` is what WAL is designed for: commits stop waiting on
    an fsync each, and the disk is synced at checkpoints. A commit is still
    durable across a crash of this process, and the database is never left
    corrupt; only a power loss or OS crash can lose the most recent
    transactions. Nearly all of those are rows a sync or refresh writes in
    bulk and the next run derives again, and they are exactly the writes an
    fsync per commit would slow down most, so one item can stay one
    transaction.
    """
    dbapi_conn.isolation_level = None
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.execute(f"PRAGMA busy_timeout={_BUSY_TIMEOUT_MS}")
    cursor.close()
    # Criteria compare values case-insensitively by Unicode, which the database
    # cannot do itself; deterministic so a query may fold each value only once.
    dbapi_conn.create_function("casefold", 1, str.casefold, deterministic=True)


def _begin(conn: Connection) -> None:
    """Open a writer's transaction with the write lock already held.

    Readers are left in the driver's statement-at-a-time autocommit: holding
    no snapshot, a reader is never the connection that fails to upgrade, and
    in WAL mode it neither blocks a writer nor waits for one.
    """
    if conn.get_execution_options().get("sqlite_write"):
        conn.exec_driver_sql("BEGIN IMMEDIATE")


# Every session, whoever opens it, refuses to store an asset status that
# disagrees with the asset's rows.
event.listen(OrmSession, "before_flush", verify_flush)


def configure_sqlite(engine: AsyncEngine) -> AsyncEngine:
    """Bind Overture's connection and transaction handling to an engine."""
    event.listen(engine.sync_engine, "connect", _on_connect)
    event.listen(engine.sync_engine, "begin", _begin)
    return engine


def as_writer(engine: AsyncEngine) -> AsyncEngine:
    """Return the same engine and pool, opening every transaction as a writer.

    The intent rides on the engine rather than on one session, so a block that
    commits part-way through and keeps writing opens its next transaction the
    same way.
    """
    return engine.execution_options(sqlite_write=True)


def alembic_config() -> Config:
    """Return the Alembic configuration for the bundled migrations."""
    config = Config()
    config.set_main_option("script_location", str(_MIGRATIONS_DIR))
    return config


def run_migrations(connection: Connection) -> tuple[str | None, str | None]:
    """Bring the schema to the current head; return the revisions before and after."""
    config = alembic_config()
    config.attributes["connection"] = connection
    before = MigrationContext.configure(connection).get_current_revision()
    command.upgrade(config, "head")
    return before, MigrationContext.configure(connection).get_current_revision()


def pending_upgrade(connection: Connection) -> str | None:
    """Return the revision of an existing schema behind the bundled migrations.

    ``None`` when there is no schema yet or it is current.
    """
    current = MigrationContext.configure(connection).get_current_revision()
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    return current if current is not None and current != head else None


class Database:
    """Own one connection pool, its session factories, and its writer queue."""

    def __init__(self, url: str, *, engine: AsyncEngine | None = None) -> None:
        self._engine = (
            engine
            if engine is not None
            else configure_sqlite(
                create_async_engine(
                    url,
                    echo=False,
                    poolclass=AsyncAdaptedQueuePool,
                    pool_size=_POOL_SIZE,
                    max_overflow=0,
                    pool_timeout=_POOL_TIMEOUT_SECONDS,
                    connect_args={"check_same_thread": False},
                )
            )
        )
        self._write_engine = as_writer(self._engine)
        self.write_lock = asyncio.Lock()

    @property
    def engine(self) -> AsyncEngine:
        """Expose the pool for readiness probes and explicit ownership."""
        return self._engine

    async def initialize(
        self, before_upgrade: Callable[[str], Awaitable[None]] | None = None
    ) -> None:
        """Migrate atomically before any service uses the database.

        *before_upgrade* runs first, with the schema's revision, when an
        existing schema is about to change.
        """
        async with self.write_lock, self._engine.connect() as conn:
            if before_upgrade is not None and (
                revision := await conn.run_sync(pending_upgrade)
            ):
                await conn.rollback()
                await before_upgrade(revision)
            # Batch migrations replace parent tables. Foreign-key cascades
            # would delete their children when Alembic drops the old table.
            # SQLite requires changing this pragma outside a transaction.
            await conn.exec_driver_sql("PRAGMA foreign_keys=OFF")
            await conn.commit()
            try:
                await conn.execution_options(sqlite_write=True)
                async with conn.begin():
                    before, after = await conn.run_sync(run_migrations)
                    violations = await conn.exec_driver_sql("PRAGMA foreign_key_check")
                    if violations.first() is not None:
                        msg = "Database migration left invalid foreign-key references"
                        raise RuntimeError(msg)
            finally:
                await conn.execution_options(sqlite_write=False)
                await conn.exec_driver_sql("PRAGMA foreign_keys=ON")
                await conn.commit()
        async with self.write_session() as session:
            if not await session.get(AppSettings, SETTINGS_ROW_ID):
                session.add(AppSettings(id=SETTINGS_ROW_ID))
        if before == after:
            logger.info("Database ready (schema %s)", after)
        else:
            logger.info(
                "Database migrated from %s to %s",
                before or "an empty database",
                after,
            )

    async def close(self) -> None:
        """Dispose the owned connection pool."""
        await self._engine.dispose()

    @asynccontextmanager
    async def read_session(self) -> AsyncGenerator[AsyncSession]:
        """Read without committing or expiring detached results."""
        async with AsyncSession(self._engine, expire_on_commit=False) as session:
            yield session

    @asynccontextmanager
    async def write_session(self) -> AsyncGenerator[AsyncSession]:
        """Serialize writers and commit on success, rolling back on failure."""
        async with (
            self.write_lock,
            AsyncSession(self._write_engine, expire_on_commit=False) as session,
        ):
            try:
                yield session
            except BaseException:
                if session.in_transaction():
                    try:
                        await session.rollback()
                    except Exception:
                        logger.exception(
                            "Rollback failed while handling transaction failure"
                        )
                session.info.clear()
                raise
            else:
                await session.commit()
