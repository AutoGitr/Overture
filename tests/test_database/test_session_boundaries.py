"""Session ownership, commit, rollback, and concurrent writes."""

lazy import pytest
lazy from sqlalchemy.exc import OperationalError
lazy from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker
lazy from sqlmodel import select
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.models.schedule import TaskSchedule
lazy from overture.db.session import Database


async def _schedule_names(factory: async_sessionmaker[AsyncSession]) -> list[str]:
    async with factory() as session:
        rows = await session.exec(select(TaskSchedule.task_name))
        return list(rows.all())


async def test_write_session_commits_on_a_clean_exit(
    database: Database,
    isolated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with database.write_session() as session:
        session.add(
            TaskSchedule(task_name="demo", enabled=True, cron_expression="0 * * * *")
        )

    assert await _schedule_names(isolated_session_factory) == ["demo"]


async def test_write_session_rolls_back_when_the_block_raises(
    database: Database,
    isolated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A half-finished write must not survive the exception that interrupted it."""

    async def add_then_fail() -> None:
        async with database.write_session() as session:
            session.add(
                TaskSchedule(
                    task_name="demo", enabled=True, cron_expression="0 * * * *"
                )
            )
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        await add_then_fail()

    assert await _schedule_names(isolated_session_factory) == []


async def test_read_session_does_not_persist_accidental_changes(
    database: Database,
    isolated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A reader commits nothing, so a stray add() is discarded rather than stored."""
    async with database.read_session() as session:
        session.add(
            TaskSchedule(task_name="demo", enabled=True, cron_expression="0 * * * *")
        )

    assert await _schedule_names(isolated_session_factory) == []


async def test_rows_read_stay_usable_after_the_reader_closes(
    database: Database,
    isolated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A loader can hand its rows back, which is why the reader never rolls back.

    ``rollback()`` expires every instance it loaded; ``close()`` detaches them
    with their values intact. Services build their work lists inside a reader
    and walk the rows afterwards, so this is the difference between a work list
    and a lapful of ``DetachedInstanceError``.
    """
    async with database.write_session() as session:
        session.add(
            TaskSchedule(task_name="demo", enabled=True, cron_expression="0 * * * *")
        )

    async with database.read_session() as session:
        rows = list((await session.exec(select(TaskSchedule))).all())

    assert [row.task_name for row in rows] == ["demo"]


async def test_a_writer_that_reads_first_still_writes(
    database: Database,
    isolated_engine: AsyncEngine,
    isolated_session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Looking a row up before inserting it must not forfeit the write.

    This is every ``sync_item``: a transaction that searches for a local match
    and inserts when it finds none, while other writers commit alongside it. A
    transaction that opens on its first read is holding a snapshot, and SQLite
    refuses to upgrade one once anyone else has committed - "database is
    locked", raised at once and never retried, whatever the busy timeout.
    Declaring the write as the transaction opens is what keeps the peer below
    from committing between the read and the write.
    """
    async with database.write_session() as session:
        await session.exec(select(TaskSchedule.task_name))
        async with isolated_engine.connect() as peer:
            await peer.exec_driver_sql("PRAGMA busy_timeout=0")
            with pytest.raises(OperationalError, match="database is locked"):
                await peer.exec_driver_sql("BEGIN IMMEDIATE")
            await peer.invalidate()
        session.add(
            TaskSchedule(task_name="held", enabled=True, cron_expression="0 * * * *")
        )

    assert await _schedule_names(isolated_session_factory) == ["held"]
