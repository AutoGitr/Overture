"""Disk-backed complete provider listing for bounded reconciliation."""

lazy import sqlite3
lazy from datetime import datetime
lazy from pathlib import Path
lazy from typing import Self

lazy from pydantic import TypeAdapter

lazy from ...db.session import PAGE_SIZE
lazy from ...domain import MediaType
lazy from ...media_servers.adapters import MAX_SEASONS_PER_SHOW, ServerItem
lazy from ...media_servers.errors import MediaServerError
lazy from ...utils.threads import owned_thread

_ITEM = TypeAdapter(ServerItem)
_ITEM.rebuild(_types_namespace={"datetime": datetime, "MediaType": MediaType})


class StagedListing:
    """Store validated provider rows until enumeration has fully succeeded.

    The file lives only as long as one sync, so it is written through one
    connection that holds its lock until closed, with its journal in memory
    and without syncs: a crash discards the run anyway, but a rejected batch
    still rolls back. Opening it, or locking it, again per row cost more than
    reconciling the row.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._connection: sqlite3.Connection | None = None

    async def __aenter__(self) -> Self:
        await self.create()
        return self

    async def __aexit__(self, *_exc: object) -> None:
        await self.close()

    @property
    def connection(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("Staged listing is not open")
        return self._connection

    async def create(self) -> None:
        await owned_thread(self._create)

    def _create(self) -> None:
        # Calls run one at a time on worker threads, never concurrently.
        connection = sqlite3.connect(
            self.path, isolation_level=None, check_same_thread=False
        )
        connection.execute("PRAGMA locking_mode=EXCLUSIVE")
        connection.execute("PRAGMA journal_mode=MEMORY")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute(
            "CREATE TABLE items ("
            "media_type TEXT NOT NULL, server_id TEXT NOT NULL, "
            "payload BLOB NOT NULL, mapped_id INTEGER, "
            "PRIMARY KEY (media_type, server_id))"
        )
        connection.execute(
            "CREATE UNIQUE INDEX mapped_item ON items (mapped_id) "
            "WHERE mapped_id IS NOT NULL"
        )
        self._connection = connection

    async def close(self) -> None:
        if self._connection is not None:
            await owned_thread(self._connection.close)
            self._connection = None

    async def append(self, batch: list[ServerItem]) -> None:
        if not batch:
            return
        if any(not item.id or not item.media_type for item in batch):
            raise MediaServerError("Media server returned missing item IDs")
        if any(len(item.seasons) > MAX_SEASONS_PER_SHOW for item in batch):
            raise MediaServerError("Media server returned too many seasons")
        try:
            await owned_thread(self._append, batch)
        except sqlite3.IntegrityError as exc:
            raise MediaServerError("Media server returned duplicate item IDs") from exc

    def _append(self, batch: list[ServerItem]) -> None:
        connection = self.connection
        connection.execute("BEGIN")
        try:
            connection.executemany(
                "INSERT INTO items (media_type, server_id, payload) VALUES (?, ?, ?)",
                [(item.media_type, item.id, _ITEM.dump_json(item)) for item in batch],
            )
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")

    async def count(self) -> int:
        return await owned_thread(self._count)

    def _count(self) -> int:
        row = self.connection.execute("SELECT count(*) FROM items").fetchone()
        return int(row[0]) if row else 0

    async def batch(self, after_rowid: int) -> list[tuple[int, ServerItem]]:
        return await owned_thread(self._batch, after_rowid)

    def _batch(self, after_rowid: int) -> list[tuple[int, ServerItem]]:
        rows = self.connection.execute(
            "SELECT rowid, payload FROM items WHERE rowid > ? ORDER BY rowid LIMIT ?",
            (after_rowid, PAGE_SIZE),
        ).fetchall()
        return [(int(rowid), _ITEM.validate_json(payload)) for rowid, payload in rows]

    async def mappings(
        self, keys: list[tuple[str, str]]
    ) -> dict[tuple[str, str], int | None]:
        """Return the listed keys among *keys*, each with the row it mapped to."""
        return await owned_thread(self._mappings, keys)

    def _mappings(
        self, keys: list[tuple[str, str]]
    ) -> dict[tuple[str, str], int | None]:
        connection = self.connection
        connection.execute(
            "CREATE TEMP TABLE IF NOT EXISTS wanted (media_type TEXT, server_id TEXT)"
        )
        connection.execute("DELETE FROM wanted")
        connection.executemany("INSERT INTO wanted VALUES (?, ?)", keys)
        rows = connection.execute(
            "SELECT media_type, server_id, mapped_id "
            "FROM items JOIN wanted USING (media_type, server_id)"
        ).fetchall()
        return {
            (media_type, server_id): mapped for media_type, server_id, mapped in rows
        }

    async def mark_mapped(self, media_type: str, server_id: str, item_id: int) -> None:
        await owned_thread(self._mark_mapped, media_type, server_id, item_id)

    async def is_mapped(self, item_id: int) -> bool:
        return await owned_thread(self._is_mapped, item_id)

    def _is_mapped(self, item_id: int) -> bool:
        return (
            self.connection.execute(
                "SELECT 1 FROM items WHERE mapped_id = ?", (item_id,)
            ).fetchone()
            is not None
        )

    def _mark_mapped(self, media_type: str, server_id: str, item_id: int) -> None:
        self.connection.execute(
            "UPDATE items SET mapped_id = ? WHERE media_type = ? AND server_id = ?",
            (item_id, media_type, server_id),
        )
