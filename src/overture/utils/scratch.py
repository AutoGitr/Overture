"""SQLite files an operation keeps its working rows in while it runs.

A scratch database lives in the operation's own directory and is discarded
with it, never read after a crash, so it keeps its journal in memory and never
waits for the disk. Transactions still roll back a rejected batch. It is not
the application database: ``sqlite3`` writes it from the worker thread that
owns the operation, without the engine, pool and writer queue that database
needs, and with rows the operation streams in and out rather than models.
"""

lazy import sqlite3
lazy from collections.abc import Generator
lazy from contextlib import closing, contextmanager
lazy from pathlib import Path


def configure_scratch(connection: sqlite3.Connection) -> sqlite3.Connection:
    """Set *connection* up as a scratch database's, and return it."""
    connection.execute("PRAGMA journal_mode=MEMORY")
    connection.execute("PRAGMA synchronous=OFF")
    connection.execute("PRAGMA temp_store=MEMORY")
    return connection


@contextmanager
def scratch_database(path: Path) -> Generator[sqlite3.Connection]:
    """Open the scratch database at *path* for one step of an operation."""
    with closing(configure_scratch(sqlite3.connect(path))) as connection:
        yield connection
