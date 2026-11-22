"""Read a row and every row that refers to it, from the table metadata alone."""

lazy from collections.abc import Sequence

lazy from pydantic_core import to_jsonable_python
lazy from sqlalchemy import ColumnElement
lazy from sqlmodel import SQLModel, Table, col, select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.models.download_job import DownloadJob
lazy from ..db.models.library import Library
lazy from ..db.models.media_server import MediaServer
lazy from ..db.tables import table_models, table_of
lazy from ..utils.types import JsonValue

#: One stored row: its table's name and its values.
type StoredValues = tuple[str, dict[str, JsonValue]]

#: Tables of work done for a record rather than of what it holds.
_WORK_TABLES = frozenset({DownloadJob.__tablename__})


class RecordRepository:
    """Follow foreign keys from one row, so a new table or column shows unasked."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def rows(self, model: type[SQLModel], key: int) -> list[StoredValues]:
        """The row of *model* with primary key *key*, then the rows referring to it.

        Rows of link tables, which only pair two records, and of jobs, which
        are work done for it, are left out.
        """
        table_models()
        table = table_of(model)
        (primary,) = table.primary_key.columns
        return await self._rows(table, primary == key)

    async def _rows(
        self, table: Table, condition: ColumnElement[bool]
    ) -> list[StoredValues]:
        connection = await self.session.connection()
        found: list[StoredValues] = []
        for row in (
            await connection.execute(table.select().where(condition))
        ).mappings():
            found.append((table.name, to_jsonable_python(dict(row))))
            primary = list(table.primary_key.columns)
            if len(primary) != 1:
                continue
            key = row[primary[0].name]
            for child in SQLModel.metadata.sorted_tables:
                # A link table only pairs two records; each record's own view
                # shows the pairing, so its rows add nothing here.
                if len(child.primary_key.columns) > 1 or child.name in _WORK_TABLES:
                    continue
                for foreign in child.foreign_keys:
                    if foreign.column is primary[0]:
                        found.extend(await self._rows(child, foreign.parent == key))
        return found

    async def library_names(self, rows: Sequence[StoredValues]) -> dict[str, str]:
        """Each library the rows name, by its ID, after its server: "Plex · Movies"."""
        ids = {
            str(values["library_id"])
            for _, values in rows
            if isinstance(values.get("library_id"), str)
        }
        found = await self.session.exec(
            select(Library.id, Library.title, MediaServer.title)
            .join(MediaServer, col(MediaServer.id) == col(Library.server_id))
            .where(col(Library.id).in_(ids))
        )
        return {library: f"{server} · {title}" for library, title, server in found}

    async def server_names(self, rows: Sequence[StoredValues]) -> dict[int, str]:
        """Each media server the rows name, by the database's number of it."""
        ids = {
            server
            for _, values in rows
            if isinstance(server := values.get("server_id"), int)
        }
        found = await self.session.exec(
            select(MediaServer.id, MediaServer.title).where(
                col(MediaServer.id).in_(ids)
            )
        )
        return {server: title for server, title in found if server is not None}
