"""Rehearse restoring a live SQLite backup into a clean runtime database."""

lazy import shutil
lazy from pathlib import Path

lazy from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
lazy from sqlmodel import text
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import as_writer, configure_sqlite, run_migrations
lazy from overture.domain import MediaType, Workflow
lazy from overture.migrations import versions_at_head
lazy from overture.schemas.backup import BackupRetention
lazy from overture.services.backup.files import BackupStore


async def test_a_live_backup_restores_data_and_starts_at_schema_head(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "source" / "overture.db"
    source_path.parent.mkdir()
    source_engine = configure_sqlite(
        create_async_engine(f"sqlite+aiosqlite:///{source_path}")
    )
    restored_engine = None
    try:
        async with source_engine.begin() as connection:
            await connection.run_sync(run_migrations)

        sessions = async_sessionmaker(
            as_writer(source_engine), class_=AsyncSession, expire_on_commit=False
        )
        async with sessions() as session:
            session.add(AppSettings(id=1, workflow=Workflow.THEMES))
            session.add(
                MediaItem(
                    media_type=MediaType.MOVIE,
                    title="Arrival",
                    year=2016,
                    server_item_id="movie-1",
                )
            )
            await session.commit()

        backup_dir = tmp_path / "backups"
        backup_name = await BackupStore(source_path, backup_dir).create(
            retention=BackupRetention()
        )

        restored_path = tmp_path / "restored" / "overture.db"
        restored_path.parent.mkdir()
        restored_path.write_bytes(b"damaged database")
        shutil.copyfile(backup_dir / backup_name, restored_path)

        restored_engine = configure_sqlite(
            create_async_engine(f"sqlite+aiosqlite:///{restored_path}")
        )
        async with restored_engine.begin() as connection:
            await connection.run_sync(run_migrations)
            integrity = (
                await connection.execute(text("PRAGMA quick_check"))
            ).scalar_one()
            revision = (
                await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one()
            title = (
                await connection.execute(text("SELECT title FROM media_items"))
            ).scalar_one()
            workflow = (
                await connection.execute(text("SELECT workflow FROM app_settings"))
            ).scalar_one()

        assert integrity == "ok"
        assert revision == versions_at_head()
        assert title == "Arrival"
        assert workflow == "themes"
    finally:
        if restored_engine is not None:
            await restored_engine.dispose()
        await source_engine.dispose()
