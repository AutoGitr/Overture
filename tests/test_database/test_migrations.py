"""Startup creates or upgrades the schema and safely accepts repeated runs."""

lazy import json
lazy import logging
lazy from pathlib import Path

lazy import pytest
lazy from alembic import command
lazy from sqlalchemy import (
    CheckConstraint,
    create_engine,
    inspect,
    text,
)
lazy from sqlalchemy.engine import Connection
lazy from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

lazy from overture.db import metadata
lazy from overture.db import session as session_module
lazy from overture.db.session import Database, alembic_config, run_migrations
lazy from overture.migrations import versions_at_head


def test_baseline_downgrade_removes_all_tables_and_can_be_reapplied() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "1")
            tables = set(inspect(conn).get_table_names())
            assert {"media_items", "seasons", "download_jobs"} <= tables
            conn.exec_driver_sql(
                "INSERT INTO media_items "
                "(id, media_type, title, monitored, theme_provenance_cleared) "
                "VALUES (1, 'movie', 'Movie', 1, 0)"
            )

            command.downgrade(config, "base")

            assert inspect(conn).get_table_names() == ["alembic_version"]
            assert (
                conn.exec_driver_sql("SELECT version_num FROM alembic_version").all()
                == []
            )
            command.upgrade(config, "1")
            assert set(inspect(conn).get_table_names()) == tables
            assert conn.exec_driver_sql("SELECT id FROM media_items").all() == []
    finally:
        engine.dispose()


def _sync_table_names(connection: Connection) -> list[str]:
    return inspect(connection).get_table_names()


async def _table_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        return set(await conn.run_sync(_sync_table_names))


async def _revision(engine: AsyncEngine) -> str | None:
    async with engine.connect() as conn:
        rows = await conn.execute(text("select version_num from alembic_version"))
        row = rows.fetchone()
        return row[0] if row else None


async def test_a_fresh_database_is_created_at_head(tmp_path: Path) -> None:
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fresh.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(run_migrations)

        tables = await _table_names(engine)
        assert "media_items" in tables
        assert "alembic_version" in tables
        assert await _revision(engine) == versions_at_head()
    finally:
        await engine.dispose()


async def test_running_twice_is_a_no_op(tmp_path: Path) -> None:
    """Every restart runs this, so it has to be safe to repeat."""
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'twice.db'}")
    try:
        for _ in range(2):
            async with engine.begin() as conn:
                await conn.run_sync(run_migrations)
        assert await _revision(engine) == versions_at_head()
    finally:
        await engine.dispose()


async def test_only_an_existing_schema_upgrade_runs_the_pre_upgrade_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'probe.db'}")

    async def record() -> None:
        seen.append("called")

    try:
        # On a fresh database, upgrade_pending is False, so hook is not called.
        await database.initialize(record)
        assert seen == []

        def fake_pending(_connection: Connection) -> bool:
            return True

        monkeypatch.setattr(session_module, "upgrade_pending", fake_pending)
        await database.initialize(record)
        assert seen == ["called"]
    finally:
        await database.close()


@pytest.mark.parametrize("invalid_reference", [False, True])
async def test_failed_startup_migration_rolls_back_and_restores_foreign_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, invalid_reference: bool
) -> None:
    database = Database(f"sqlite+aiosqlite:///{tmp_path / 'rollback.db'}")
    try:
        await database.initialize()

        def failing_migration(connection: Connection) -> tuple[str, str]:
            connection.exec_driver_sql(
                "INSERT INTO media_items "
                "(id, media_type, title, monitored, theme_provenance_cleared) "
                "VALUES (1, 'show', 'Must roll back', 1, 0)"
            )
            if invalid_reference:
                connection.exec_driver_sql(
                    "INSERT INTO seasons (media_item_id, season_num, file_count) "
                    "VALUES (999, 1, 1)"
                )
                return "head", "head"
            connection.exec_driver_sql("CREATE TABLE migration_probe (id INTEGER)")
            msg = "Migration failed"
            raise RuntimeError(msg)

        with monkeypatch.context() as patch:
            patch.setattr(session_module, "run_migrations", failing_migration)
            with pytest.raises(
                RuntimeError,
                match="invalid foreign-key references"
                if invalid_reference
                else "Migration failed",
            ):
                await database.initialize()

        async with database.engine.connect() as conn:
            assert (await conn.exec_driver_sql("PRAGMA foreign_keys")).scalar() == 1
            assert (await conn.exec_driver_sql("SELECT * FROM media_items")).all() == []
            assert (await conn.exec_driver_sql("SELECT * FROM seasons")).all() == []
        assert "migration_probe" not in await _table_names(database.engine)
        assert await _revision(database.engine) == versions_at_head()
        await database.initialize()
    finally:
        await database.close()


async def test_embedded_migrations_do_not_reconfigure_application_logging(
    tmp_path: Path,
) -> None:
    """Alembic must not disable the app's loggers during startup."""
    root = logging.getLogger()
    application_logger = logging.getLogger("overture.logging_probe")
    original_root_level = root.level
    original_handlers = list(root.handlers)
    original_disabled = application_logger.disabled
    root.setLevel(logging.INFO)
    application_logger.disabled = False
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'logging.db'}")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(run_migrations)

        assert root.level == logging.INFO
        assert root.handlers == original_handlers
        assert application_logger.disabled is False
    finally:
        await engine.dispose()
        root.setLevel(original_root_level)
        root.handlers[:] = original_handlers
        application_logger.disabled = original_disabled


def test_autogenerate_finds_no_unapplied_changes() -> None:
    """``alembic check`` finds nothing to do: a model change needs a migration.

    It runs ``env.py``, so it compares with the same options as autogenerate.
    """
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
            command.check(config)
    finally:
        engine.dispose()


def test_every_model_check_constraint_exists_at_head() -> None:
    """Autogenerate ignores CHECK constraints, so compare them by name and rule."""
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
            inspector = inspect(conn)
            migrated = {
                (table, check["name"], check["sqltext"])
                for table in inspector.get_table_names()
                for check in inspector.get_check_constraints(table)
            }
    finally:
        engine.dispose()

    declared = {
        (table.name, constraint.name, str(constraint.sqltext))
        for table in metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert declared == migrated


def test_revision_2_moves_collection_choices_and_keeps_the_setting() -> None:
    """Kept collection themes wait unlisted for a sync; the toggle carries over."""
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "1")
            conn.exec_driver_sql(
                "INSERT INTO collection_themes (id, server_item_id, media_type, "
                "server_type, youtube_id, server_theme_id, monitored) VALUES "
                "(1, 'c1', 'movie', 'plex', 'abcDEF12345', '/theme/1', 1), "
                "(2, 'c2', 'show', 'plex', NULL, NULL, 1)"
            )
            conn.exec_driver_sql(
                "INSERT INTO app_settings (id, auto_match_art, workflow, "
                "theme_search_format, min_duration_seconds, max_duration_seconds, "
                "normalize_theme_loudness, skip_media_server_tmdb_urls, "
                "disable_media_server_art, aspect_ratio_tolerance, "
                "plex_collections_enabled, tmdb_language_filter, auto_advance, "
                "auto_advance_skip_completed, auto_unmonitor) VALUES (1, 0, 'art', "
                "'{title}', 30, 300, 1, 0, 0, 'strict', 0, 'en_null', 0, 1, 'off')"
            )

            command.upgrade(config, "2")

            assert conn.exec_driver_sql(
                "SELECT server_item_id, media_type, youtube_id, server_theme_id, "
                "tmdb_match, last_synced_at FROM media_collections "
                "ORDER BY server_item_id"
            ).all() == [
                ("c1", "movie", "abcDEF12345", "/theme/1", "auto", None),
                ("c2", "show", None, None, "auto", None),
            ]
            assert conn.exec_driver_sql(
                "SELECT collections_enabled FROM app_settings"
            ).all() == [(0,)]

            command.downgrade(config, "1")

            # Only the collection holding a choice of the user's goes back.
            assert conn.exec_driver_sql(
                "SELECT server_item_id, youtube_id FROM collection_themes"
            ).all() == [("c1", "abcDEF12345")]
            assert conn.exec_driver_sql(
                "SELECT plex_collections_enabled FROM app_settings"
            ).all() == [(0,)]
    finally:
        engine.dispose()


@pytest.mark.parametrize("revision", ["1", "2"])
def test_collection_ids_upgrade_jobs_and_history_and_downgrade_without_loss(
    revision: str,
) -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "1")
            conn.exec_driver_sql(
                "INSERT INTO collection_themes (id, server_item_id, "
                "media_type, server_type, "
                "youtube_id, monitored) VALUES (7, '42', 'movie', 'plex', "
                "'abcDEF12345', 1)"
            )
            command.upgrade(config, revision)
            conn.exec_driver_sql(
                "INSERT INTO download_jobs (id, job_type, collection_server_id, "
                "collection_media_type, collection_title, status, "
                "progress_percent, created_at) "
                "VALUES ('pending', 'collection_theme', '42', 'movie', "
                "'Saga', 'pending', 0, '2026-01-01'), "
                "('orphan', 'collection_theme', 'gone', 'movie', 'Gone', "
                "'done', 100, '2026-01-01')"
            )
            old = {
                "job": {
                    "target": {
                        "target_type": "collection_theme",
                        "collection_server_id": "42",
                        "media_type": "movie",
                        "title": "Saga",
                    }
                }
            }
            conn.exec_driver_sql(
                "INSERT INTO job_runs (id, kind, started_at, event, "
                "summary, total, log_total, cleared) "
                "VALUES ('run', 'download', '2026-01-01', "
                "'download.completed', '{}', 1, 0, 0)"
            )
            conn.execute(
                text("INSERT INTO job_results VALUES ('run', 0, :payload)"),
                {"payload": json.dumps(old)},
            )
            command.upgrade(config, "head")
            collection_id = conn.exec_driver_sql(
                "SELECT id FROM media_collections WHERE server_item_id='42'"
            ).scalar_one()
            assert (
                conn.exec_driver_sql(
                    "SELECT collection_id FROM download_jobs WHERE id='pending'"
                ).scalar_one()
                == collection_id
            )
            target = json.loads(
                conn.exec_driver_sql("SELECT payload FROM job_results").scalar_one()
            )["job"]["target"]
            assert target == {
                "target_type": "collection_theme",
                "collection_id": collection_id,
                "title": "Saga",
            }
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
            assert (
                conn.exec_driver_sql("SELECT count(*) FROM download_jobs").scalar_one()
                == 2
            )
            assert "collections_enabled" not in {
                col["name"] for col in inspect(conn).get_columns("app_settings")
            }
            command.downgrade(config, "1")
            assert (
                conn.exec_driver_sql(
                    "SELECT collection_server_id FROM download_jobs WHERE id='pending'"
                ).scalar_one()
                == "42"
            )
            assert (
                json.loads(
                    conn.exec_driver_sql("SELECT payload FROM job_results").scalar_one()
                )
                == old
            )
            assert (
                conn.exec_driver_sql(
                    "SELECT youtube_id FROM collection_themes WHERE server_item_id='42'"
                ).scalar_one()
                == "abcDEF12345"
            )
            command.upgrade(config, "head")
            assert conn.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    finally:
        engine.dispose()
