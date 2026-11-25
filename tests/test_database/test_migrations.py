"""Startup creates or upgrades the schema and safely accepts repeated runs."""

lazy import json
lazy import logging
lazy import sqlite3
lazy from collections.abc import Generator
lazy from contextlib import contextmanager
lazy from functools import cache
lazy from pathlib import Path

lazy import pytest
lazy from alembic import command
lazy from alembic.config import Config
lazy from alembic.script import ScriptDirectory
lazy from sqlalchemy import insert
lazy from sqlalchemy.engine import Connection
lazy from sqlalchemy.exc import IntegrityError
lazy from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
lazy from sqlmodel import CheckConstraint, String, create_engine, inspect, text

lazy from overture.db import metadata
lazy from overture.db import session as session_module
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.session import Database, alembic_config, run_migrations
lazy from overture.domain import MediaType
lazy from overture.migrations import versions_at_head
lazy from overture.schemas.sync import SyncScheduleConfig
lazy from overture.utils.collection_formats import (
    SORT_TITLE_FORMAT_LENGTH,
    SUMMARY_FORMAT_LENGTH,
)


@cache
def _revision_snapshots() -> dict[str, bytes]:
    """Walk the Alembic chain once and snapshot the in-memory DB at each revision."""
    config = alembic_config()
    script = ScriptDirectory.from_config(config)
    revisions = [rev.revision for rev in reversed(list(script.walk_revisions()))]
    raw = sqlite3.connect(":memory:")
    engine = create_engine("sqlite://", creator=lambda: raw)
    snapshots: dict[str, bytes] = {}
    try:
        for rev in revisions:
            with engine.begin() as conn:
                config.attributes["connection"] = conn
                command.upgrade(config, rev)
            snapshots[rev] = raw.serialize()
        snapshots["head"] = snapshots[revisions[-1]]
    finally:
        engine.dispose()
    return snapshots


@contextmanager
def _at_revision(revision: str) -> Generator[tuple[Connection, Config]]:
    """Open an isolated in-memory database already migrated to *revision*."""
    snapshot = _revision_snapshots()[revision]

    def connect() -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.deserialize(snapshot)
        return conn

    engine = create_engine("sqlite://", creator=connect)
    try:
        with engine.begin() as conn:
            config = alembic_config()
            config.attributes["connection"] = conn
            yield conn, config
    finally:
        engine.dispose()


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

    async def record(revision: str) -> None:
        seen.append(revision)

    try:
        # A fresh database has no schema to upgrade, so the hook is not called.
        await database.initialize(record)
        assert seen == []

        def fake_pending(_connection: Connection) -> str:
            return "abc123"

        monkeypatch.setattr(session_module, "pending_upgrade", fake_pending)
        await database.initialize(record)
        assert seen == ["abc123"]
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
    with _at_revision("head") as (_conn, config):
        command.check(config)


def test_every_model_check_constraint_exists_at_head() -> None:
    """Autogenerate ignores CHECK constraints, so compare them by name and rule."""
    with _at_revision("head") as (conn, _config):
        inspector = inspect(conn)
        migrated = {
            (table, check["name"], check["sqltext"])
            for table in inspector.get_table_names()
            for check in inspector.get_check_constraints(table)
        }

    declared = {
        (table.name, constraint.name, str(constraint.sqltext))
        for table in metadata.tables.values()
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
    }
    assert declared == migrated


def test_stored_minutes_become_seconds_and_back() -> None:
    with _at_revision("d55c703635bb") as (conn, config):
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


def test_saved_presets_are_dropped_and_the_table_comes_back_empty() -> None:
    with _at_revision("7fc9ce3c2813") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO collection_presets (media_type, label, description, "
            "payload_json) VALUES ('movie', 'Mine', '', '{}')"
        )

        command.upgrade(config, "b3a91c4e5f27")
        assert "collection_presets" not in inspect(conn).get_table_names()

        command.downgrade(config, "7fc9ce3c2813")
        assert conn.exec_driver_sql("SELECT * FROM collection_presets").all() == []


def test_a_movies_director_becomes_the_first_of_its_directors_and_back() -> None:
    with _at_revision("b3a91c4e5f27") as (conn, config):
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
    with _at_revision("c6d2e8f41a90") as (conn, config):
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
        assert conn.exec_driver_sql("SELECT count(*) FROM art_slots").scalar_one() == 0
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
            "SELECT name, media_type FROM collection_groups ORDER BY name, media_type"
        ).all() == [
            ("Differ", "movie"),
            ("Differ (Shows)", "show"),
            ("Same", "movie"),
            ("Same", "show"),
        ]


def test_slots_select_uploads_and_lose_them_on_downgrade() -> None:
    with _at_revision("e1f4a7c92b3d") as (conn, config):
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
        assert conn.exec_driver_sql("SELECT url, upload_hash FROM art_slots").all() == [
            ("https://images.test/p.jpg", None)
        ]
        conn.exec_driver_sql(
            "INSERT INTO art_slots (id, media_item_id, art_type, upload_hash) "
            "VALUES (2, 1, 'background', 'a')"
        )
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql("UPDATE art_slots SET upload_hash = 'b' WHERE id = 1")

        command.downgrade(config, "e1f4a7c92b3d")
        assert conn.exec_driver_sql("SELECT id, url FROM art_slots").all() == [
            (1, "https://images.test/p.jpg")
        ]


def test_movies_and_shows_keep_only_their_own_fields() -> None:
    with _at_revision("f3b8d2a61c47") as (conn, config):
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
            conn.exec_driver_sql("UPDATE media_items SET edition = 'Cut' WHERE id = 2")

        command.downgrade(config, "f3b8d2a61c47")
        conn.exec_driver_sql("UPDATE media_items SET edition = 'Cut' WHERE id = 2")


def test_stored_server_links_are_dropped_and_come_back_empty() -> None:
    with _at_revision("a4d7c1e93f20") as (conn, config):
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


def test_collections_reference_group_rows_and_name_them_again_on_downgrade() -> None:
    with _at_revision("b8e3f5a0c612") as (conn, config):
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
        assert conn.exec_driver_sql("PRAGMA foreign_key_check(media_collections)").all()
        conn.exec_driver_sql(
            "INSERT INTO collection_groups (id, server_type, name, minimum_items) "
            "VALUES (7, 'plex', 'Sagas', 3)"
        )

        command.downgrade(config, "b8e3f5a0c612")
        assert conn.exec_driver_sql(
            "SELECT collection_group FROM media_collections ORDER BY id"
        ).all() == [("Sagas",), ("Studios",), ("Ungrouped",), (None,)]


def test_items_and_collections_reference_a_library_row_for_each_key() -> None:
    with _at_revision("c2f9a7d4e815") as (conn, config):
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


def test_list_columns_become_shared_terms_in_order_and_come_back() -> None:
    with _at_revision("d6a1b3c8f957") as (conn, config):
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


def test_term_links_state_their_kind_are_clustered_and_come_back() -> None:
    with _at_revision("a8d3e6f0c271") as (conn, config):
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


def test_json_columns_are_renamed_typed_and_hold_only_valid_json() -> None:
    with _at_revision("e5b2d8f1a346") as (conn, config):
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


def test_drawn_art_and_separators_are_added_and_separators_go_on_downgrade() -> None:
    with _at_revision("f7c4a9e2b158") as (conn, config):
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
        assert conn.exec_driver_sql("SELECT COUNT(*) FROM media_collections").all() == [
            (0,)
        ]


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
    with _at_revision("c9e4f1b7a2d3") as (conn, config):
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
        assert conn.exec_driver_sql("SELECT auto_art FROM collection_rules").all() == [
            ("draw",)
        ]
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


def test_matching_becomes_overturedb_then_tmdb_and_rules_and_theme_search_appear() -> (
    None
):
    with _at_revision("c9e4f1b7a2d3") as (conn, config):
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
        conn.exec_driver_sql("UPDATE app_settings SET collection_auto_art = 'match'")

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


def test_collections_start_with_their_own_posters_and_keep_consistent_ones() -> None:
    with _at_revision("c9e4f1b7a2d3") as (conn, config):
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


def test_the_collections_of_the_server_synced_last_are_kept() -> None:
    with _at_revision("8e103f5cf701") as (conn, config):
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
        assert conn.exec_driver_sql("SELECT id FROM collection_groups").all() == [(2,)]
        assert conn.exec_driver_sql("SELECT * FROM collection_rules").all() == []
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "INSERT INTO collection_groups (name, separator) VALUES ('Sagas', 0)"
            )

        command.downgrade(config, "8e103f5cf701")
        assert conn.exec_driver_sql(
            "SELECT server_type FROM media_collections"
        ).all() == [("plex",)]


def test_selections_take_the_hash_of_the_file_recorded_for_them() -> None:
    with _at_revision("b7e2c4f9a1d6") as (conn, config):
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


def test_catalog_rows_runs_rules_and_schedule_take_the_catalog_name() -> None:
    with _at_revision("d2a7f5c3e9b1") as (conn, config):
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
        assert conn.exec_driver_sql("SELECT title FROM catalog_collections").all() == [
            ("Star Wars Collection",)
        ]
        assert conn.exec_driver_sql("SELECT tmdb_id FROM catalog_drafts").all() == [
            (7,)
        ]
        assert conn.exec_driver_sql(
            "SELECT id, kind, event FROM job_runs ORDER BY id"
        ).all() == [
            ("r1", "catalog_sync", "catalog.sync.completed"),
            ("r2", "sync", "sync.completed"),
        ]
        assert conn.exec_driver_sql("SELECT kind FROM notification_rules").all() == [
            ("catalog_sync",)
        ]
        assert conn.exec_driver_sql("SELECT task_name FROM task_schedule").all() == [
            ("catalog",)
        ]
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
        assert conn.exec_driver_sql("SELECT task_name FROM task_schedule").all() == [
            ("public_dataset",)
        ]


def test_automatic_art_choices_and_colours_take_the_generated_name() -> None:
    with _at_revision("c9e4f1b7a2d3") as (conn, config):
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
            "SELECT collection_auto_art, collection_generated_style FROM app_settings"
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


_V3_COLLECTION_DRAFT = {
    "media_type": "collection",
    "title": "Saga",
    "tmdb_id": 10,
    "poster_url": "https://image.tmdb.org/t/p/original/p.jpg",
    "background_url": None,
    "youtube_id_overturedb": None,
    "youtube_id_themerrdb": None,
    "consistent_poster_url": "https://theposterdb.com/api/assets/2503",
}


def test_collection_poster_styles_split_into_individual_matte_and_overlay() -> None:
    with _at_revision("c9e4f1b7a2d3") as (conn, config):
        conn.exec_driver_sql(
            f"INSERT INTO app_settings ({', '.join(_SETTINGS_BEFORE_AUTO_ART)}) "  # noqa: S608 -- literal test values
            f"VALUES ({', '.join(map(str, _SETTINGS_BEFORE_AUTO_ART.values()))})"
        )
        command.upgrade(config, "f2b6d9a4c731")
        conn.exec_driver_sql(
            "UPDATE app_settings SET collection_overturedb_posters = 'consistent'"
        )
        conn.exec_driver_sql(
            "INSERT INTO collection_groups (id, name, separator, "
            "overturedb_posters) VALUES (1, 'Sagas', 0, 'consistent')"
        )
        conn.exec_driver_sql(
            "INSERT INTO catalog_collections (tmdb_id, title, poster_url, "
            "consistent_poster_url, no_theme) VALUES (10, 'Saga', "
            "'https://image.tmdb.org/t/p/original/p.jpg', "
            "'https://theposterdb.com/api/assets/2503', 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO catalog_drafts (media_type, tmdb_id, entry, updated_at) "
            "VALUES ('collection', 10, "
            "'" + json.dumps(_V3_COLLECTION_DRAFT) + "', '2026-08-26T12:00:00Z')"
        )

        command.upgrade(config, "a4e9c2b8f517")

        assert conn.exec_driver_sql(
            "SELECT collection_overturedb_posters FROM app_settings"
        ).all() == [("overlay",)]
        assert conn.exec_driver_sql(
            "SELECT overturedb_posters FROM collection_groups"
        ).all() == [("overlay",)]
        assert conn.exec_driver_sql(
            "SELECT poster_url_individual, poster_url_matte, poster_url_overlay "
            "FROM catalog_collections"
        ).all() == [
            (
                "https://image.tmdb.org/t/p/original/p.jpg",
                None,
                "https://theposterdb.com/api/assets/2503",
            )
        ]
        (draft_json,) = conn.exec_driver_sql("SELECT entry FROM catalog_drafts").one()
        assert json.loads(draft_json) == {
            "media_type": "collection",
            "title": "Saga",
            "tmdb_id": 10,
            "poster_url_individual": "https://image.tmdb.org/t/p/original/p.jpg",
            "poster_url_matte": None,
            "poster_url_overlay": "https://theposterdb.com/api/assets/2503",
            "background_url": None,
            "youtube_id_overturedb": None,
            "youtube_id_themerrdb": None,
        }

        command.downgrade(config, "f2b6d9a4c731")
        assert conn.exec_driver_sql(
            "SELECT collection_overturedb_posters FROM app_settings"
        ).all() == [("consistent",)]
        assert conn.exec_driver_sql(
            "SELECT poster_url, consistent_poster_url FROM catalog_collections"
        ).all() == [
            (
                "https://image.tmdb.org/t/p/original/p.jpg",
                "https://theposterdb.com/api/assets/2503",
            )
        ]
        (draft_json,) = conn.exec_driver_sql("SELECT entry FROM catalog_drafts").one()
        assert json.loads(draft_json) == _V3_COLLECTION_DRAFT


def test_collection_poster_links_take_the_style_overturedb_holds_them_as() -> None:
    with _at_revision("a4e9c2b8f517") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO catalog_collections (tmdb_id, title, "
            "poster_url_individual, poster_url_matte, no_theme) VALUES "
            "(10, 'Saga', 'https://image.tmdb.org/t/p/original/i.jpg', "
            "'https://theposterdb.com/api/assets/2503', 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO media_collections (id, title, tmdb_collection_id, kind, "
            "order_type, child_count, visible_home, visible_shared, "
            "visible_library, monitored, deselected, unsynced) VALUES "
            "(1, 'Saga', 10, 'regular', 'release.asc', 0, 0, 0, 0, 1, 0, 0), "
            "(2, 'Other', NULL, 'regular', 'release.asc', 0, 0, 0, 0, 1, 0, 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO art_slots (id, collection_id, art_type, url, "
            "generated_title_only) VALUES "
            "(1, 1, 'poster', 'https://theposterdb.com/api/assets/2503', 0), "
            "(2, 2, 'poster', 'https://image.tmdb.org/t/p/original/o.jpg', 0), "
            "(3, 1, 'background', 'https://image.tmdb.org/t/p/original/b.jpg', 0)"
        )

        command.upgrade(config, "b6f1d3a8e524")

        assert conn.exec_driver_sql(
            "SELECT id, poster_style FROM art_slots ORDER BY id"
        ).all() == [(1, "matte"), (2, "individual"), (3, None)]
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "UPDATE art_slots SET poster_style = NULL WHERE id = 1"
            )

        command.downgrade(config, "a4e9c2b8f517")
        assert "poster_style" not in {
            column["name"] for column in inspect(conn).get_columns("art_slots")
        }


def test_saved_filters_are_kept_by_media_type_and_name() -> None:
    with _at_revision("b6f1d3a8e524") as (conn, config):
        assert "saved_filters" not in inspect(conn).get_table_names()

        command.upgrade(config, "c3e7a1f9b204")
        conn.exec_driver_sql(
            "INSERT INTO saved_filters (media_type, name, criteria, created_at, "
            "updated_at) VALUES ('movie', 'Horror', '{}', '2026-11-16', "
            "'2026-11-16')"
        )
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "INSERT INTO saved_filters (media_type, name, criteria, "
                "created_at, updated_at) VALUES ('movie', 'Horror', '{}', "
                "'2026-11-16', '2026-11-16')"
            )

        command.downgrade(config, "b6f1d3a8e524")
        assert "saved_filters" not in inspect(conn).get_table_names()


def test_one_servers_titles_become_copies_of_server_one_and_back() -> None:
    with _at_revision("c3e7a1f9b204") as (conn, config):
        for statement in (
            (
                "INSERT INTO task_schedule (task_name, enabled, cron_expression, "
                "payload) VALUES ('sync_server', 0, '', "
                '\'{"last_media_server": "abc"}\')'
            ),
            (
                "INSERT INTO libraries (id, media_type, title) "
                "VALUES ('7', 'movie', 'Movies')"
            ),
            (
                "INSERT INTO media_items (id, media_type, title, server_item_id, "
                "library_id, monitored, theme_provenance_cleared, director_etag) "
                "VALUES (5, 'movie', 'Film', '100', '7', 1, 0, 'v1')"
            ),
            "INSERT INTO terms (id, kind, name) VALUES (1, 'label', 'Fav')",
            "INSERT INTO media_item_terms VALUES (5, 'label', 0, 1)",
            (
                "INSERT INTO seasons (id, media_item_id, season_num, "
                "server_item_id, file_count) VALUES (9, 5, 1, 's1', 0)"
            ),
            (
                "INSERT INTO media_collections (id, title, kind, order_type, "
                "visible_home, visible_shared, visible_library, child_count, "
                "monitored, deselected, unsynced, server_path) VALUES (3, 'Saga', "
                "'regular', 'release.asc', 0, 0, 0, 0, 1, 0, 0, '/boxsets/Saga')"
            ),
            (
                "INSERT INTO collection_libraries (collection_id, library_id, "
                "media_type, server_item_id) VALUES (3, '7', 'movie', 'c1')"
            ),
            (
                "INSERT INTO saved_schedules (id, kind, name, cron_expression, "
                "enabled, payload, state, created_at, updated_at) VALUES (1, "
                "'sync', 'Poll', '* * * * *', 1, '{\"library_ids\": [\"7\"]}', "
                "'{\"checkpoint\": \"2026-01-01T00:00:00Z\"}', '2026-01-01', "
                "'2026-01-01')"
            ),
        ):
            conn.exec_driver_sql(statement)

        command.upgrade(config, "e4b1c8f2a903")
        # No server has a place in MEDIA_SERVERS until Overture starts.
        assert conn.exec_driver_sql(
            "SELECT id, key, server_type, identity, position, "
            "removed_at IS NOT NULL FROM media_servers"
        ).all() == [(1, None, None, "abc", None, 1)]
        assert conn.exec_driver_sql(
            "SELECT media_item_id, server_id, server_item_id, library_id, "
            "labels, director_etag FROM media_item_copies"
        ).all() == [(5, 1, "100", "1:7", '["Fav"]', "v1")]
        assert conn.exec_driver_sql("SELECT * FROM season_copies").all() == [
            (9, 1, "s1")
        ]
        assert conn.exec_driver_sql(
            "SELECT library_id, server_id, server_path FROM collection_libraries"
        ).all() == [("1:7", 1, "/boxsets/Saga")]
        assert conn.exec_driver_sql(
            "SELECT payload, state FROM saved_schedules"
        ).all() == [
            (
                '{"library_ids": ["1:7"]}',
                '{"checkpoints": {"1": "2026-01-01T00:00:00Z"}}',
            )
        ]
        assert not conn.exec_driver_sql(
            "SELECT 1 FROM task_schedule WHERE task_name = 'sync_server'"
        ).all()

        command.downgrade(config, "c3e7a1f9b204")
        assert conn.exec_driver_sql(
            "SELECT server_item_id, library_id, director_etag FROM media_items"
        ).all() == [("100", "7", "v1")]
        assert conn.exec_driver_sql("SELECT server_item_id FROM seasons").all() == [
            ("s1",)
        ]
        assert conn.exec_driver_sql(
            "SELECT library_id FROM collection_libraries"
        ).all() == [("7",)]
        assert conn.exec_driver_sql(
            "SELECT server_path FROM media_collections"
        ).all() == [("/boxsets/Saga",)]
        assert conn.exec_driver_sql(
            "SELECT payload, state FROM saved_schedules"
        ).all() == [
            (
                '{"library_ids": ["7"]}',
                '{"checkpoint": "2026-01-01T00:00:00Z"}',
            )
        ]


def test_show_orders_are_admitted_and_fall_back_to_older_ones_on_downgrade() -> None:
    with _at_revision("e4b1c8f2a903") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO collection_groups (id, name, separator) "
            "VALUES (1, 'Airing', 0), (2, 'Backlog', 0)"
        )
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "UPDATE collection_groups SET order_type = 'episode_added.desc'"
            )

        command.upgrade(config, "3ae7fb38a1bb")
        conn.exec_driver_sql(
            "UPDATE collection_groups SET order_type = 'episode_added.desc' "
            "WHERE id = 1"
        )
        conn.exec_driver_sql(
            "UPDATE collection_groups SET order_type = 'unplayed_episodes.asc' "
            "WHERE id = 2"
        )

        command.downgrade(config, "e4b1c8f2a903")
        # The latest episode's date sorts by the date added; the other inherits.
        assert conn.exec_driver_sql(
            "SELECT order_type FROM collection_groups ORDER BY id"
        ).all() == [("added.desc",), (None,)]


def test_automatic_art_and_overturedb_posters_become_ordered_lists() -> None:
    with _at_revision("c9e4f1b7a2d3") as (conn, config):
        conn.exec_driver_sql(
            f"INSERT INTO app_settings ({', '.join(_SETTINGS_BEFORE_AUTO_ART)}) "  # noqa: S608 -- literal test values
            f"VALUES ({', '.join(map(str, _SETTINGS_BEFORE_AUTO_ART.values()))})"
        )
        command.upgrade(config, "3ae7fb38a1bb")
        conn.exec_driver_sql(
            "UPDATE app_settings SET collection_auto_art = "
            "'overturedb_tmdb_generate', collection_overturedb_posters = 'matte'"
        )
        conn.exec_driver_sql(
            "INSERT INTO collection_groups (id, name, separator, auto_art, "
            "overturedb_posters) VALUES (1, 'Sagas', 0, 'off', NULL), "
            "(2, 'Decades', 0, NULL, 'overlay')"
        )

        command.upgrade(config, "d5a2f8c3e916")

        assert conn.exec_driver_sql(
            "SELECT collection_auto_art, collection_overturedb_posters, "
            "collection_themes FROM app_settings"
        ).all() == [('["overturedb", "tmdb", "generate"]', '["matte"]', 1)]
        assert conn.exec_driver_sql(
            "SELECT auto_art, overturedb_posters, themes FROM collection_groups "
            "ORDER BY id"
        ).all() == [("[]", None, None), (None, '["overlay"]', None)]
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "UPDATE collection_groups SET auto_art = 'off' WHERE id = 1"
            )

        conn.exec_driver_sql(
            "UPDATE app_settings SET collection_auto_art = "
            "'[\"generate\", \"tmdb\"]', collection_overturedb_posters = '[]'"
        )
        command.downgrade(config, "3ae7fb38a1bb")
        assert conn.exec_driver_sql(
            "SELECT collection_auto_art, collection_overturedb_posters "
            "FROM app_settings"
        ).all() == [("tmdb_generate", "individual")]
        assert conn.exec_driver_sql(
            "SELECT auto_art, overturedb_posters FROM collection_groups ORDER BY id"
        ).all() == [("off", None), (None, "overlay")]


def test_saved_filters_become_one_per_name_for_movies_and_shows() -> None:
    ids = (
        '{"mode": "all", "conditions": [{"kind": "source", "operator": "is", '
        '"source": {"type": "tmdb_item", "tmdb_ids": [1]}}]}'
    )
    with _at_revision("d5a2f8c3e916") as (conn, config):
        for row_id, media_type, name, criteria in (
            (1, "movie", "Horror", '{"mode": "all"}'),
            (2, "show", "horror", '{"mode": "all"}'),
            (3, "movie", "New", '{"mode": "all"}'),
            (4, "show", "New", '{"mode": "any"}'),
            (5, "movie", "Picks", ids),
            (6, "show", "Picks", ids),
        ):
            conn.exec_driver_sql(
                "INSERT INTO saved_filters (id, media_type, name, criteria, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, '2026-11-16', "
                "'2026-11-16')",
                (row_id, media_type, name, criteria),
            )

        command.upgrade(config, "f1b8d4e6a273")

        # The same IDs name a movie and a show, so those stay apart.
        assert conn.exec_driver_sql(
            "SELECT id, name, media_type FROM saved_filters ORDER BY id"
        ).all() == [
            (1, "Horror", None),
            (3, "New", None),
            (4, "New (shows)", None),
            (5, "Picks", "movie"),
            (6, "Picks (shows)", "show"),
        ]
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "INSERT INTO saved_filters (name, criteria, created_at, "
                "updated_at) VALUES ('New', '{}', '2026-11-18', '2026-11-18')"
            )

        command.downgrade(config, "d5a2f8c3e916")
        assert conn.exec_driver_sql(
            "SELECT id, media_type FROM saved_filters ORDER BY id"
        ).all() == [
            (1, "movie"),
            (3, "movie"),
            (4, "movie"),
            (5, "movie"),
            (6, "show"),
        ]


def test_job_log_lines_keep_their_lines_and_name_no_server() -> None:
    with _at_revision("f1b8d4e6a273") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO job_runs (id, kind, started_at, event, summary, total, "
            "log_total, cleared) VALUES ('run', 'sync', '2026-11-18', "
            "'sync.completed', '{}', 0, 1, 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO job_log_lines (run_id, ordinal, outcome, entry) "
            "VALUES ('run', 0, 'Added', '{\"outcome\": \"Added\"}')"
        )

        command.upgrade(config, "a4c7e1d9b352")

        assert conn.exec_driver_sql(
            "SELECT ordinal, outcome, server FROM job_log_lines"
        ).all() == [(0, "Added", None)]

        command.downgrade(config, "f1b8d4e6a273")
        assert conn.exec_driver_sql(
            "SELECT ordinal, outcome FROM job_log_lines"
        ).all() == [(0, "Added")]


def test_fingerprints_of_an_earlier_format_are_cleared_and_current_ones_kept() -> None:
    with _at_revision("b9e2f4a7c613") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO media_items (id, media_type, title, monitored, "
            "theme_provenance_cleared) VALUES (1, 'movie', 'Alien', 1, 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO art_slots (id, media_item_id, art_type, file_hash, "
            "phash, generated_title_only) VALUES "
            "(1, 1, 'poster', 'p', ?, 0), (2, 1, 'background', 'b', ?, 0)",
            ("0" * 16, "a" * 64),
        )

        command.upgrade(config, "c4f8a2e6b913")

        assert conn.exec_driver_sql(
            "SELECT id, phash FROM art_slots ORDER BY id"
        ).all() == [(1, None), (2, "a" * 64)]

        command.downgrade(config, "b9e2f4a7c613")
        assert conn.exec_driver_sql(
            "SELECT id, phash FROM art_slots ORDER BY id"
        ).all() == [(1, None), (2, "a" * 64)]


def _collection_condition(value: str, operator: str = "is") -> dict[str, object]:
    return {
        "kind": "field",
        "field": "collection",
        "operator": operator,
        "value": value,
    }


def test_collection_conditions_name_collections_by_id_and_by_title_again() -> None:
    with _at_revision("c4f8a2e6b913") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO media_servers (id, key, title, server_type, identity, "
            "position) VALUES (1, 'plex', 'Plex', 'plex', 'plex:a', 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO libraries (id, media_type, server_id, title) VALUES "
            "('1:1', 'movie', 1, 'Movies'), ('1:2', 'movie', 1, 'Films')"
        )
        for collection_id, title in ((3, "Top"), (4, "Saga"), (5, "Saga")):
            conn.exec_driver_sql(
                "INSERT INTO media_collections (id, title, kind, order_type, "
                "visible_home, visible_shared, visible_library, child_count, "
                "monitored, deselected, unsynced, last_synced_at) VALUES "
                "(?, ?, 'regular', 'release.asc', 0, 0, 0, 0, 1, 0, 0, "
                "'2026-11-18')",
                (collection_id, title),
            )
        criteria = {
            "mode": "all",
            "conditions": [
                _collection_condition("top"),
                _collection_condition("Saga", "is_not"),
                _collection_condition("Gone"),
            ],
            "groups": [],
        }
        # A JSON column holds no criteria or generator as JSON's null.
        conn.exec_driver_sql(
            "INSERT INTO collection_groups (id, name, separator, generator) "
            "VALUES (1, 'Plain', 0, 'null')"
        )
        for part_id, collection_id, library_id, stored in (
            (1, 3, "1:1", json.dumps(criteria)),
            (2, 4, "1:1", None),
            (3, 5, "1:2", "null"),
        ):
            conn.exec_driver_sql(
                "INSERT INTO collection_libraries (id, collection_id, "
                "library_id, media_type, server_id, criteria) VALUES "
                "(?, ?, ?, 'movie', 1, ?)",
                (part_id, collection_id, library_id, stored),
            )
        conn.exec_driver_sql(
            "INSERT INTO saved_filters (id, name, criteria, created_at, "
            "updated_at) VALUES (1, 'Sagas', ?, '2026-11-18', '2026-11-18')",
            (json.dumps({"conditions": [_collection_condition("saga")]}),),
        )

        command.upgrade(config, "d7b3e9a1c524")

        [part] = conn.exec_driver_sql(
            "SELECT criteria FROM collection_libraries WHERE id = 1"
        ).one()
        # Only collection 4 named Saga is in the library.
        assert json.loads(part) == {
            "mode": "all",
            "conditions": [
                _collection_condition("3"),
                _collection_condition("4", "is_not"),
                _collection_condition("0"),
            ],
            "groups": [],
        }
        assert conn.exec_driver_sql(
            "SELECT generator FROM collection_groups"
        ).all() == [("null",)]
        assert conn.exec_driver_sql(
            "SELECT criteria FROM collection_libraries WHERE id = 3"
        ).all() == [("null",)]
        [saved] = conn.exec_driver_sql("SELECT criteria FROM saved_filters").one()
        assert json.loads(saved) == {
            "conditions": [],
            "groups": [
                {
                    "mode": "any",
                    "conditions": [
                        _collection_condition("4"),
                        _collection_condition("5"),
                    ],
                    "groups": [],
                }
            ],
        }

        command.downgrade(config, "c4f8a2e6b913")
        [part] = conn.exec_driver_sql(
            "SELECT criteria FROM collection_libraries WHERE id = 1"
        ).one()
        assert [condition["value"] for condition in json.loads(part)["conditions"]] == [
            "Top",
            "Saga",
            "0",
        ]


def test_job_log_lines_name_their_server_by_number_and_by_name_again() -> None:
    with _at_revision("d7b3e9a1c524") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO media_servers (id, key, title, server_type, identity, "
            "position) VALUES (2, 'plex', 'Plex', 'plex', 'plex:a', 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO job_runs (id, kind, started_at, event, summary, total, "
            "log_total, cleared) VALUES ('run', 'sync', '2026-11-18', "
            "'sync.completed', '{}', 0, 2, 0)"
        )
        for ordinal, server in ((0, "Plex"), (1, None)):
            conn.exec_driver_sql(
                "INSERT INTO job_log_lines (run_id, ordinal, outcome, server, "
                "entry) VALUES ('run', ?, 'Added', ?, ?)",
                (
                    ordinal,
                    server,
                    json.dumps({"outcome": "Added", "server": server}),
                ),
            )

        command.upgrade(config, "e2a6c8f4d137")

        rows = conn.exec_driver_sql(
            "SELECT ordinal, server_id, entry FROM job_log_lines ORDER BY ordinal"
        ).all()
        assert [(row[0], row[1], json.loads(row[2])) for row in rows] == [
            (0, 2, {"outcome": "Added", "server": "Plex", "server_id": 2}),
            (1, None, {"outcome": "Added", "server": None}),
        ]

        command.downgrade(config, "d7b3e9a1c524")
        rows = conn.exec_driver_sql(
            "SELECT ordinal, server, entry FROM job_log_lines ORDER BY ordinal"
        ).all()
        assert [(row[0], row[1], json.loads(row[2])) for row in rows] == [
            (0, "Plex", {"outcome": "Added", "server": "Plex"}),
            (1, None, {"outcome": "Added", "server": None}),
        ]


def test_generated_posters_show_the_group_until_a_tier_hides_it() -> None:
    with _at_revision("e2a6c8f4d137") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO collection_groups (id, name, separator) VALUES (1, 'Sagas', 0)"
        )
        settings_columns = {
            column["name"] for column in inspect(conn).get_columns("app_settings")
        }

        command.upgrade(config, "f5d1b7e3a982")

        assert conn.exec_driver_sql(
            "SELECT generated_title_only FROM collection_groups"
        ).all() == [(None,)]
        assert "collection_generated_title_only" in {
            column["name"] for column in inspect(conn).get_columns("app_settings")
        }

        command.downgrade(config, "e2a6c8f4d137")
        assert {
            column["name"] for column in inspect(conn).get_columns("app_settings")
        } == settings_columns


def test_empty_json_values_become_sql_null_and_json_null_is_refused() -> None:
    with _at_revision("f5d1b7e3a982") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO collection_groups (id, name, separator, generator, "
            "auto_art) VALUES (1, 'Plain', 0, 'null', '[\"generate\"]')"
        )

        command.upgrade(config, "a1f6c3e8d590")

        assert conn.exec_driver_sql(
            "SELECT generator, auto_art FROM collection_groups"
        ).all() == [(None, '["generate"]')]
        with pytest.raises(IntegrityError, match="ck_collection_groups_generator"):
            conn.exec_driver_sql("UPDATE collection_groups SET generator = 'null'")

        command.downgrade(config, "f5d1b7e3a982")
        conn.exec_driver_sql("UPDATE collection_groups SET generator = 'null'")


def test_stored_runs_count_targets_from_their_counters_and_back() -> None:
    with _at_revision("a1f6c3e8d590") as (conn, config):
        line = {"outcome": "No match", "target": "94 collections", "reason": "none"}
        conn.exec_driver_sql(
            "INSERT INTO job_runs (id, kind, started_at, event, summary, total, "
            "log_total, cleared) VALUES ('run', 'bulk_theme', '2026-11-20', "
            "'theme.completed', ?, 95, 3, 0), ('quiet', 'backup', '2026-11-19', "
            "'backup.completed', '{}', 0, 0, 0)",
            (
                json.dumps(
                    {
                        "done": 95,
                        "no_match": 94,
                        "skipped": 1,
                        "errors": 0,
                        "log_outcomes": {"No match": 1, "Skipped": 1, "Started": 1},
                        "log": line,
                    }
                ),
            ),
        )
        conn.exec_driver_sql(
            "INSERT INTO job_log_lines (run_id, ordinal, outcome, entry) "
            "VALUES ('run', 0, 'No match', ?)",
            (json.dumps(line),),
        )

        command.upgrade(config, "b7d2f9a4c681")

        summaries = {
            run_id: json.loads(summary)
            for run_id, summary in conn.exec_driver_sql(
                "SELECT id, summary FROM job_runs"
            ).all()
        }
        assert summaries["run"] == {
            "done": 95,
            "log_outcomes": {"No match": 1, "Skipped": 1, "Started": 1},
            "log_targets": {"No match": 94, "Skipped": 1, "Started": 1},
            "log": line,
        }
        assert summaries["quiet"] == {"log_targets": {}}

        counted = {**line, "count": 94}
        conn.exec_driver_sql(
            "UPDATE job_runs SET summary = json_set(summary, '$.log', json(?)) "
            "WHERE id = 'run'",
            (json.dumps(counted),),
        )
        conn.exec_driver_sql(
            "UPDATE job_log_lines SET entry = ?", (json.dumps(counted),)
        )
        command.downgrade(config, "a1f6c3e8d590")

        [summary] = conn.exec_driver_sql(
            "SELECT summary FROM job_runs WHERE id = 'run'"
        ).one()
        restored = json.loads(summary)
        assert {key: restored[key] for key in ("no_match", "skipped", "errors")} == {
            "no_match": 94,
            "skipped": 1,
            "errors": 0,
        }
        assert restored["log"] == line
        [entry] = conn.exec_driver_sql("SELECT entry FROM job_log_lines").one()
        assert json.loads(entry) == line


def test_slots_and_themes_become_assets_with_deliveries_and_come_back() -> None:
    with _at_revision("b7d2f9a4c681") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO media_servers (id, key, title, server_type, identity, "
            "position) VALUES (1, 'plex', 'Plex', 'plex', 'plex:a', 0), "
            "(2, 'plex2', 'Plex 2', 'plex', 'plex:b', 1)"
        )
        conn.exec_driver_sql(
            "INSERT INTO libraries (id, media_type, server_id, title) VALUES "
            "('1:1', 'movie', 1, 'Movies'), ('2:1', 'movie', 2, 'Movies 2')"
        )
        conn.exec_driver_sql(
            "INSERT INTO media_items (id, media_type, title, monitored, "
            "folder_path, youtube_id, youtube_id_source, theme_file_hash, "
            "theme_file_mtime_ns, theme_file_size, theme_selection_hash, "
            "theme_provenance_cleared) VALUES (1, 'movie', 'Alien', 1, "
            "'/movies/Alien', 'yt-alien', 'download', 'other', 5, 6, 'theme', 0), "
            "(2, 'show', 'Firefly', 1, '/shows/Firefly', NULL, NULL, 'unselected', "
            "7, 8, NULL, 0), "
            # A source the old schema kept without its video.
            "(3, 'movie', 'Heat', 1, NULL, NULL, 'download', NULL, NULL, NULL, "
            "NULL, 0)"
        )
        conn.exec_driver_sql(
            "UPDATE media_items SET theme_file_duration = 30 WHERE id = 2"
        )
        conn.exec_driver_sql(
            "INSERT INTO seasons (id, media_item_id, season_num, file_count) "
            "VALUES (1, 2, 1, 1)"
        )
        conn.exec_driver_sql(
            "INSERT INTO art_slots (id, media_item_id, art_type, url, file_hash, "
            "phash, width, height, file_mtime_ns, file_size, selection_hash, "
            "generated_title_only) VALUES (1, 1, 'poster', "
            "'https://image.tmdb.org/t/p/original/a.jpg', 'poster', ?, 1000, "
            "1500, 1, 2, 'poster', 0)",
            ("a" * 64,),
        )
        conn.exec_driver_sql(
            "INSERT INTO art_slots (id, season_id, art_type, url, file_hash, "
            "selection_hash, generated_title_only) VALUES (3, 1, 'season_poster', "
            "'https://image.tmdb.org/t/p/original/s1.jpg', 's1', 's1', 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO media_collections (id, title, kind, order_type, "
            "visible_home, visible_shared, visible_library, child_count, monitored, "
            "deselected, unsynced, last_synced_at, thumb_url, art_url, youtube_id, "
            "youtube_id_source, server_theme_id) VALUES (2, 'Saga', 'regular', "
            "'release.asc', 0, 0, 0, 0, 1, 0, 0, '2026-11-20', "
            "'http://plex/thumb/1', 'http://plex/art/1', 'yt-saga', 'themerrdb', "
            "'/theme/1')"
        )
        conn.exec_driver_sql(
            "INSERT INTO collection_libraries (id, collection_id, library_id, "
            "media_type, server_id, server_item_id) VALUES "
            "(1, 2, '1:1', 'movie', 1, 'box'), "
            "(2, 2, '2:1', 'movie', 2, 'box2')"
        )
        conn.exec_driver_sql(
            "INSERT INTO art_slots (id, collection_id, art_type, url, poster_style, "
            "file_hash, phash, width, height, file_mtime_ns, file_size, "
            "generated_title_only) VALUES (2, 2, 'poster', "
            "'https://image.tmdb.org/t/p/original/s.jpg', 'individual', 'up', ?, "
            "1000, 1500, 1, 2, 0)",
            ("b" * 64,),
        )

        command.upgrade(config, "c3e8a1f5d927")

        assets = {
            (
                "item"
                if row[0] is not None
                else "season"
                if row[1] is not None
                else "collection",
                row[0] or row[1] or row[2],
                row[3],
            ): row[4:]
            for row in conn.exec_driver_sql(
                "SELECT media_item_id, season_id, collection_id, kind, status, "
                "content_hash, duration, id FROM assets"
            )
        }
        # The poster file is the selection's; the theme file was replaced.
        assert assets[("item", 1, "poster")][:2] == ("complete", "poster")
        assert assets[("item", 1, "background")][:2] == ("missing", None)
        assert assets[("item", 1, "theme")][:2] == ("partial", "theme")
        # An unselected local theme keeps its duration on the file delivery only.
        assert assets[("item", 2, "theme")][:3] == ("partial", None, None)
        assert conn.exec_driver_sql(
            "SELECT duration FROM asset_deliveries WHERE asset_id = ?",
            (assets[("item", 2, "theme")][3],),
        ).one() == (30,)
        # Season poster migrates with its local file delivery.
        assert assets[("season", 1, "season_poster")][:2] == ("complete", "s1")
        # The uploaded poster is on the collection's copies; only lead gets ref.
        assert assets[("collection", 2, "poster")][:2] == ("complete", "up")
        # An image the server shows that Overture never chose starts the asset.
        assert assets[("collection", 2, "background")][:2] == ("partial", None)
        # A Plex theme Overture uploaded is named by its video, on every copy.
        assert assets[("collection", 2, "theme")][:2] == (
            "complete",
            "youtube:yt-saga",
        )
        assert assets[("item", 3, "theme")][:2] == ("missing", None)
        assert conn.exec_driver_sql(
            "SELECT youtube_id_source, theme_found_by FROM assets WHERE id = ?",
            (assets[("collection", 2, "theme")][3],),
        ).one() == ("download", "themerrdb")
        theme_deliveries = conn.exec_driver_sql(
            "SELECT server_id, server_item_id, channel, observed_hash, observed_ref "
            "FROM asset_deliveries WHERE asset_id = ? ORDER BY server_id",
            (assets[("collection", 2, "theme")][3],),
        ).all()
        assert theme_deliveries == [
            (1, "box", "upload", "youtube:yt-saga", "/theme/1"),
            (2, "box2", "upload", "youtube:yt-saga", None),
        ]

        command.downgrade(config, "b7d2f9a4c681")

        assert conn.exec_driver_sql(
            "SELECT art_type, url, file_hash, selection_hash FROM art_slots ORDER BY id"
        ).all() == [
            ("poster", "https://image.tmdb.org/t/p/original/a.jpg", "poster", "poster"),
            (
                "season_poster",
                "https://image.tmdb.org/t/p/original/s1.jpg",
                "s1",
                "s1",
            ),
            ("poster", "https://image.tmdb.org/t/p/original/s.jpg", "up", None),
        ]
        assert conn.exec_driver_sql(
            "SELECT id, youtube_id, theme_file_hash, theme_selection_hash "
            "FROM media_items ORDER BY id"
        ).all() == [
            (1, "yt-alien", "other", "theme"),
            (2, None, "unselected", None),
            (3, None, None, None),
        ]
        assert conn.exec_driver_sql(
            "SELECT thumb_url, art_url, youtube_id, youtube_id_source, "
            "server_theme_id FROM media_collections"
        ).one() == (
            "http://plex/thumb/1",
            "http://plex/art/1",
            "yt-saga",
            "themerrdb",
            "/theme/1",
        )


def test_assets_without_folders_or_on_other_servers_convert_and_come_back() -> None:
    with _at_revision("b7d2f9a4c681") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO media_servers (id, key, title, server_type, identity, "
            "position) VALUES (1, 'plex', 'Plex', 'plex', 'plex:a', 0), "
            "(2, 'jellyfin', 'Jellyfin', 'jellyfin', 'jf:a', 1), "
            "(3, 'emby', 'Emby', 'emby', 'emby:a', 2)"
        )
        conn.exec_driver_sql(
            "INSERT INTO libraries (id, media_type, server_id, title) VALUES "
            "('2:1', 'movie', 2, 'Movies'), ('3:1', 'movie', 3, 'Movies')"
        )
        conn.exec_driver_sql(
            "INSERT INTO media_items (id, media_type, title, monitored, "
            "theme_provenance_cleared) VALUES (1, 'movie', 'Heat', 1, 0), "
            "(2, 'movie', 'Ronin', 1, 0)"
        )
        conn.exec_driver_sql(
            "UPDATE media_items SET folder_path = '/m/Ronin' WHERE id = 2"
        )
        conn.exec_driver_sql(
            "INSERT INTO art_slots (id, media_item_id, art_type, url, "
            "generated_title_only) VALUES (1, 1, 'poster', "
            "'https://image.tmdb.org/t/p/original/h.jpg', 0)"
        )
        # A file in the folder that nothing selects.
        conn.exec_driver_sql(
            "INSERT INTO art_slots (id, media_item_id, art_type, file_hash, "
            "file_mtime_ns, file_size, generated_title_only) "
            "VALUES (2, 2, 'poster', 'found', 3, 4, 0)"
        )
        conn.exec_driver_sql(
            "INSERT INTO media_collections (id, title, kind, order_type, "
            "visible_home, visible_shared, visible_library, child_count, monitored, "
            "deselected, unsynced, thumb_url, youtube_id, youtube_id_source, "
            "theme_file_hash, theme_file_mtime_ns, theme_file_size, "
            "theme_file_duration) VALUES "
            "(1, 'Saga', 'regular', 'release.asc', 0, 0, 0, 0, 1, 0, 0, "
            "'/jf/thumb', 'yt-saga', 'overturedb', 'audio', 5, 6, 30), "
            "(2, 'Withheld', 'regular', 'release.asc', 0, 0, 0, 0, 1, 0, 0, "
            "NULL, NULL, NULL, NULL, NULL, NULL, NULL)"
        )
        conn.exec_driver_sql(
            "INSERT INTO collection_libraries (id, collection_id, library_id, "
            "media_type, server_id, server_item_id) VALUES "
            "(1, 1, '2:1', 'movie', 2, 'jf-box'), (2, 1, '3:1', 'movie', 3, 'em-box')"
        )
        conn.exec_driver_sql(
            "INSERT INTO art_slots (id, collection_id, art_type, url, poster_style, "
            "file_hash, generated_title_only) VALUES (3, 1, 'poster', "
            "'https://image.tmdb.org/t/p/original/s.jpg', 'individual', 'up', 0), "
            "(4, 2, 'poster', 'https://image.tmdb.org/t/p/original/w.jpg', "
            "'individual', 'kept', 0)"
        )

        command.upgrade(config, "c3e8a1f5d927")

        def asset(owner: str, owner_id: int, kind: str) -> tuple[object, ...]:
            return conn.exec_driver_sql(
                f"SELECT id, status, content_hash FROM assets "  # noqa: S608 -- the test's own column names
                f"WHERE {owner} = ? AND kind = ?",
                (owner_id, kind),
            ).one()

        def deliveries(asset_id: object) -> list[tuple[object, ...]]:
            return [
                tuple(row)
                for row in conn.exec_driver_sql(
                    "SELECT server_id, channel, observed_hash, observed_ref, "
                    "file_mtime_ns, duration FROM asset_deliveries "
                    "WHERE asset_id = ? ORDER BY server_id",
                    (asset_id,),
                )
            ]

        # Without a folder, the selection alone completes a title's art.
        heat = asset("media_item_id", 1, "poster")
        assert heat[1:] == ("complete", None)
        assert deliveries(heat[0]) == []
        # A file nothing selects is seen, but is no content.
        ronin = asset("media_item_id", 2, "poster")
        assert ronin[1:] == ("partial", None)
        assert deliveries(ronin[0]) == [(None, "file", "found", None, 3, None)]
        # Jellyfin is this collection's lead copy, though not the first server.
        poster = asset("collection_id", 1, "poster")
        assert poster[1:] == ("complete", "up")
        assert deliveries(poster[0]) == [
            (2, "upload", "up", "/jf/thumb", None, None),
            (3, "upload", "up", None, None, None),
        ]
        # Jellyfin keeps the theme in the collection's folder; Emby keeps none.
        theme = asset("collection_id", 1, "theme")
        assert theme[1:] == ("complete", "audio")
        assert deliveries(theme[0]) == [(2, "file", "audio", None, 5, 30)]
        # A collection without a copy is complete on its selection alone.
        assert asset("collection_id", 2, "poster")[1:] == ("complete", "kept")

        command.downgrade(config, "b7d2f9a4c681")

        assert conn.exec_driver_sql(
            "SELECT id, thumb_url, youtube_id, youtube_id_source, theme_file_hash, "
            "theme_file_mtime_ns, theme_file_duration FROM media_collections "
            "ORDER BY id"
        ).all() == [
            (1, "/jf/thumb", "yt-saga", "overturedb", "audio", 5, 30),
            (2, None, None, None, None, None, None),
        ]
        assert conn.exec_driver_sql(
            "SELECT id, url, file_hash, file_mtime_ns FROM art_slots "
            "WHERE media_item_id IS NOT NULL ORDER BY id"
        ).all() == [
            (1, "https://image.tmdb.org/t/p/original/h.jpg", None, None),
            (2, None, "found", 3),
        ]


def test_task_schedules_move_into_saved_schedules_and_back() -> None:
    with _at_revision("c3e8a1f5d927") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO task_schedule (task_name, enabled, cron_expression, "
            "payload, updated_at) VALUES "
            "('backup', 1, '0 4 * * *', '{\"retention\":{\"latest\":5}}', "
            "'2026-01-02 00:00:00.000000'), "
            "('catalog', 0, '', '{}', NULL), "
            "('value 1', 0, '', '{}', NULL)"
        )

        command.upgrade(config, "d4f9a2b6e831")

        assert "task_schedule" not in inspect(conn).get_table_names()
        rows = conn.exec_driver_sql(
            "SELECT kind, name, enabled, cron_expression, payload "
            "FROM saved_schedules ORDER BY kind"
        ).all()
        assert rows == [
            ("backup", "backup", 1, "0 4 * * *", '{"retention":{"latest":5}}'),
            ("catalog", "catalog", 0, "0 0 * * *", "{}"),
        ]

        command.downgrade(config, "c3e8a1f5d927")

        restored = conn.exec_driver_sql(
            "SELECT task_name, enabled, cron_expression, payload "
            "FROM task_schedule ORDER BY task_name"
        ).all()
        assert restored == [
            ("backup", 1, "0 4 * * *", '{"retention":{"latest":5}}'),
            ("catalog", 0, "0 0 * * *", "{}"),
        ]
        assert conn.exec_driver_sql("SELECT * FROM saved_schedules").all() == []


def test_the_global_collection_formats_widen_to_a_groups_and_back() -> None:
    def lengths(conn: Connection) -> dict[str, int | None]:
        return {
            column["name"]: column["type"].length
            if isinstance(column["type"], String)
            else 0
            for column in inspect(conn).get_columns("app_settings")
            if column["name"]
            in {"collection_sort_title_format", "collection_summary_format"}
        }

    with _at_revision("d4f9a2b6e831") as (conn, config):
        assert lengths(conn) == {
            "collection_sort_title_format": 200,
            "collection_summary_format": 2000,
        }

        command.upgrade(config, "2d3465b91d26")
        assert lengths(conn) == {
            "collection_sort_title_format": SORT_TITLE_FORMAT_LENGTH,
            "collection_summary_format": SUMMARY_FORMAT_LENGTH,
        }

        command.downgrade(config, "d4f9a2b6e831")
        assert lengths(conn) == {
            "collection_sort_title_format": 200,
            "collection_summary_format": 2000,
        }


def test_replace_existing_becomes_where_current_selection_stands_and_back() -> None:
    def payload(**fields: object) -> str:
        return json.dumps({"library_ids": ["1:movies"], **fields})

    def payloads(conn: Connection) -> list[dict[str, object]]:
        return [
            json.loads(stored)
            for (stored,) in conn.exec_driver_sql(
                "SELECT payload FROM saved_schedules ORDER BY id"
            ).all()
        ]

    art = {"art_types": ["poster"], "threshold": -1}
    with _at_revision("2d3465b91d26") as (conn, config):
        for schedule_id, kind, stored in (
            (
                1,
                "assets",
                payload(
                    overwrite_existing=False,
                    art={**art, "source_order": ["overturedb", "local_art_matching"]},
                    themes={"source_order": ["themerrdb"]},
                ),
            ),
            (
                2,
                "assets",
                payload(
                    overwrite_existing=True,
                    art=None,
                    themes={"source_order": ["overturedb", "youtube_search"]},
                ),
            ),
            (3, "sync", payload(include_collections=True)),
        ):
            conn.exec_driver_sql(
                "INSERT INTO saved_schedules (id, kind, name, cron_expression, "
                "enabled, payload, state, created_at, updated_at) VALUES "
                "(?, ?, ?, '0 3 * * *', 1, ?, '{}', '2026-01-01', '2026-01-01')",
                (schedule_id, kind, f"run {schedule_id}", stored),
            )

        command.upgrade(config, "c6e2a8f4d913")
        assert payloads(conn) == [
            {
                "library_ids": ["1:movies"],
                "art": {
                    **art,
                    "source_order": [
                        "current_selection",
                        "overturedb",
                        "local_art_matching",
                    ],
                },
                "themes": {"source_order": ["current_selection", "themerrdb"]},
            },
            {
                "library_ids": ["1:movies"],
                "art": None,
                "themes": {
                    "source_order": [
                        "overturedb",
                        "youtube_search",
                        "current_selection",
                    ]
                },
            },
            {"library_ids": ["1:movies"], "include_collections": True},
        ]
        conn.exec_driver_sql(
            "UPDATE saved_schedules SET payload = ? WHERE id = 1",
            (
                payload(
                    art={**art, "source_order": ["current_selection"]},
                    themes={"source_order": ["current_selection", "themerrdb"]},
                ),
            ),
        )

        command.downgrade(config, "2d3465b91d26")
        assert payloads(conn)[:2] == [
            {
                "library_ids": ["1:movies"],
                "art": {**art, "source_order": ["overturedb", "local_art_matching"]},
                "themes": {"source_order": ["themerrdb"]},
                "overwrite_existing": False,
            },
            {
                "library_ids": ["1:movies"],
                "art": None,
                "themes": {"source_order": ["overturedb", "youtube_search"]},
                "overwrite_existing": True,
            },
        ]


def test_resolutions_become_terms_and_the_first_comes_back() -> None:
    with _at_revision("c6e2a8f4d913") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO media_items (id, media_type, title, monitored, "
            "resolution) VALUES "
            "(1, 'movie', 'Sharp', 1, '4k'), (2, 'movie', 'Also sharp', 1, '4k'), "
            "(3, 'movie', 'Unread', 1, NULL), (4, 'show', 'Blank', 1, '')"
        )
        conn.exec_driver_sql(
            "INSERT INTO terms (id, kind, name) VALUES (1, 'genre', 'Drama')"
        )
        conn.exec_driver_sql(
            "INSERT INTO media_item_terms (media_item_id, kind, position, term_id) "
            "VALUES (1, 'genre', 0, 1)"
        )

        command.upgrade(config, "b4d7e2a9c615")
        assert conn.exec_driver_sql(
            "SELECT l.media_item_id, l.kind, l.position, t.name "
            "FROM media_item_terms AS l JOIN terms AS t ON t.id = l.term_id "
            "ORDER BY l.media_item_id, l.kind"
        ).all() == [
            (1, "genre", 0, "Drama"),
            (1, "resolution", 0, "4k"),
            (2, "resolution", 0, "4k"),
        ]
        assert conn.exec_driver_sql(
            "SELECT COUNT(*) FROM terms WHERE kind = 'resolution'"
        ).all() == [(1,)]
        assert not conn.exec_driver_sql(
            "SELECT 1 FROM sqlite_schema WHERE name = 'media_item_terms' "
            "AND sql NOT LIKE '%WITHOUT ROWID%'"
        ).all()
        # A show holds each resolution its episodes come in.
        conn.exec_driver_sql(
            "INSERT INTO terms (id, kind, name) VALUES (9, 'resolution', '720')"
        )
        conn.exec_driver_sql(
            "INSERT INTO media_item_terms (media_item_id, kind, position, term_id) "
            "VALUES (4, 'resolution', 0, 9), (4, 'resolution', 1, "
            "(SELECT id FROM terms WHERE kind = 'resolution' AND name = '4k'))"
        )

        command.downgrade(config, "c6e2a8f4d913")
        assert conn.exec_driver_sql(
            "SELECT id, resolution FROM media_items ORDER BY id"
        ).all() == [(1, "4k"), (2, "4k"), (3, None), (4, "720")]
        assert conn.exec_driver_sql(
            "SELECT kind, name FROM terms ORDER BY id"
        ).all() == [("genre", "Drama")]
        with pytest.raises(IntegrityError):
            conn.exec_driver_sql(
                "INSERT INTO terms (kind, name) VALUES ('resolution', '4k')"
            )


def test_server_copies_gain_image_versions_and_lose_them_on_downgrade() -> None:
    with _at_revision("b4d7e2a9c615") as (conn, config):
        conn.exec_driver_sql(
            "INSERT INTO media_servers (id, key, title, identity) "
            "VALUES (1, 'jelly', 'Jelly', 'jellyfin:jelly')"
        )
        conn.exec_driver_sql(
            "INSERT INTO libraries (id, media_type, title, server_id) "
            "VALUES ('1:shows', 'show', 'Shows', 1)"
        )
        conn.exec_driver_sql(
            "INSERT INTO media_items (id, media_type, title, monitored) "
            "VALUES (1, 'show', 'Show', 1)"
        )
        conn.exec_driver_sql(
            "INSERT INTO media_item_copies (media_item_id, server_id, media_type, "
            "server_item_id, library_id, labels) "
            "VALUES (1, 1, 'show', 's1', '1:shows', '[]')"
        )
        conn.exec_driver_sql(
            "INSERT INTO seasons (id, media_item_id, season_num, file_count) "
            "VALUES (10, 1, 1, 3)"
        )
        conn.exec_driver_sql(
            "INSERT INTO season_copies (season_id, server_id, server_item_id) "
            "VALUES (10, 1, 'x10')"
        )

        command.upgrade(config, "d2f8a4c6e913")
        # Only a sync knows what a server shows.
        assert conn.exec_driver_sql(
            "SELECT server_item_id, poster_version, background_version "
            "FROM media_item_copies"
        ).all() == [("s1", None, None)]
        assert conn.exec_driver_sql(
            "SELECT server_item_id, poster_version FROM season_copies"
        ).all() == [("x10", None)]

        command.downgrade(config, "b4d7e2a9c615")
        assert conn.exec_driver_sql(
            "SELECT server_item_id FROM media_item_copies"
        ).all() == [("s1",)]
        assert conn.exec_driver_sql(
            "SELECT server_item_id FROM season_copies"
        ).all() == [("x10",)]


def test_every_revision_has_a_test_here() -> None:
    """Each migration is exercised on rows as the app stores them, in this file."""
    tests = Path(__file__).read_text()
    revisions = [
        script.revision
        for script in ScriptDirectory.from_config(alembic_config()).walk_revisions()
    ]
    assert revisions
    assert [revision for revision in revisions if revision not in tests] == []
