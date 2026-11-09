"""Startup creates or upgrades the schema and safely accepts repeated runs."""

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
