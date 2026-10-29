"""Startup creates or upgrades the schema and safely accepts repeated runs."""

lazy import json
lazy import logging
lazy from pathlib import Path

lazy import pytest
lazy from alembic import command
lazy from sqlalchemy import (
    Boolean,
    CheckConstraint,
    MetaData,
    Table,
    create_engine,
    insert,
    inspect,
    text,
)
lazy from sqlalchemy.engine import Connection
lazy from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

lazy from overture.db import metadata
lazy from overture.db import session as session_module
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.settings import AppSettings
lazy from overture.db.session import Database, alembic_config, run_migrations
lazy from overture.domain import MediaType, ServerType
lazy from overture.migrations import versions_at_head


def _previous_settings(settings: Table, **values: object) -> dict[str, object]:
    """Today's settings defaults, in the forms earlier revisions stored."""
    return {
        **AppSettings().model_dump(
            include={column.name for column in settings.columns}
        ),
        **(
            {"collection_sync_interval_hours": 24}
            if "collection_sync_interval_hours" in settings.c
            else {}
        ),
        # Auto-advance was a flag before it had modes.
        **(
            {"auto_advance": False}
            if isinstance(settings.c.auto_advance.type, Boolean)
            else {}
        ),
        **values,
    }


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
            connection.execute(
                insert(MediaItem).values(
                    **MediaItem(
                        id=1, media_type=MediaType.SHOW, title="Must roll back"
                    ).model_dump()
                )
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


def test_revision_4_clears_only_show_collection_matches() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "3")
            conn.exec_driver_sql(
                "INSERT INTO media_collections (server_item_id, media_type, "
                "server_type, title, child_count, tmdb_collection_id, tmdb_match, "
                "monitored, youtube_id) VALUES "
                "('movies', 'movie', 'plex', 'Movies', 2, 10, 'manual', 1, NULL), "
                "('shows', 'show', 'plex', 'Shows', 2, 20, 'manual', 0, 'abcDEF12345')"
            )
            command.upgrade(config, "4")
            expected = [
                ("movies", 10, "manual", 1, None),
                ("shows", None, "auto", 0, "abcDEF12345"),
            ]
            query = (
                "SELECT server_item_id, tmdb_collection_id, tmdb_match, "
                "monitored, youtube_id FROM media_collections ORDER BY server_item_id"
            )
            assert conn.exec_driver_sql(query).all() == expected
            command.downgrade(config, "3")
            assert conn.exec_driver_sql(query).all() == expected
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


def test_revision_5_preserves_collection_members_art_and_settings() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "4")
            conn.exec_driver_sql(
                "INSERT INTO media_items (id, media_type, title, monitored, "
                "theme_provenance_cleared) VALUES (1, 'movie', 'Movie', 1, 0)"
            )
            conn.exec_driver_sql(
                "INSERT INTO media_collections (id, server_item_id, media_type, "
                "server_type, title, child_count, monitored, tmdb_match) VALUES "
                "(1, 'server', 'movie', 'plex', 'Saga', 1, 1, 'auto')"
            )
            conn.exec_driver_sql(
                "INSERT INTO media_collection_members (collection_id, "
                "media_item_id) VALUES (1, 1)"
            )
            conn.exec_driver_sql(
                "INSERT INTO art_slots (media_item_id, art_type, url) VALUES (1, "
                "'poster', 'https://example.test/a.jpg')"
            )
            # The former singleton may already hold non-default user choices.
            conn.exec_driver_sql(
                "INSERT INTO app_settings (id, auto_match_art, workflow, "
                "theme_search_format, min_duration_seconds, max_duration_seconds, "
                "normalize_theme_loudness, skip_media_server_tmdb_urls, "
                "disable_media_server_art, aspect_ratio_tolerance, "
                "tmdb_language_filter, auto_advance, auto_advance_skip_completed, "
                "auto_unmonitor) VALUES (1, 1, 'art', 'custom', 30, 300, 1, 0, 0, "
                "'strict', 'en_null', 0, 1, 'off')"
            )
            command.upgrade(config, "head")
            assert conn.exec_driver_sql(
                "SELECT collection_sync_mode, collection_minimum_items, "
                "auto_match_art FROM app_settings"
            ).one() == ("sync", 1, 1)
            assert conn.exec_driver_sql(
                "SELECT order_type, visible_home FROM media_collections"
            ).one() == ("release.asc", 0)
            assert (
                conn.exec_driver_sql(
                    "SELECT position FROM media_collection_members"
                ).scalar_one()
                == 0
            )
            assert (
                conn.exec_driver_sql("SELECT genres FROM media_items").scalar_one()
                == "[]"
            )
            assert (
                conn.exec_driver_sql("SELECT url FROM art_slots").scalar_one()
                == "https://example.test/a.jpg"
            )
            conn.exec_driver_sql(
                "INSERT INTO art_slots (collection_id, art_type, url) VALUES (1, "
                "'poster', 'https://example.test/collection.jpg')"
            )
            command.downgrade(config, "4")
            assert (
                conn.exec_driver_sql("SELECT url FROM art_slots").scalar_one()
                == "https://example.test/a.jpg"
            )
            assert (
                conn.exec_driver_sql(
                    "SELECT media_item_id FROM media_collection_members"
                ).scalar_one()
                == 1
            )
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_collection_group_upgrade_preserves_existing_collections() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "ede4b777b0f9")
            connection.exec_driver_sql(
                "INSERT INTO media_collections "
                "(id, server_item_id, media_type, server_type, title, child_count, "
                "monitored, tmdb_match, order_type, visible_home) "
                "VALUES (1, 'saga', 'movie', 'plex', 'Saga', "
                "2, 1, 'auto', 'release', 0)"
            )
            command.upgrade(config, "head")
            assert connection.exec_driver_sql(
                "SELECT title, collection_group FROM media_collections"
            ).all() == [("Saga", None)]
            assert "ix_media_collections_collection_group" in {
                index["name"]
                for index in inspect(connection).get_indexes("media_collections")
            }
            connection.exec_driver_sql(
                "UPDATE media_collections SET collection_group = 'Weekend'"
            )
            command.downgrade(config, "ede4b777b0f9")
            assert connection.exec_driver_sql(
                "SELECT title FROM media_collections"
            ).all() == [("Saga",)]
            command.upgrade(config, "head")
            assert (
                connection.exec_driver_sql(
                    "SELECT collection_group FROM media_collections"
                ).scalar()
                is None
            )
    finally:
        engine.dispose()


def test_explicit_collection_identity_preserves_ids_and_downgrades_to_choices() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "6bb24ff9b36c")
            connection.exec_driver_sql(
                "INSERT INTO media_collections (server_item_id, media_type, "
                "server_type, title, child_count, monitored, tmdb_match, "
                "tmdb_collection_id, order_type, visible_home) VALUES "
                "('one','movie','plex','One',1,1,'auto',10,'release',0), "
                "('two','movie','plex','Two',1,1,'unmatched',NULL,'release',0)"
            )
            command.upgrade(config, "head")
            assert connection.exec_driver_sql(
                "SELECT tmdb_collection_id FROM media_collections "
                "ORDER BY server_item_id"
            ).all() == [(10,), (None,)]
            assert "tmdb_match" not in {
                column["name"]
                for column in inspect(connection).get_columns("media_collections")
            }
            command.downgrade(config, "6bb24ff9b36c")
            assert connection.exec_driver_sql(
                "SELECT tmdb_match FROM media_collections ORDER BY server_item_id"
            ).all() == [("manual",), ("unmatched",)]
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_collection_group_policy_migration_preserves_existing_settings_and_rules() -> (
    None
):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "de75601826ea")
            old = MetaData()
            settings = Table("app_settings", old, autoload_with=conn)
            collections = Table("media_collections", old, autoload_with=conn)
            rules = Table("collection_rules", old, autoload_with=conn)
            conn.execute(
                settings.insert().values(
                    **_previous_settings(settings, collection_minimum_items=4)
                )
            )
            conn.execute(
                collections.insert().values(
                    **_previous_collection(
                        collections,
                        id=1,
                        server_item_id="c1",
                        title="Saga",
                        collection_group="Weekend",
                    )
                )
            )
            conn.execute(
                rules.insert().values(
                    collection_id=1,
                    source_type="mdblist",
                    source_identifier="42",
                    minimum_items=2,
                    sync_interval_hours=24,
                    enabled=True,
                )
            )
            command.upgrade(config, "8bfb249cdcbd")
            assert conn.exec_driver_sql(
                "SELECT collection_minimum_items, collection_sort_title_format "
                "FROM app_settings"
            ).one() == (4, "")
            assert conn.exec_driver_sql(
                "SELECT minimum_items, auto_match_art, auto_match_theme "
                "FROM collection_rules"
            ).one() == (2, None, None)
            assert (
                conn.exec_driver_sql(
                    "SELECT collection_group FROM media_collections"
                ).scalar_one()
                == "Weekend"
            )
            assert (
                conn.exec_driver_sql(
                    "SELECT count(*) FROM collection_groups"
                ).scalar_one()
                == 0
            )
            command.upgrade(config, "9a1b2c3d4e5f")
            assert (
                conn.exec_driver_sql(
                    "SELECT builders_json FROM collection_rules"
                ).scalar_one()
                == '[{"type": "mdblist", "identifiers": ["42"]}]'
            )
            command.upgrade(config, "head")
            command.downgrade(config, "8bfb249cdcbd")
            command.downgrade(config, "de75601826ea")
            assert "collection_groups" not in inspect(conn).get_table_names()
            assert (
                conn.exec_driver_sql(
                    "SELECT minimum_items FROM collection_rules"
                ).scalar_one()
                == 2
            )
    finally:
        engine.dispose()


def test_collection_template_sources_preserve_metadata_and_sync_schedules() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "9a1b2c3d4e5f")
            old = MetaData()
            settings = Table("app_settings", old, autoload_with=conn)
            collections = Table("media_collections", old, autoload_with=conn)
            conn.execute(
                settings.insert().values(
                    **_previous_settings(settings, collection_order_default="release")
                )
            )
            conn.execute(
                collections.insert().values(
                    **_previous_collection(
                        collections,
                        id=1,
                        title="Saga",
                        summary="Literal {overview}",
                        sort_title="01_{literal}",
                    )
                )
            )
            conn.exec_driver_sql(
                "INSERT INTO saved_schedules "
                "(kind, name, enabled, cron_expression, payload_json, state_json, "
                "created_at, updated_at) "
                "VALUES ('sync', 'Nightly', 1, '0 2 * * *', ?, '{}', "
                "'2026-10-25', '2026-10-25')",
                (json.dumps({"mode": "full", "library_ids": ["1"]}),),
            )
            conn.execute(
                collections.insert().values(
                    **_previous_collection(
                        collections,
                        id=2,
                        title="Other",
                        summary="About Other: Original summary",
                        summary_format="About {title}: {summary}",
                    )
                )
            )
            command.upgrade(config, "head")
            assert (
                conn.exec_driver_sql(
                    "SELECT collection_import_unmanaged FROM app_settings"
                ).scalar_one()
                == 1
            )
            assert conn.exec_driver_sql(
                "SELECT summary, summary_source, summary_format, sort_title_format "
                "FROM media_collections WHERE id=1"
            ).one() == (
                "Literal {overview}",
                "Literal {overview}",
                "Literal {{overview}}",
                "01_{{literal}}",
            )
            assert conn.exec_driver_sql(
                "SELECT summary_source, summary_format "
                "FROM media_collections WHERE id=2"
            ).one() == ("Original summary", "About {title}: {summary}")
            payload = json.loads(
                conn.exec_driver_sql(
                    "SELECT payload_json FROM saved_schedules"
                ).scalar_one()
            )
            assert payload["include_collections"] is True
            assert payload["library_ids"] == ["1"]
            command.downgrade(config, "9a1b2c3d4e5f")
            command.upgrade(config, "head")
            assert (
                conn.exec_driver_sql(
                    "SELECT summary_format FROM media_collections WHERE id=1"
                ).scalar_one()
                == "Literal {{overview}}"
            )
    finally:
        engine.dispose()


def _previous_collection(table: Table, **values: object) -> dict[str, object]:
    """A movie collection row for revisions before orders named their direction."""
    row = MediaCollection.model_validate(
        {"media_type": MediaType.MOVIE, "server_type": ServerType.PLEX, **values}
    ).model_dump(include={column.name for column in table.columns})
    return {**row, "order_type": "release"}


def test_collection_criteria_migration_converts_rules_sets_orders_and_items() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "5cff4899af03")
            old = MetaData()
            collections = Table("media_collections", old, autoload_with=conn)
            rules = Table("collection_rules", old, autoload_with=conn)
            groups = Table("collection_groups", old, autoload_with=conn)
            for identity in (1, 2, 3, 4):
                conn.execute(
                    collections.insert().values(
                        **_previous_collection(
                            collections,
                            id=identity,
                            server_item_id=f"c{identity}",
                            title=f"Collection {identity}",
                        )
                    )
                )
            conn.execute(
                collections.update()
                .where(collections.c.id == 1)
                .values(order_type="alpha", auto_generated_tmdb_id=10)
            )
            library_filter = {
                "type": "library_filter",
                "filter_group": {
                    "mode": "all",
                    "conditions": [
                        {"field": "tag", "operator": "contains", "value": "kids"},
                        {"field": "added_within_days", "operator": "is", "value": 7},
                        {"field": "genre", "operator": "is", "value": ""},
                    ],
                    "groups": [],
                },
            }
            mdblist = {"type": "mdblist", "identifiers": ["user/list"]}
            seeded: tuple[
                tuple[int, list[object] | None, dict[str, object] | None, str | None],
                ...,
            ] = (
                (1, [mdblist, library_filter], None, None),
                (
                    2,
                    [mdblist],
                    {
                        "filter_group": {
                            "mode": "all",
                            "conditions": [
                                {"field": "unplayed", "operator": "is", "value": "1"}
                            ],
                            "groups": [],
                        },
                        "sort_by": "rating.desc",
                        "limit": 20,
                    },
                    "request",
                ),
                (3, None, None, None),
                (
                    4,
                    None,
                    {
                        "filter_group": {"mode": "all", "conditions": [], "groups": []},
                        "sort_by": "added.desc",
                        "limit": None,
                    },
                    "classic",
                ),
            )
            for collection_id, builders, smart, label in seeded:
                conn.execute(
                    rules.insert().values(
                        collection_id=collection_id,
                        source_type="filter",
                        source_identifier="",
                        builders_json=json.dumps(builders) if builders else None,
                        smart_filter_json=json.dumps(smart) if smart else None,
                        managed_label=label,
                        sync_interval_hours=24,
                        enabled=True,
                        order_type="custom",
                    )
                )
            conn.execute(
                groups.insert().values(
                    server_type="plex",
                    media_type="movie",
                    name="Franchises",
                    dynamic_tmdb_json=json.dumps(
                        {
                            "enabled": True,
                            "library_id": "movies",
                            "strip_prefix": "The ",
                            "strip_suffix": " Collection",
                            "exclude_tmdb_ids": [86311],
                            "auto_exclude_from_other_collections": True,
                        }
                    ),
                )
            )
            conn.exec_driver_sql(
                "INSERT INTO media_items (id, media_type, title, monitored, "
                "theme_provenance_cleared, genres, actors, writers, producers, "
                "countries, labels, tags, rating) VALUES (1, 'movie', 'Movie', 1, 0, "
                "'[]', '[]', '[]', '[]', '[]', '[\"Kids\"]', '[\"Kids\", \"4K\"]', 7.5)"
            )

            command.upgrade(config, "head")

            criteria = {
                row[0]: (json.loads(row[1]), row[2], row[3], row[4])
                for row in conn.exec_driver_sql(
                    "SELECT collection_id, criteria_json, smart, item_limit, "
                    "order_type FROM collection_rules"
                )
            }
            source = {"kind": "source", "operator": "is", "source": mdblist}
            assert criteria[1] == (
                {
                    "mode": "any",
                    "conditions": [source],
                    "groups": [
                        {
                            "mode": "all",
                            "conditions": [
                                {
                                    "kind": "field",
                                    "field": "label",
                                    "operator": "is",
                                    "value": "kids",
                                },
                                {
                                    "kind": "field",
                                    "field": "added",
                                    "operator": "in_last",
                                    "value": 7,
                                },
                            ],
                            "groups": [],
                        }
                    ],
                },
                0,
                None,
                "custom",
            )
            unplayed = {
                "kind": "field",
                "field": "unplayed",
                "operator": "is",
                "value": True,
            }
            assert criteria[2] == (
                {
                    "mode": "all",
                    "conditions": [],
                    "groups": [
                        {"mode": "all", "conditions": [unplayed], "groups": []},
                        {"mode": "all", "conditions": [source], "groups": []},
                    ],
                },
                1,
                20,
                "critic_rating.desc",
            )
            assert 3 not in criteria
            assert criteria[4][0]["conditions"] == [
                {
                    "kind": "field",
                    "field": "label",
                    "operator": "is",
                    "value": "classic",
                }
            ]
            assert conn.exec_driver_sql(
                "SELECT order_type, generated_value FROM media_collections WHERE id=1"
            ).one() == ("title.asc", "10")
            generator = json.loads(
                conn.exec_driver_sql(
                    "SELECT generator_json FROM collection_groups"
                ).scalar_one()
            )
            assert generator["dimension"] == "franchise"
            assert generator["exclude"] == ["86311"]
            assert generator["strip_prefix"] == "The "
            assert conn.exec_driver_sql(
                "SELECT labels, critic_rating FROM media_items"
            ).one() == ('["Kids", "4K"]', None)

            command.downgrade(config, "5cff4899af03")
            assert conn.exec_driver_sql(
                "SELECT collection_id, builders_json, smart_filter_json "
                "FROM collection_rules ORDER BY collection_id"
            ).all()[0][0:2] == (
                1,
                json.dumps(
                    [
                        mdblist,
                        {
                            "type": "library_filter",
                            "filter_group": {
                                "mode": "all",
                                "conditions": [
                                    {
                                        "field": "label",
                                        "operator": "is",
                                        "value": "kids",
                                    },
                                    {
                                        "field": "added_within_days",
                                        "operator": "lte",
                                        "value": 7,
                                    },
                                ],
                                "groups": [],
                            },
                        },
                    ]
                ),
            )
            assert conn.exec_driver_sql(
                "SELECT order_type, auto_generated_tmdb_id FROM media_collections "
                "WHERE id=1"
            ).one() == ("alpha", 10)
            assert json.loads(
                conn.exec_driver_sql(
                    "SELECT dynamic_tmdb_json FROM collection_groups"
                ).scalar_one()
            )["exclude_tmdb_ids"] == [86311]
            command.upgrade(config, "head")
    finally:
        engine.dispose()


def test_unsynced_collections_upgrade_as_synced_and_downgrade() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "7d3f2a9c4b81")
            connection.exec_driver_sql(
                "INSERT INTO media_collections "
                "(id, server_item_id, media_type, server_type, kind, title, "
                "child_count, monitored, order_type, visible_home, visible_shared, "
                "visible_library) "
                "VALUES (1, 'saga', 'movie', 'plex', 'regular', 'Saga', 0, 1, "
                "'release.asc', 0, 0, 0)"
            )
            command.upgrade(config, "head")
            assert connection.exec_driver_sql(
                "SELECT title, unsynced FROM media_collections"
            ).all() == [("Saga", 0)]
            command.downgrade(config, "7d3f2a9c4b81")
            assert connection.exec_driver_sql(
                "SELECT title FROM media_collections"
            ).all() == [("Saga",)]
    finally:
        engine.dispose()


def test_cron_schedules_member_effects_and_set_libraries_convert_both_ways() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "b4e8c1d2f3a7")
            old = MetaData()
            settings = Table("app_settings", old, autoload_with=conn)
            conn.execute(
                settings.insert().values(
                    **_previous_settings(settings, collection_sync_interval_hours=6)
                )
            )
            conn.exec_driver_sql(
                "INSERT INTO media_collections "
                "(id, server_item_id, media_type, server_type, kind, title, "
                "child_count, monitored, order_type, visible_home, visible_shared, "
                "visible_library, unsynced) "
                "VALUES (1, 'saga', 'movie', 'plex', 'regular', 'Saga', 0, 1, "
                "'release.asc', 0, 0, 0, 0)"
            )
            person = {
                "mode": "all",
                "conditions": [
                    {
                        "kind": "source",
                        "operator": "is",
                        "source": {
                            "type": "tmdb_person",
                            "person_id": 5,
                            "roles": ["director"],
                            "use_biography": True,
                        },
                    }
                ],
                "groups": [],
            }
            conn.execute(
                text(
                    "INSERT INTO collection_rules (collection_id, criteria_json, "
                    "smart, sync_interval_hours, enabled) "
                    "VALUES (1, :criteria, 0, 168, 0)"
                ),
                {"criteria": json.dumps(person)},
            )
            conn.execute(
                text(
                    "INSERT INTO collection_groups (server_type, media_type, name, "
                    "sync_interval_hours, generator_json) "
                    "VALUES ('plex', 'movie', 'Decades', 12, :generator)"
                ),
                {
                    "generator": json.dumps(
                        {
                            "dimension": "decade",
                            "library_id": "movies",
                            "enabled": False,
                            "criteria": person,
                        }
                    )
                },
            )
            command.upgrade(config, "e6a1c2d3f4b5")
            assert conn.exec_driver_sql(
                "SELECT collection_sync_schedule, tmdb_region FROM app_settings"
            ).one() == ("0 */6 * * *", "US")
            schedule, sync_enabled, criteria = conn.exec_driver_sql(
                "SELECT sync_schedule, sync_enabled, criteria_json "
                "FROM collection_rules"
            ).one()
            assert (schedule, sync_enabled) == ("0 3 * * 0", 0)
            assert "use_biography" not in criteria
            assert (
                conn.exec_driver_sql(
                    "SELECT summary_format FROM media_collections"
                ).scalar()
                == "{source_summary}"
            )
            group_schedule, group_enabled, summary, generator = conn.exec_driver_sql(
                "SELECT sync_schedule, sync_enabled, summary_format, generator_json "
                "FROM collection_groups"
            ).one()
            assert (group_schedule, group_enabled, summary) == (
                "0 */12 * * *",
                0,
                "{source_summary}",
            )
            stored = json.loads(generator)
            assert (stored["library_ids"], stored["remove_vanished"]) == (
                ["movies"],
                False,
            )
            assert "enabled" not in stored

            command.downgrade(config, "b4e8c1d2f3a7")
            assert conn.exec_driver_sql(
                "SELECT sync_interval_hours, enabled FROM collection_rules"
            ).one() == (168, 0)
            restored = json.loads(
                conn.exec_driver_sql(
                    "SELECT generator_json FROM collection_groups"
                ).scalar_one()
            )
            assert restored["library_id"] == "movies"
            assert (
                conn.exec_driver_sql(
                    "SELECT collection_sync_interval_hours FROM app_settings"
                ).scalar()
                == 6
            )
    finally:
        engine.dispose()


def test_assets_schedules_drop_retry_saved_downloads() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "e6a1c2d3f4b5")
            connection.exec_driver_sql(
                "INSERT INTO saved_schedules "
                "(kind, name, enabled, cron_expression, payload_json, state_json, "
                "created_at, updated_at) "
                "VALUES ('assets', 'Nightly', 1, '0 2 * * *', ?, '{}', "
                "'2026-10-25', '2026-10-25')",
                (
                    json.dumps(
                        {
                            "library_ids": ["1"],
                            "retry_saved_downloads": True,
                            "themes": {},
                        }
                    ),
                ),
            )
            command.upgrade(config, "head")
            payload = connection.exec_driver_sql(
                "SELECT payload_json FROM saved_schedules"
            ).scalar_one()
            assert json.loads(payload) == {"library_ids": ["1"], "themes": {}}
            command.downgrade(config, "e6a1c2d3f4b5")
    finally:
        engine.dispose()


def test_incremental_poll_figures_move_to_the_last_run_and_back() -> None:
    engine = create_engine("sqlite://")
    state = {
        "checkpoint": "2026-10-25T00:00:00Z",
        "last_duration_seconds": 1.5,
        "last_items_added": 2,
        "last_downloads": 0,
    }
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "f3c9a1d7e2b6")
            connection.exec_driver_sql(
                "INSERT INTO saved_schedules "
                "(kind, name, enabled, cron_expression, payload_json, state_json, "
                "created_at, updated_at) "
                "VALUES ('sync', 'New media', 1, '*/15 * * * *', ?, ?, "
                "'2026-10-25', '2026-10-25')",
                (json.dumps({"mode": "incremental"}), json.dumps(state)),
            )
            command.upgrade(config, "head")
            [(saved_state, summary)] = connection.exec_driver_sql(
                "SELECT state_json, last_run_json FROM saved_schedules"
            ).all()
            assert json.loads(saved_state) == {"checkpoint": "2026-10-25T00:00:00Z"}
            assert json.loads(summary) == {
                "duration_seconds": 1.5,
                "counts": {"added": 2},
                "failed": False,
            }
            command.downgrade(config, "f3c9a1d7e2b6")
            restored = connection.exec_driver_sql(
                "SELECT state_json FROM saved_schedules"
            ).scalar_one()
            assert json.loads(restored) == state
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("enabled", "mode"), [(True, "slots_and_items"), (False, "off")]
)
def test_auto_advance_becomes_a_mode_and_require_group_defaults_off(
    enabled: bool, mode: str
) -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "a7d2e9c4f1b3")
            settings = Table("app_settings", MetaData(), autoload_with=connection)
            connection.execute(
                settings.insert().values(
                    **_previous_settings(settings, id=1, auto_advance=enabled)
                )
            )
            command.upgrade(config, "b4e8c2d6a9f1")
            assert connection.exec_driver_sql(
                "SELECT auto_advance, collection_require_group FROM app_settings"
            ).all() == [(mode, 0)]
            command.downgrade(config, "a7d2e9c4f1b3")
            assert connection.exec_driver_sql(
                "SELECT auto_advance FROM app_settings"
            ).all() == [(int(enabled),)]
    finally:
        engine.dispose()


def test_catalog_rows_gain_an_unset_no_theme_flag_and_lose_it_again() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "b4e8c2d6a9f1")
            connection.exec_driver_sql(
                "INSERT INTO public_dataset_collections (id, tmdb_id, title) "
                "VALUES (1, 10, 'Saga')"
            )
            command.upgrade(config, "head")
            assert connection.exec_driver_sql(
                "SELECT title, no_theme FROM public_dataset_collections"
            ).all() == [("Saga", 0)]
            command.downgrade(config, "b4e8c2d6a9f1")
            columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(public_dataset_collections)"
                )
            }
            assert "no_theme" not in columns
    finally:
        engine.dispose()


def test_overturedb_settings_start_on_and_sets_fold_removal_into_minimum() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "c5f9d3e7b1a2")
            settings = Table("app_settings", MetaData(), autoload_with=connection)
            connection.execute(
                settings.insert().values(**_previous_settings(settings, id=1))
            )
            generator = {"dimension": "decade", "library_ids": ["movies"]}
            connection.exec_driver_sql(
                "INSERT INTO collection_groups "
                "(id, server_type, media_type, name, generator_json) VALUES "
                "(1, 'plex', 'movie', 'Decades', ?), (2, 'plex', 'movie', 'Genres', ?)",
                (
                    json.dumps({**generator, "remove_vanished": True}),
                    json.dumps({**generator, "remove_vanished": False}),
                ),
            )
            preset = {
                "media_type": "movie",
                "label": "Decades",
                "set": {
                    "group": "Decades",
                    "policy": {},
                    "generator": {"dimension": "decade", "remove_vanished": True},
                },
            }
            connection.exec_driver_sql(
                "INSERT INTO collection_presets "
                "(id, media_type, label, description, payload_json) "
                "VALUES (1, 'movie', 'Decades', '', ?)",
                (json.dumps(preset),),
            )
            command.upgrade(config, "d8b3f6a2c9e4")
            assert connection.exec_driver_sql(
                "SELECT overturedb_no_theme, overturedb_browse FROM app_settings"
            ).all() == [(1, 1)]
            groups = connection.exec_driver_sql(
                "SELECT delete_below_minimum, generator_json FROM collection_groups "
                "ORDER BY id"
            ).all()
            assert [(row[0], json.loads(row[1])) for row in groups] == [
                (1, generator),
                (None, generator),
            ]
            saved = json.loads(
                connection.exec_driver_sql(
                    "SELECT payload_json FROM collection_presets"
                ).scalar_one()
            )
            assert saved["set"]["policy"] == {"delete_below_minimum": True}
            assert "remove_vanished" not in saved["set"]["generator"]

            command.downgrade(config, "c5f9d3e7b1a2")
            restored = [
                json.loads(row[0])["remove_vanished"]
                for row in connection.exec_driver_sql(
                    "SELECT generator_json FROM collection_groups ORDER BY id"
                )
            ]
            assert restored == [True, False]
    finally:
        engine.dispose()


def test_rules_lose_their_schedule_and_assets_runs_combine_collections() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection:
            config = alembic_config()
            config.attributes["connection"] = connection
            command.upgrade(config, "d8b3f6a2c9e4")
            settings = Table("app_settings", MetaData(), autoload_with=connection)
            connection.execute(
                settings.insert().values(
                    **_previous_settings(settings, id=1, collection_require_group=False)
                )
            )
            connection.exec_driver_sql(
                "INSERT INTO media_collections "
                "(id, server_item_id, media_type, server_type, kind, title, "
                "child_count, monitored, order_type, visible_home, visible_shared, "
                "visible_library, unsynced) "
                "VALUES (1, 'saga', 'movie', 'plex', 'regular', 'Saga', 0, 1, "
                "'release.asc', 0, 0, 0, 0)"
            )
            connection.exec_driver_sql(
                "INSERT INTO collection_rules "
                "(id, collection_id, criteria_json, smart, sync_schedule, "
                "sync_enabled) "
                "VALUES (1, 1, '{}', 0, '0 3 * * 0', 0)"
            )
            run = {
                "library_ids": ["movies"],
                "themes": {"source_order": ["overturedb"], "include_collections": True},
            }
            connection.exec_driver_sql(
                "INSERT INTO saved_schedules "
                "(id, kind, name, enabled, cron_expression, payload_json, state_json, "
                "created_at, updated_at) "
                "VALUES (1, 'assets', 'Nightly', 1, '0 2 * * *', ?, '{}', "
                "'2026-01-01', '2026-01-01')",
                (json.dumps(run),),
            )
            command.upgrade(config, "e9c4a7b1d3f5")
            columns = {
                row[1]
                for row in connection.exec_driver_sql(
                    "PRAGMA table_info(collection_rules)"
                )
            }
            assert not {"sync_schedule", "sync_enabled"} & columns
            assert json.loads(
                connection.exec_driver_sql(
                    "SELECT payload_json FROM saved_schedules"
                ).scalar_one()
            ) == {
                "library_ids": ["movies"],
                "all_collections": True,
                "themes": {"source_order": ["overturedb"]},
            }
            assert connection.exec_driver_sql(
                "SELECT collection_require_group FROM app_settings"
            ).scalar_one()

            command.downgrade(config, "d8b3f6a2c9e4")
            assert (
                json.loads(
                    connection.exec_driver_sql(
                        "SELECT payload_json FROM saved_schedules"
                    ).scalar_one()
                )
                == run
            )
    finally:
        engine.dispose()
