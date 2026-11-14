"""Startup creates or upgrades the schema and safely accepts repeated runs."""

lazy import json
lazy import logging
lazy from pathlib import Path

lazy import pytest
lazy from alembic import command
lazy from sqlalchemy import insert
lazy from sqlalchemy.engine import Connection
lazy from sqlalchemy.exc import IntegrityError
lazy from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
lazy from sqlmodel import CheckConstraint, create_engine, inspect, text

lazy from overture.db import metadata
lazy from overture.db import session as session_module
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database, alembic_config, run_migrations
lazy from overture.domain import MediaType
lazy from overture.migrations import versions_at_head
lazy from overture.schemas.sync import SyncScheduleConfig


def test_baseline_downgrade_removes_all_tables_and_can_be_reapplied() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "head")
            tables = set(inspect(conn).get_table_names())
            assert {"media_items", "seasons", "download_jobs"} <= tables
            conn.execute(
                insert(MediaItem).values(
                    **MediaItem(
                        id=1, media_type=MediaType.MOVIE, title="Movie"
                    ).model_dump()
                )
            )

            command.downgrade(config, "base")

            assert inspect(conn).get_table_names() == ["alembic_version"]
            assert (
                conn.exec_driver_sql("SELECT version_num FROM alembic_version").all()
                == []
            )
            command.upgrade(config, "head")
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


def test_stored_minutes_become_seconds_and_back() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "d55c703635bb")
            conn.exec_driver_sql(
                "INSERT INTO media_items (id, media_type, title, monitored, "
                "genres, actors, writers, producers, countries, labels, "
                "origin_countries, tmdb_keywords, companies, networks, streaming, "
                "theme_provenance_cleared, duration_minutes) VALUES (1, 'movie', "
                "'Movie', 1, '[]', '[]', '[]', '[]', '[]', '[]', '[]', '[]', '[]', "
                "'[]', '[]', 0, 117)"
            )

            command.upgrade(config, "7fc9ce3c2813")
            assert conn.exec_driver_sql(
                "SELECT duration_seconds, sort_title FROM media_items"
            ).all() == [(7020, None)]

            command.downgrade(config, "d55c703635bb")
            assert conn.exec_driver_sql(
                "SELECT duration_minutes FROM media_items"
            ).all() == [(117,)]
    finally:
        engine.dispose()


def test_saved_presets_are_dropped_and_the_table_comes_back_empty() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "7fc9ce3c2813")
            conn.exec_driver_sql(
                "INSERT INTO collection_presets (media_type, label, description, "
                "payload_json) VALUES ('movie', 'Mine', '', '{}')"
            )

            command.upgrade(config, "b3a91c4e5f27")
            assert "collection_presets" not in inspect(conn).get_table_names()

            command.downgrade(config, "7fc9ce3c2813")
            assert conn.exec_driver_sql("SELECT * FROM collection_presets").all() == []
    finally:
        engine.dispose()


def test_a_movies_director_becomes_the_first_of_its_directors_and_back() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "b3a91c4e5f27")
            for item_id, director in ((1, "'Ridley Scott'"), (2, "NULL")):
                conn.exec_driver_sql(
                    "INSERT INTO media_items (id, media_type, title, monitored, "  # noqa: S608 -- literal test values
                    "genres, actors, writers, producers, countries, labels, "
                    "origin_countries, tmdb_keywords, companies, networks, streaming, "
                    "theme_provenance_cleared, director, director_etag) VALUES "
                    f"({item_id}, 'movie', 'Movie', 1, '[]', '[]', '[]', '[]', '[]', "
                    f"'[]', '[]', '[]', '[]', '[]', '[]', 0, {director}, 'v1')"
                )
            conn.exec_driver_sql(
                "INSERT INTO media_collections (id, media_type, server_type, kind, "
                "title, order_type, visible_home, visible_shared, visible_library, "
                "child_count, monitored, unsynced) VALUES (1, 'movie', 'plex', "
                "'regular', 'Saga', 'release.asc', 0, 0, 0, 0, 1, 0)"
            )

            command.upgrade(config, "c6d2e8f41a90")
            # A stored director loses its Etag, so the next sync reads them all.
            assert conn.exec_driver_sql(
                "SELECT directors, director_etag FROM media_items ORDER BY id"
            ).all() == [('["Ridley Scott"]', None), ("[]", "v1")]
            assert conn.exec_driver_sql(
                "SELECT deselected FROM media_collections"
            ).all() == [(0,)]

            command.downgrade(config, "b3a91c4e5f27")
            assert conn.exec_driver_sql(
                "SELECT director FROM media_items ORDER BY id"
            ).all() == [("Ridley Scott",), (None,)]
    finally:
        engine.dispose()


def _seed_collection(
    conn: Connection,
    collection_id: int,
    *,
    media_type: str,
    library_id: str,
    server_id: str,
    group: str,
    value: str | None = None,
) -> None:
    conn.execute(
        text(
            "INSERT INTO media_collections (id, server_item_id, media_type, "
            "library_id, server_type, kind, title, order_type, visible_home, "
            "visible_shared, "
            "visible_library, child_count, monitored, unsynced, deselected, "
            "collection_group, generated_value) VALUES (:id, :server, :type, :library, "
            "'plex', 'regular', 'Saga', 'release.asc', 0, 0, 0, 1, 1, 0, 0, :group, "
            ":value)"
        ),
        {
            "id": collection_id,
            "server": server_id,
            "type": media_type,
            "library": library_id,
            "group": group,
            "value": value,
        },
    )
    conn.execute(
        text(
            "INSERT INTO collection_rules (collection_id, criteria_json, smart) "
            "VALUES (:id, :criteria, 0)"
        ),
        {"id": collection_id, "criteria": f'{{"library": "{library_id}"}}'},
    )


def _seed_group(
    conn: Connection, media_type: str, name: str, minimum: int | None
) -> None:
    conn.execute(
        text(
            "INSERT INTO collection_groups (server_type, media_type, name, "
            "minimum_items) VALUES ('plex', :type, :name, :minimum)"
        ),
        {"type": media_type, "name": name, "minimum": minimum},
    )


def test_collections_move_to_their_libraries_and_groups_are_shared() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "c6d2e8f41a90")
            _seed_collection(
                conn, 1, media_type="movie", library_id="m", server_id="a", group="Same"
            )
            _seed_collection(
                conn, 2, media_type="show", library_id="s", server_id="b", group="Same"
            )
            _seed_collection(
                conn,
                3,
                media_type="movie",
                library_id="m",
                server_id="c",
                group="Differ",
            )
            _seed_collection(
                conn,
                4,
                media_type="show",
                library_id="s",
                server_id="d",
                group="Differ",
            )
            _seed_collection(
                conn,
                5,
                media_type="movie",
                library_id="m",
                server_id="e",
                group="Set",
                value="1990",
            )
            _seed_collection(
                conn,
                6,
                media_type="movie",
                library_id="m2",
                server_id="f",
                group="Set",
                value="1990",
            )
            conn.execute(
                text(
                    "INSERT INTO art_slots (collection_id, art_type, url) "
                    "VALUES (6, 'poster', 'https://example.test/poster.jpg')"
                )
            )
            _seed_group(conn, "movie", "Same", None)
            _seed_group(conn, "show", "Same", 3)
            _seed_group(conn, "movie", "Differ", 1)
            _seed_group(conn, "show", "Differ", 2)
            conn.execute(
                text(
                    "INSERT INTO saved_schedules (kind, name, enabled, "
                    "cron_expression, payload_json, state_json, created_at, "
                    "updated_at) VALUES ('sync', 'Nightly', 1, '0 3 * * *', :payload, "
                    "'{}', '2026-01-01', '2026-01-01')"
                ),
                {"payload": '{"collection_groups": ["Differ"]}'},
            )

            command.upgrade(config, "e1f4a7c92b3d")

            assert conn.exec_driver_sql(
                "SELECT collection_id, library_id, media_type, server_item_id, "
                "criteria_json FROM collection_libraries ORDER BY id"
            ).all() == [
                (1, "m", "movie", "a", '{"library": "m"}'),
                (2, "s", "show", "b", '{"library": "s"}'),
                (3, "m", "movie", "c", '{"library": "m"}'),
                (4, "s", "show", "d", '{"library": "s"}'),
                (5, "m", "movie", "e", '{"library": "m"}'),
                (5, "m2", "movie", "f", '{"library": "m2"}'),
            ]
            # Groups that agree merge; ones that differ keep every setting.
            assert conn.exec_driver_sql(
                "SELECT name, minimum_items FROM collection_groups ORDER BY name"
            ).all() == [("Differ", 1), ("Differ (Shows)", 2), ("Same", 3)]
            assert conn.exec_driver_sql(
                "SELECT id, collection_group FROM media_collections ORDER BY id"
            ).all() == [
                (1, "Same"),
                (2, "Same"),
                (3, "Differ"),
                (4, "Differ (Shows)"),
                (5, "Set"),
            ]
            assert (
                conn.exec_driver_sql(
                    "SELECT payload_json FROM saved_schedules"
                ).scalar_one()
                == '{"collection_groups": ["Differ", "Differ (Shows)"]}'
            )
            assert (
                conn.exec_driver_sql(
                    "SELECT child_count FROM media_collections WHERE id = 5"
                ).scalar_one()
                == 2
            )
            # Migrations run without cascades, so nothing of a merged row is left.
            assert (
                conn.exec_driver_sql("SELECT count(*) FROM art_slots").scalar_one() == 0
            )
            assert (
                conn.exec_driver_sql(
                    "SELECT count(*) FROM collection_rules WHERE collection_id = 6"
                ).scalar_one()
                == 0
            )

            command.downgrade(config, "c6d2e8f41a90")

            assert conn.exec_driver_sql(
                "SELECT id, media_type, library_id, server_item_id "
                "FROM media_collections ORDER BY id"
            ).all() == [
                (1, "movie", "m", "a"),
                (2, "show", "s", "b"),
                (3, "movie", "m", "c"),
                (4, "show", "s", "d"),
                (5, "movie", "m", "e"),
            ]
            assert (
                conn.exec_driver_sql(
                    "SELECT criteria_json FROM collection_rules WHERE collection_id = 5"
                ).scalar_one()
                == '{"library": "m"}'
            )
            # A shared group goes back to each media type its collections hold.
            assert conn.exec_driver_sql(
                "SELECT name, media_type FROM collection_groups "
                "ORDER BY name, media_type"
            ).all() == [
                ("Differ", "movie"),
                ("Differ (Shows)", "show"),
                ("Same", "movie"),
                ("Same", "show"),
            ]
    finally:
        engine.dispose()


def test_slots_select_uploads_and_lose_them_on_downgrade() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "e1f4a7c92b3d")
            conn.exec_driver_sql(
                "INSERT INTO media_items (id, media_type, title, monitored, "
                "genres, actors, writers, producers, countries, labels, "
                "origin_countries, tmdb_keywords, companies, networks, streaming, "
                "theme_provenance_cleared, directors) VALUES (1, 'movie', 'Movie', 1, "
                "'[]', '[]', '[]', '[]', '[]', '[]', '[]', '[]', '[]', '[]', '[]', 0, "
                "'[]')"
            )
            conn.exec_driver_sql(
                "INSERT INTO art_slots (id, media_item_id, art_type, url) "
                "VALUES (1, 1, 'poster', 'https://images.test/p.jpg')"
            )

            command.upgrade(config, "f3b8d2a61c47")
            assert conn.exec_driver_sql(
                "SELECT url, upload_hash FROM art_slots"
            ).all() == [("https://images.test/p.jpg", None)]
            conn.exec_driver_sql(
                "INSERT INTO art_slots (id, media_item_id, art_type, upload_hash) "
                "VALUES (2, 1, 'background', 'a')"
            )
            with pytest.raises(IntegrityError):
                conn.exec_driver_sql(
                    "UPDATE art_slots SET upload_hash = 'b' WHERE id = 1"
                )

            command.downgrade(config, "e1f4a7c92b3d")
            assert conn.exec_driver_sql("SELECT id, url FROM art_slots").all() == [
                (1, "https://images.test/p.jpg")
            ]
    finally:
        engine.dispose()


def test_movies_and_shows_keep_only_their_own_fields() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "f3b8d2a61c47")
            for item_id, media_type in ((1, "movie"), (2, "show")):
                conn.exec_driver_sql(
                    "INSERT INTO media_items (id, media_type, title, monitored, "  # noqa: S608 -- literal test values
                    "genres, actors, writers, producers, countries, labels, "
                    "origin_countries, tmdb_keywords, companies, networks, streaming, "
                    "theme_provenance_cleared, directors, show_status, last_aired, "
                    "edition, versions, tmdb_collection_id) VALUES "
                    f"({item_id}, '{media_type}', 'Title', 1, '[]', '[]', '[]', '[]', "
                    "'[]', '[]', '[]', '[]', '[]', '[\"HBO\"]', '[]', 0, '[]', "
                    "'Released', '2020-01-01', 'Cut', 2, 10)"
                )

            command.upgrade(config, "a4d7c1e93f20")
            assert conn.exec_driver_sql(
                "SELECT show_status, last_aired, networks, edition, versions, "
                "tmdb_collection_id FROM media_items ORDER BY id"
            ).all() == [
                (None, None, "[]", "Cut", 2, 10),
                ("Released", "2020-01-01", '["HBO"]', None, None, None),
            ]
            with pytest.raises(IntegrityError):
                conn.exec_driver_sql(
                    "UPDATE media_items SET edition = 'Cut' WHERE id = 2"
                )

            command.downgrade(config, "f3b8d2a61c47")
            conn.exec_driver_sql("UPDATE media_items SET edition = 'Cut' WHERE id = 2")
    finally:
        engine.dispose()


def test_stored_server_links_are_dropped_and_come_back_empty() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "a4d7c1e93f20")
            conn.exec_driver_sql(
                "INSERT INTO media_collections (id, server_type, kind, "
                "title, order_type, visible_home, visible_shared, visible_library, "
                "child_count, monitored, unsynced, deselected, server_link) VALUES "
                "(1, 'plex', 'regular', 'Saga', 'release.asc', 0, 0, 0, 0, "
                "1, 0, 0, 'https://server/1')"
            )

            command.upgrade(config, "b8e3f5a0c612")
            columns = {
                table: {column["name"] for column in inspect(conn).get_columns(table)}
                for table in ("media_items", "media_collections")
            }
            assert all("server_link" not in names for names in columns.values())

            command.downgrade(config, "a4d7c1e93f20")
            assert conn.exec_driver_sql(
                "SELECT title, server_link FROM media_collections"
            ).all() == [("Saga", None)]
    finally:
        engine.dispose()


def test_collections_reference_group_rows_and_name_them_again_on_downgrade() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "b8e3f5a0c612")
            conn.exec_driver_sql(
                "INSERT INTO collection_groups (id, server_type, name, minimum_items) "
                "VALUES (7, 'plex', 'Sagas', 3)"
            )
            for collection_id, group in (
                (1, "'Sagas'"),
                (2, "'Studios'"),
                (3, "NULL"),
                (4, "'Leftover'"),
            ):
                conn.exec_driver_sql(
                    "INSERT INTO media_collections (id, server_type, kind, title, "  # noqa: S608 -- literal test values
                    "order_type, visible_home, visible_shared, visible_library, "
                    "child_count, monitored, unsynced, deselected, collection_group) "
                    f"VALUES ({collection_id}, 'plex', 'regular', 'C{collection_id}', "
                    f"'release.asc', 0, 0, 0, 0, 1, 0, 0, {group})"
                )
            # Collections 1-3 are managed; 4 is not, so it belongs to no group.
            for collection_id in (1, 2, 3):
                conn.exec_driver_sql(
                    "INSERT INTO collection_rules (collection_id, smart) "  # noqa: S608 -- literal test values
                    f"VALUES ({collection_id}, 0)"
                )

            command.upgrade(config, "c2f9a7d4e815")
            assert conn.exec_driver_sql(
                "SELECT c.id, g.name, g.minimum_items FROM media_collections AS c "
                "LEFT JOIN collection_groups AS g ON g.id = c.group_id ORDER BY c.id"
            ).all() == [
                (1, "Sagas", 3),
                (2, "Studios", None),
                (3, "Ungrouped", None),
                (4, None, None),
            ]
            # A group its collections still reference cannot go.
            conn.exec_driver_sql("DELETE FROM collection_groups WHERE id = 7")
            assert conn.exec_driver_sql(
                "PRAGMA foreign_key_check(media_collections)"
            ).all()
            conn.exec_driver_sql(
                "INSERT INTO collection_groups (id, server_type, name, minimum_items) "
                "VALUES (7, 'plex', 'Sagas', 3)"
            )

            command.downgrade(config, "b8e3f5a0c612")
            assert conn.exec_driver_sql(
                "SELECT collection_group FROM media_collections ORDER BY id"
            ).all() == [("Sagas",), ("Studios",), ("Ungrouped",), (None,)]
    finally:
        engine.dispose()


def test_items_and_collections_reference_a_library_row_for_each_key() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "c2f9a7d4e815")
            conn.exec_driver_sql(
                "INSERT INTO media_items (id, media_type, title, monitored, "
                "genres, actors, writers, producers, countries, labels, "
                "origin_countries, tmdb_keywords, companies, networks, streaming, "
                "theme_provenance_cleared, directors, library_id) VALUES "
                "(1, 'movie', 'Movie', 1, '[]', '[]', '[]', '[]', '[]', '[]', '[]', "
                "'[]', '[]', '[]', '[]', 0, '[]', 'films')"
            )
            conn.exec_driver_sql(
                "INSERT INTO media_collections (id, server_type, kind, title, "
                "order_type, visible_home, visible_shared, visible_library, "
                "child_count, monitored, unsynced, deselected) VALUES "
                "(1, 'plex', 'regular', 'Saga', 'release.asc', 0, 0, 0, 0, 1, 0, 0)"
            )
            conn.exec_driver_sql(
                "INSERT INTO collection_libraries (collection_id, library_id, "
                "media_type) VALUES (1, 'series', 'show')"
            )

            command.upgrade(config, "d6a1b3c8f957")
            # Titled by key until the next sync names them.
            assert conn.exec_driver_sql(
                "SELECT id, media_type, title, removed_at FROM libraries ORDER BY id"
            ).all() == [
                ("films", "movie", "films", None),
                ("series", "show", "series", None),
            ]
            assert not conn.exec_driver_sql("PRAGMA foreign_key_check").all()

            command.downgrade(config, "c2f9a7d4e815")
            assert "libraries" not in inspect(conn).get_table_names()
    finally:
        engine.dispose()


def test_list_columns_become_shared_terms_in_order_and_come_back() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "d6a1b3c8f957")
            for item_id, media_type, genres, directors in (
                (1, "movie", '["Drama", "Action", "Drama", ""]', '["Lead"]'),
                (2, "show", '["Action"]', '["Ignored"]'),
            ):
                conn.exec_driver_sql(
                    "INSERT INTO media_items (id, media_type, title, monitored, "  # noqa: S608 -- literal test values
                    "genres, actors, writers, producers, countries, labels, "
                    "origin_countries, tmdb_keywords, companies, networks, streaming, "
                    "theme_provenance_cleared, directors) VALUES "
                    f"({item_id}, '{media_type}', 'Title', 1, '{genres}', '[]', '[]', "
                    "'[]', '[]', '[]', '[]', '[]', '[]', '[]', '[]', 0, "
                    f"'{directors}')"
                )

            command.upgrade(config, "e5b2d8f1a346")
            assert conn.exec_driver_sql(
                "SELECT l.media_item_id, t.kind, t.name, l.position "
                "FROM media_item_terms AS l JOIN terms AS t ON t.id = l.term_id "
                "ORDER BY l.media_item_id, t.kind, l.position"
            ).all() == [
                (1, "director", "Lead", 0),
                (1, "genre", "Drama", 0),
                (1, "genre", "Action", 1),
                (2, "genre", "Action", 0),
            ]
            assert conn.exec_driver_sql("SELECT COUNT(*) FROM terms").all() == [(3,)]

            command.downgrade(config, "d6a1b3c8f957")
            assert conn.exec_driver_sql(
                "SELECT genres, directors FROM media_items ORDER BY id"
            ).all() == [('["Drama","Action"]', '["Lead"]'), ('["Action"]', "[]")]
    finally:
        engine.dispose()


def test_term_links_state_their_kind_are_clustered_and_come_back() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "a8d3e6f0c271")
            conn.exec_driver_sql(
                "INSERT INTO media_items (id, media_type, title, monitored, "
                "theme_provenance_cleared) VALUES (1, 'movie', 'Title', 1, 0)"
            )
            conn.exec_driver_sql(
                "INSERT INTO terms (id, kind, name) VALUES "
                "(1, 'genre', 'Drama'), (2, 'genre', 'Action'), (3, 'actor', 'Lead')"
            )
            conn.exec_driver_sql(
                "INSERT INTO media_item_terms (media_item_id, term_id, position) "
                "VALUES (1, 2, 1), (1, 1, 0), (1, 3, 0)"
            )

            command.upgrade(config, "c9e4f1b7a2d3")
            assert conn.exec_driver_sql(
                "SELECT media_item_id, kind, position, term_id FROM media_item_terms "
                "ORDER BY media_item_id, kind, position"
            ).all() == [(1, "actor", 0, 3), (1, "genre", 0, 1), (1, "genre", 1, 2)]
            assert conn.exec_driver_sql("PRAGMA index_list(media_item_terms)").all()
            assert not conn.exec_driver_sql(
                "SELECT 1 FROM sqlite_schema WHERE name = 'media_item_terms' "
                "AND sql NOT LIKE '%WITHOUT ROWID%'"
            ).all()

            command.downgrade(config, "a8d3e6f0c271")
            assert conn.exec_driver_sql(
                "SELECT media_item_id, term_id, position FROM media_item_terms "
                "ORDER BY term_id"
            ).all() == [(1, 1, 0), (1, 2, 1), (1, 3, 0)]
    finally:
        engine.dispose()


def test_json_columns_are_renamed_typed_and_hold_only_valid_json() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "e5b2d8f1a346")
            conn.exec_driver_sql(
                "INSERT INTO collection_groups (id, server_type, name, generator_json) "
                "VALUES (1, 'plex', 'Decades', '{\"dimension\": \"decade\"}')"
            )
            conn.exec_driver_sql(
                "INSERT INTO task_schedule (task_name, enabled, cron_expression, "
                "payload_json) VALUES ('backup', 1, '0 3 * * *', '{\"a\": 1}')"
            )

            command.upgrade(config, "f7c4a9e2b158")
            assert conn.exec_driver_sql(
                "SELECT generator FROM collection_groups"
            ).all() == [('{"dimension": "decade"}',)]
            assert conn.exec_driver_sql("SELECT payload FROM task_schedule").all() == [
                ('{"a": 1}',)
            ]
            with pytest.raises(IntegrityError):
                conn.exec_driver_sql("UPDATE task_schedule SET payload = 'not json'")

            command.downgrade(config, "e5b2d8f1a346")
            assert conn.exec_driver_sql(
                "SELECT generator_json FROM collection_groups"
            ).all() == [('{"dimension": "decade"}',)]
    finally:
        engine.dispose()


def test_drawn_art_and_separators_are_added_and_separators_go_on_downgrade() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "f7c4a9e2b158")
            command.upgrade(config, "a8d3e6f0c271")
            conn.exec_driver_sql(
                "INSERT INTO collection_groups (id, server_type, name, separator) "
                "VALUES (1, 'plex', 'Sagas', 1)"
            )
            conn.exec_driver_sql(
                "INSERT INTO media_collections (id, server_type, kind, title, "
                "order_type, visible_home, visible_shared, visible_library, "
                "child_count, monitored, unsynced, deselected, group_id) VALUES "
                "(1, 'plex', 'separator', 'Sagas', 'release.asc', 0, 0, 0, 0, 1, 0, "
                "0, 1)"
            )
            with pytest.raises(IntegrityError):
                conn.exec_driver_sql(
                    "INSERT INTO art_slots (collection_id, art_type, url, "
                    "generated_style) VALUES (1, 'poster', 'https://x.test/p.jpg', "
                    "'dark')"
                )

            command.downgrade(config, "f7c4a9e2b158")
            assert conn.exec_driver_sql(
                "SELECT COUNT(*) FROM media_collections"
            ).all() == [(0,)]
    finally:
        engine.dispose()


#: An application settings row as the revision before automatic art stores it.
_SETTINGS_BEFORE_AUTO_ART = {
    "id": 1,
    "collection_sync_mode": "'sync'",
    "collection_mode_default": "'default'",
    "collection_order_default": "'release.asc'",
    "collection_filtering_default": "'user'",
    "collection_visible_home": 0,
    "collection_visible_shared": 0,
    "collection_visible_library": 0,
    "collection_minimum_items": 2,
    "collection_delete_below_minimum": 1,
    "collection_auto_match_art": 1,
    "collection_auto_generate_art": 0,
    "collection_auto_match_theme": 0,
    "collection_sort_title_format": "''",
    "collection_summary_format": "''",
    "collection_delete_when_inactive": 1,
    "collection_sync_schedule": "'0 3 * * *'",
    "collection_sync_enabled": 1,
    "collection_request_missing": 0,
    "collection_import_unmanaged": 1,
    "overturedb_no_theme": 1,
    "overturedb_browse": 1,
    "tmdb_region": "'US'",
    "radarr_root_folder": "''",
    "radarr_search": 0,
    "sonarr_root_folder": "''",
    "sonarr_search": 0,
    "auto_match_art": 0,
    "workflow": "'art_and_themes'",
    "theme_search_format": "'{title}'",
    "min_duration_seconds": 20,
    "max_duration_seconds": 600,
    "normalize_theme_loudness": 1,
    "skip_media_server_tmdb_urls": 0,
    "disable_media_server_art": 0,
    "aspect_ratio_tolerance": "'strict'",
    "tmdb_language_filter": "'en_null'",
    "auto_advance": "'slots_and_items'",
    "auto_advance_skip_completed": 1,
    "auto_unmonitor": "'art_and_theme'",
}


def test_automatic_art_combines_each_tiers_switches_and_schedules_move_to_sync() -> (
    None
):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "c9e4f1b7a2d3")
            conn.exec_driver_sql(
                f"INSERT INTO app_settings ({', '.join(_SETTINGS_BEFORE_AUTO_ART)}) "  # noqa: S608 -- literal test values
                f"VALUES ({', '.join(map(str, _SETTINGS_BEFORE_AUTO_ART.values()))})"
            )
            conn.exec_driver_sql(
                "INSERT INTO collection_groups (id, server_type, name, separator, "
                "auto_generate_art, sync_schedule) VALUES "
                "(1, 'plex', 'Sagas', 0, 1, '0 4 * * *'), "
                "(2, 'plex', 'Studios', 0, NULL, NULL), "
                "(3, 'plex', 'Off', 0, NULL, NULL)"
            )
            conn.exec_driver_sql(
                "UPDATE collection_groups SET sync_enabled = 0 WHERE id = 3"
            )
            conn.exec_driver_sql(
                "INSERT INTO media_collections (id, server_type, kind, title, "
                "order_type, visible_home, visible_shared, visible_library, "
                "child_count, monitored, unsynced, deselected, group_id) VALUES "
                "(1, 'plex', 'regular', 'Saga', 'release.asc', 0, 0, 0, 0, 1, 0, "
                "0, 1)"
            )
            conn.exec_driver_sql(
                "INSERT INTO collection_rules (collection_id, smart, auto_match_art) "
                "VALUES (1, 0, 0)"
            )

            command.upgrade(config, "b4d7e2a9c815")

            assert conn.exec_driver_sql(
                "SELECT collection_auto_art, collection_drawn_style, "
                "collection_backgrounds FROM app_settings"
            ).all() == [("match", "dark", 1)]
            assert conn.exec_driver_sql(
                "SELECT name, auto_art FROM collection_groups ORDER BY id"
            ).all() == [("Sagas", "match_or_draw"), ("Studios", None), ("Off", None)]
            # The collection turned matching off and inherited its group's drawing.
            assert conn.exec_driver_sql(
                "SELECT auto_art FROM collection_rules"
            ).all() == [("draw",)]
            schedules = conn.exec_driver_sql(
                "SELECT name, cron_expression, payload FROM saved_schedules "
                "WHERE kind = 'sync' ORDER BY cron_expression"
            ).all()
            assert [(name, cron) for name, cron, _ in schedules] == [
                ("Collections (0 3 * * *)", "0 3 * * *"),
                ("Collections (0 4 * * *)", "0 4 * * *"),
            ]
            assert [
                json.loads(payload)["collection_groups"] for *_, payload in (schedules)
            ] == [["Studios", "Ungrouped"], ["Sagas"]]
            SyncScheduleConfig.model_validate(json.loads(schedules[0][2]))

            command.downgrade(config, "c9e4f1b7a2d3")
            assert conn.exec_driver_sql(
                "SELECT auto_match_art, auto_generate_art FROM collection_groups "
                "WHERE id = 1"
            ).all() == [(1, 1)]
            assert conn.exec_driver_sql(
                "SELECT collection_auto_match_art, collection_auto_generate_art "
                "FROM app_settings"
            ).all() == [(1, 0)]
    finally:
        engine.dispose()


def test_matching_becomes_overturedb_then_tmdb_and_rules_and_theme_search_appear() -> (
    None
):
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "c9e4f1b7a2d3")
            conn.exec_driver_sql(
                f"INSERT INTO app_settings ({', '.join(_SETTINGS_BEFORE_AUTO_ART)}) "  # noqa: S608 -- literal test values
                f"VALUES ({', '.join(map(str, _SETTINGS_BEFORE_AUTO_ART.values()))})"
            )
            command.upgrade(config, "b4d7e2a9c815")
            conn.exec_driver_sql(
                "INSERT INTO collection_groups (id, server_type, name, separator, "
                "auto_art) VALUES (1, 'plex', 'Sagas', 0, 'match_or_draw'), "
                "(2, 'plex', 'Studios', 0, 'draw')"
            )
            conn.exec_driver_sql(
                "UPDATE app_settings SET collection_auto_art = 'match'"
            )

            command.upgrade(config, "e8a3c5d1f702")

            assert conn.exec_driver_sql(
                "SELECT collection_auto_art, auto_search_themes FROM app_settings"
            ).all() == [("overturedb_tmdb", 1)]
            assert conn.exec_driver_sql(
                "SELECT auto_art FROM collection_groups ORDER BY id"
            ).all() == [("overturedb_tmdb_draw",), ("draw",)]
            slot_columns = {
                column["name"] for column in inspect(conn).get_columns("art_slots")
            }
            assert "generated_title_only" in slot_columns
            assert "generated_textless" not in slot_columns
            conn.exec_driver_sql(
                "INSERT INTO notification_rules VALUES ('sync', 1, 0, 'changes', 0)"
            )
            with pytest.raises(IntegrityError):
                conn.exec_driver_sql(
                    "INSERT INTO notification_rules VALUES ('backup', 1, 0, 'often', 0)"
                )
            conn.exec_driver_sql(
                "UPDATE collection_groups SET auto_art = 'tmdb_draw' WHERE id = 2"
            )

            command.downgrade(config, "b4d7e2a9c815")
            assert conn.exec_driver_sql(
                "SELECT auto_art FROM collection_groups ORDER BY id"
            ).all() == [("match_or_draw",), ("match_or_draw",)]
            assert "notification_rules" not in inspect(conn).get_table_names()
            assert "generated_textless" in {
                column["name"] for column in inspect(conn).get_columns("art_slots")
            }
    finally:
        engine.dispose()


def test_collections_start_with_their_own_posters_and_keep_consistent_ones() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "c9e4f1b7a2d3")
            conn.exec_driver_sql(
                f"INSERT INTO app_settings ({', '.join(_SETTINGS_BEFORE_AUTO_ART)}) "  # noqa: S608 -- literal test values
                f"VALUES ({', '.join(map(str, _SETTINGS_BEFORE_AUTO_ART.values()))})"
            )
            command.upgrade(config, "e8a3c5d1f702")
            conn.exec_driver_sql(
                "INSERT INTO public_dataset_collections (tmdb_id, title, no_theme) "
                "VALUES (10, 'Star Wars Collection', 0)"
            )

            command.upgrade(config, "8e103f5cf701")

            assert conn.exec_driver_sql(
                "SELECT collection_overturedb_posters FROM app_settings"
            ).all() == [("individual",)]
            for table in ("collection_groups", "collection_rules"):
                assert "overturedb_posters" in {
                    column["name"] for column in inspect(conn).get_columns(table)
                }
            assert conn.exec_driver_sql(
                "SELECT consistent_poster_url FROM public_dataset_collections"
            ).all() == [(None,)]

            command.downgrade(config, "e8a3c5d1f702")
            assert "consistent_poster_url" not in {
                column["name"]
                for column in inspect(conn).get_columns("public_dataset_collections")
            }
    finally:
        engine.dispose()


def test_the_collections_of_the_server_synced_last_are_kept() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "8e103f5cf701")
            conn.exec_driver_sql(
                "INSERT INTO collection_groups (id, server_type, name, separator) "
                "VALUES (1, 'plex', 'Sagas', 0), (2, 'jellyfin', 'Sagas', 0)"
            )
            conn.exec_driver_sql(
                "INSERT INTO media_collections (id, server_type, kind, title, "
                "order_type, visible_home, visible_shared, visible_library, "
                "child_count, monitored, unsynced, deselected, group_id, "
                "last_synced_at) VALUES "
                "(1, 'plex', 'regular', 'Old', 'release.asc', 0, 0, 0, 0, 1, 0, 0, 1, "
                "'2026-01-01 00:00:00'), "
                "(2, 'jellyfin', 'regular', 'New', 'release.asc', 0, 0, 0, 0, 1, 0, "
                "0, 2, '2026-02-01 00:00:00')"
            )
            conn.exec_driver_sql(
                "INSERT INTO collection_rules (collection_id, smart) VALUES (1, 0)"
            )

            command.upgrade(config, "b7e2c4f9a1d6")

            assert conn.exec_driver_sql(
                "SELECT id, title FROM media_collections"
            ).all() == [(2, "New")]
            assert conn.exec_driver_sql("SELECT id FROM collection_groups").all() == [
                (2,)
            ]
            assert conn.exec_driver_sql("SELECT * FROM collection_rules").all() == []
            with pytest.raises(IntegrityError):
                conn.exec_driver_sql(
                    "INSERT INTO collection_groups (name, separator) "
                    "VALUES ('Sagas', 0)"
                )

            command.downgrade(config, "8e103f5cf701")
            assert conn.exec_driver_sql(
                "SELECT server_type FROM media_collections"
            ).all() == [("plex",)]
    finally:
        engine.dispose()


def test_selections_take_the_hash_of_the_file_recorded_for_them() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "b7e2c4f9a1d6")
            conn.exec_driver_sql(
                "INSERT INTO media_items (id, media_type, title, monitored, "
                "theme_provenance_cleared, youtube_id, theme_file_hash) VALUES "
                "(1, 'movie', 'Chosen', 1, 0, 'abc', 't1'), "
                "(2, 'movie', 'Unchosen', 1, 0, NULL, 't2')"
            )
            conn.exec_driver_sql(
                "INSERT INTO art_slots (id, media_item_id, art_type, url, "
                "upload_hash, file_hash, generated_title_only) VALUES "
                "(1, 1, 'poster', 'https://images.test/p.jpg', NULL, 'p1', 0), "
                "(2, 1, 'background', NULL, NULL, 'b1', 0), "
                "(3, 2, 'poster', NULL, 'u', 'u', 0), "
                "(4, 2, 'background', 'https://images.test/b.jpg', NULL, NULL, 0)"
            )

            command.upgrade(config, "d2a7f5c3e9b1")

            assert conn.exec_driver_sql(
                "SELECT id, selection_hash FROM art_slots ORDER BY id"
            ).all() == [(1, "p1"), (2, None), (3, "u"), (4, None)]
            assert conn.exec_driver_sql(
                "SELECT id, theme_selection_hash FROM media_items ORDER BY id"
            ).all() == [(1, "t1"), (2, None)]

            command.downgrade(config, "b7e2c4f9a1d6")
            assert "selection_hash" not in {
                column["name"] for column in inspect(conn).get_columns("art_slots")
            }
            assert "theme_selection_hash" not in {
                column["name"] for column in inspect(conn).get_columns("media_items")
            }
    finally:
        engine.dispose()


def test_catalog_rows_runs_rules_and_schedule_take_the_catalog_name() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "d2a7f5c3e9b1")
            conn.exec_driver_sql(
                "INSERT INTO public_dataset_items (id, media_type, tmdb_id, "
                "no_theme) VALUES (1, 'show', 5, 0)"
            )
            conn.exec_driver_sql(
                "INSERT INTO public_dataset_seasons (id, public_dataset_item_id, "
                "season_num, poster_url) VALUES (1, 1, 1, 'https://images.test/s.jpg')"
            )
            conn.exec_driver_sql(
                "INSERT INTO public_dataset_collections (tmdb_id, title, no_theme) "
                "VALUES (10, 'Star Wars Collection', 0)"
            )
            conn.exec_driver_sql(
                "INSERT INTO public_dataset_drafts (media_type, tmdb_id, entry, "
                "updated_at) VALUES ('movie', 7, '{}', '2026-11-01 00:00:00')"
            )
            conn.exec_driver_sql(
                "INSERT INTO job_runs (id, kind, started_at, event, summary, total, "
                "log_total, cleared) VALUES ('r1', 'public_dataset_sync', "
                "'2026-11-01 00:00:00', 'public-dataset.sync.completed', '{}', "
                "0, 0, 0), "
                "('r2', 'sync', '2026-11-01 00:00:00', 'sync.completed', '{}', 0, 0, 0)"
            )
            conn.exec_driver_sql(
                "INSERT INTO notification_rules VALUES "
                "('public_dataset_sync', 1, 0, 'always', 0)"
            )
            conn.exec_driver_sql(
                "INSERT INTO task_schedule (task_name, enabled, cron_expression, "
                "payload) VALUES ('public_dataset', 1, '0 0 * * *', '{}')"
            )

            command.upgrade(config, "c9e4b1a7d385")

            assert conn.exec_driver_sql(
                "SELECT s.season_num FROM catalog_item_seasons s "
                "JOIN catalog_items i ON i.id = s.catalog_item_id"
            ).all() == [(1,)]
            assert conn.exec_driver_sql(
                "SELECT title FROM catalog_collections"
            ).all() == [("Star Wars Collection",)]
            assert conn.exec_driver_sql("SELECT tmdb_id FROM catalog_drafts").all() == [
                (7,)
            ]
            assert conn.exec_driver_sql(
                "SELECT id, kind, event FROM job_runs ORDER BY id"
            ).all() == [
                ("r1", "catalog_sync", "catalog.sync.completed"),
                ("r2", "sync", "sync.completed"),
            ]
            assert conn.exec_driver_sql(
                "SELECT kind FROM notification_rules"
            ).all() == [("catalog_sync",)]
            assert conn.exec_driver_sql(
                "SELECT task_name FROM task_schedule"
            ).all() == [("catalog",)]
            assert [
                (key["referred_table"], key["constrained_columns"], key.get("options"))
                for key in inspect(conn).get_foreign_keys("catalog_item_seasons")
            ] == [("catalog_items", ["catalog_item_id"], {"ondelete": "CASCADE"})]

            command.downgrade(config, "d2a7f5c3e9b1")
            assert {"public_dataset_items", "public_dataset_drafts"} <= set(
                inspect(conn).get_table_names()
            )
            assert conn.exec_driver_sql(
                "SELECT kind, event FROM job_runs WHERE id = 'r1'"
            ).all() == [("public_dataset_sync", "public-dataset.sync.completed")]
            assert conn.exec_driver_sql(
                "SELECT task_name FROM task_schedule"
            ).all() == [("public_dataset",)]
    finally:
        engine.dispose()


def test_automatic_art_choices_and_colours_take_the_generated_name() -> None:
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            command.upgrade(config, "c9e4f1b7a2d3")
            conn.exec_driver_sql(
                f"INSERT INTO app_settings ({', '.join(_SETTINGS_BEFORE_AUTO_ART)}) "  # noqa: S608 -- literal test values
                f"VALUES ({', '.join(map(str, _SETTINGS_BEFORE_AUTO_ART.values()))})"
            )
            command.upgrade(config, "c9e4b1a7d385")
            conn.exec_driver_sql(
                "UPDATE app_settings SET collection_auto_art = 'overturedb_tmdb_draw', "
                "collection_drawn_style = 'light'"
            )
            conn.exec_driver_sql(
                "INSERT INTO collection_groups (id, name, separator, auto_art, "
                "drawn_style) VALUES (1, 'Sagas', 0, 'draw', 'accent'), "
                "(2, 'Studios', 0, 'tmdb', NULL)"
            )

            command.upgrade(config, "f2b6d9a4c731")

            assert conn.exec_driver_sql(
                "SELECT collection_auto_art, collection_generated_style "
                "FROM app_settings"
            ).all() == [("overturedb_tmdb_generate", "light")]
            assert conn.exec_driver_sql(
                "SELECT auto_art, generated_style FROM collection_groups ORDER BY id"
            ).all() == [("generate", "accent"), ("tmdb", None)]
            with pytest.raises(IntegrityError):
                conn.exec_driver_sql("UPDATE collection_groups SET auto_art = 'draw'")

            command.downgrade(config, "c9e4b1a7d385")
            assert conn.exec_driver_sql(
                "SELECT auto_art, drawn_style FROM collection_groups ORDER BY id"
            ).all() == [("draw", "accent"), ("tmdb", None)]
            assert conn.exec_driver_sql(
                "SELECT collection_auto_art FROM app_settings"
            ).all() == [("overturedb_tmdb_draw",)]
    finally:
        engine.dispose()
