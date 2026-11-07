"""Read a row and every row that refers to it, from the table metadata alone."""

lazy from pydantic_core import to_jsonable_python
lazy from sqlalchemy import ColumnElement
lazy from sqlmodel import SQLModel, Table
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from ..db.tables import table_models, table_of
lazy from ..schemas.records import StoredRow


class RecordRepository:
    """Follow foreign keys from one row, so a new table or column shows unasked."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def rows(self, model: type[SQLModel], key: int) -> list[StoredRow]:
        """The row of *model* with primary key *key*, then the rows referring to it."""
        table_models()
        table = table_of(model)
        (primary,) = table.primary_key.columns
        return await self._rows(table, primary == key)

    async def _rows(
        self, table: Table, condition: ColumnElement[bool]
    ) -> list[StoredRow]:
        connection = await self.session.connection()
        found: list[StoredRow] = []
        for row in (
            await connection.execute(table.select().where(condition))
        ).mappings():
            found.append(
                StoredRow(table=table.name, values=to_jsonable_python(dict(row)))
            )
            primary = list(table.primary_key.columns)
            if len(primary) != 1:
                continue
            key = row[primary[0].name]
            for child in SQLModel.metadata.sorted_tables:
                for foreign in child.foreign_keys:
                    if foreign.column is primary[0]:
                        found.extend(await self._rows(child, foreign.parent == key))
        return found
