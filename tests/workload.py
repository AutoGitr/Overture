"""Record what the database does while a piece of work runs."""

lazy import asyncio
lazy import time
lazy from collections import Counter
lazy from collections.abc import AsyncGenerator, Generator, Sequence
lazy from contextlib import asynccontextmanager, contextmanager
lazy from contextvars import ContextVar
lazy from dataclasses import dataclass, field
lazy from typing import Any

lazy from sqlalchemy import event
lazy from sqlalchemy.ext.asyncio import AsyncEngine
lazy from sqlalchemy.orm import Mapper

#: Set while the current task is inside a write transaction.
WRITING: ContextVar[bool] = ContextVar("writing", default=False)

#: Statements that manage the connection rather than read or change data.
_HOUSEKEEPING = ("PRAGMA", "BEGIN", "COMMIT", "ROLLBACK", "SAVEPOINT", "RELEASE")

#: A plan line that visits a whole table; a covering index is still a scan.
_TABLE_SCAN = "SCAN "


@dataclass(slots=True)
class Workload:
    """The database's share of one piece of work."""

    #: Each statement that read or changed data, with its parameters.
    statements: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])
    #: How many entities the ORM built, by model.
    entities: Counter[str] = field(default_factory=Counter[str])
    #: The rows the largest write transaction changed or asked about.
    largest_write: int = 0
    #: The rows the transaction in progress has touched, if one is.
    writing: int | None = None

    @property
    def selects(self) -> list[tuple[str, Any]]:
        return [row for row in self.statements if row[0].startswith("SELECT")]

    @property
    def counts(self) -> tuple[int, int, int]:
        """What must not grow with the library, for comparing two runs."""
        return len(self.statements), self.entities.total(), self.largest_write

    def end_transaction(self) -> None:
        if self.writing is not None:
            self.largest_write = max(self.largest_write, self.writing)
        self.writing = None


@contextmanager
def recording(engine: AsyncEngine) -> Generator[Workload]:
    """Collect every statement and entity *engine*'s connections produce."""
    workload = Workload()
    target = engine.sync_engine

    def statement(
        _connection: Any,
        _cursor: Any,
        text: str,
        parameters: Any,
        _context: Any,
        executemany: bool,
    ) -> None:
        if text.startswith("BEGIN IMMEDIATE"):
            workload.writing = 0
        if text.startswith(_HOUSEKEEPING):
            return
        workload.statements.append((text, parameters))
        if workload.writing is not None:
            workload.writing += len(parameters) if executemany else 1

    def loaded(entity: Any, _context: Any) -> None:
        workload.entities[type(entity).__name__] += 1

    def ended(_connection: Any) -> None:
        workload.end_transaction()

    event.listen(target, "before_cursor_execute", statement)
    event.listen(target, "commit", ended)
    event.listen(target, "rollback", ended)
    event.listen(Mapper, "load", loaded)
    try:
        yield workload
    finally:
        event.remove(Mapper, "load", loaded)
        event.remove(target, "rollback", ended)
        event.remove(target, "commit", ended)
        event.remove(target, "before_cursor_execute", statement)


async def table_scans(
    engine: AsyncEngine, statements: Sequence[tuple[str, Any]], tables: Sequence[str]
) -> list[str]:
    """Return the plan lines that read one of *tables* from end to end."""
    found: list[str] = []
    async with engine.connect() as connection:
        for text, parameters in statements:
            plan = await connection.exec_driver_sql(
                f"EXPLAIN QUERY PLAN {text}", parameters
            )
            found.extend(
                f"{line}: {text}"
                for *_, line in plan.all()
                if line.startswith(_TABLE_SCAN) and line.split()[1] in tables
            )
    return found


@dataclass(slots=True)
class Stall:
    """The longest the event loop went without running anything else, in seconds."""

    longest: float = 0.0


@asynccontextmanager
async def watching_the_event_loop() -> AsyncGenerator[Stall]:
    """Measure how long the block keeps other requests from being served."""
    stall = Stall()
    interval = 0.005

    async def beat() -> None:
        previous = time.perf_counter()
        while True:
            await asyncio.sleep(interval)
            now = time.perf_counter()
            stall.longest = max(stall.longest, now - previous - interval)
            previous = now

    task = asyncio.create_task(beat())
    try:
        yield stall
    finally:
        task.cancel()
