"""Talk to several media servers: record servers and each one's copies.

The server Overture talked to becomes server 1, and server audits, whose
findings name no server, are cleared. Its type is not stored, so
the row waits, removed, for the configured server with the identity it
recorded, or the lead server when it recorded none, to take it over when
Overture starts. Library IDs name their server from here on, in tables and in
the JSON of saved schedules and job results.

Revision ID: e4b1c8f2a903
Revises: c3e7a1f9b204
Create Date: 2026-11-16 22:11:45.304423

"""

import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import cast

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "e4b1c8f2a903"
down_revision: str | Sequence[str] | None = "c3e7a1f9b204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The number the server Overture talked to keeps.
_SERVER = 1
#: The schedule row that recorded that server's identity.
_SERVER_TASK = "sync_server"


def _scoped(key: str) -> str:
    return f"{_SERVER}:{key}"


def _unscoped(library_id: str) -> str:
    return library_id.partition(":")[2] or library_id


def _rewrite(value: object, library: Callable[[str], str]) -> object:
    """Rewrite every library ID a stored payload holds."""
    if isinstance(value, dict):
        rewritten: dict[str, object] = {}
        for key, item in cast("dict[str, object]", value).items():
            if key == "library_ids" and isinstance(item, list):
                rewritten[key] = [
                    library(entry) if isinstance(entry, str) else entry
                    for entry in cast("list[object]", item)
                ]
            elif key == "library_id" and isinstance(item, str):
                rewritten[key] = library(item)
            else:
                rewritten[key] = _rewrite(item, library)
        return rewritten
    if isinstance(value, list):
        return [_rewrite(item, library) for item in cast("list[object]", value)]
    return value


#: The JSON columns that hold library IDs, by table.
_LIBRARY_JSON = (
    ("saved_schedules", "payload"),
    ("job_results", "payload"),
    ("collection_groups", "generator"),
)


def _rewrite_json(
    column_of: str, table: str, change: Callable[[object], object]
) -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(f"SELECT rowid, {column_of} FROM {table} WHERE {column_of} IS NOT NULL")  # noqa: S608 -- names are constants
    ).all()
    for rowid, value in rows:
        stored = json.loads(value) if isinstance(value, str) else value
        rewritten = change(stored)
        if rewritten != stored:
            connection.execute(
                sa.text(
                    f"UPDATE {table} SET {column_of} = :value WHERE rowid = :rowid"  # noqa: S608 -- names are constants
                ),
                {"value": json.dumps(rewritten), "rowid": rowid},
            )


def _rewrite_payloads(library: Callable[[str], str]) -> None:
    for table, column_of in _LIBRARY_JSON:
        _rewrite_json(column_of, table, lambda value: _rewrite(value, library))


def _per_server_checkpoint(state: object) -> object:
    """Each server is polled from its own checkpoint."""
    if not isinstance(state, dict):
        return state
    fields = cast("dict[str, object]", state)
    if "checkpoint" not in fields:
        return fields
    checkpoint = fields["checkpoint"]
    return {"checkpoints": {str(_SERVER): checkpoint} if checkpoint else {}}


def _single_checkpoint(state: object) -> object:
    if not isinstance(state, dict):
        return state
    fields = cast("dict[str, dict[str, str]]", state)
    if "checkpoints" not in fields:
        return fields
    checkpoints = fields["checkpoints"]
    return {"checkpoint": min(checkpoints.values(), default=None)}


def upgrade() -> None:
    connection = op.get_bind()
    op.create_table(
        "media_servers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", auto_string(), nullable=True),
        sa.Column("title", auto_string(), nullable=False),
        sa.Column(
            "server_type",
            sa.Enum("plex", "jellyfin", "emby", name="servertype", native_enum=False),
            nullable=True,
        ),
        sa.Column("identity", auto_string(), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "server_type IN ('plex', 'jellyfin', 'emby')",
            name="ck_media_servers_server_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("media_servers") as batch_op:
        batch_op.create_index("ix_media_servers_identity", ["identity"], unique=False)
        batch_op.create_index(
            "uq_media_servers_key",
            ["key"],
            unique=True,
            sqlite_where=sa.text("key IS NOT NULL"),
        )

    recorded = connection.execute(
        sa.text("SELECT payload FROM task_schedule WHERE task_name = :name"),
        {"name": _SERVER_TASK},
    ).scalar()
    payload = cast(
        "dict[str, str | None]",
        json.loads(recorded) if isinstance(recorded, str) else recorded or {},
    )
    identity = payload.get("last_media_server") or ""
    held = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM libraries) "
            "OR EXISTS (SELECT 1 FROM collection_libraries)"
        )
    ).scalar()
    if identity or held:
        connection.execute(
            sa.text(
                "INSERT INTO media_servers (id, title, identity, removed_at) "
                "VALUES (:id, 'Media server', :identity, :now)"
            ),
            {
                "id": _SERVER,
                "identity": identity,
                # As SQLAlchemy stores a DateTime in SQLite.
                "now": datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S.%f"),
            },
        )
    connection.execute(
        sa.text("DELETE FROM task_schedule WHERE task_name = :name"),
        {"name": _SERVER_TASK},
    )

    with op.batch_alter_table("libraries") as batch_op:
        batch_op.add_column(
            sa.Column("server_id", sa.Integer(), nullable=False, server_default="1")
        )
    connection.execute(
        sa.text("UPDATE libraries SET id = :server || ':' || id"), {"server": _SERVER}
    )
    with op.batch_alter_table("libraries") as batch_op:
        batch_op.alter_column("server_id", server_default=None)
        batch_op.create_index("ix_libraries_server_id", ["server_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_libraries_server",
            "media_servers",
            ["server_id"],
            ["id"],
            ondelete="RESTRICT",
        )

    with op.batch_alter_table("collection_libraries") as batch_op:
        batch_op.add_column(
            sa.Column("server_id", sa.Integer(), nullable=False, server_default="1")
        )
        batch_op.add_column(sa.Column("server_path", auto_string(), nullable=True))
    connection.execute(
        sa.text(
            "UPDATE collection_libraries "
            "SET library_id = :server || ':' || library_id, "
            "server_path = CASE WHEN server_item_id IS NULL THEN NULL ELSE ("
            "SELECT server_path FROM media_collections AS c "
            "WHERE c.id = collection_libraries.collection_id) END"
        ),
        {"server": _SERVER},
    )
    with op.batch_alter_table("collection_libraries") as batch_op:
        batch_op.alter_column("server_id", server_default=None)
        batch_op.create_foreign_key(
            "fk_collection_libraries_server",
            "media_servers",
            ["server_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    with op.batch_alter_table("media_collections") as batch_op:
        batch_op.drop_column("server_path")

    op.create_table(
        "media_item_copies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_item_id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column(
            "media_type",
            sa.Enum("movie", "show", name="mediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column("server_item_id", auto_string(), nullable=False),
        sa.Column("library_id", auto_string(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=True),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("plays", sa.Integer(), nullable=True),
        sa.Column("last_played_at", sa.DateTime(), nullable=True),
        sa.Column("unplayed", sa.Boolean(), nullable=True),
        sa.Column("in_progress", sa.Boolean(), nullable=True),
        sa.Column("user_rating", sa.Float(), nullable=True),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("director_etag", auto_string(), nullable=True),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_media_item_copies_media_type"
        ),
        sa.CheckConstraint(
            "json_valid(labels)", name="ck_media_item_copies_labels_json"
        ),
        sa.ForeignKeyConstraint(
            ["library_id", "media_type"],
            ["libraries.id", "libraries.media_type"],
            name="fk_media_item_copies_library",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["server_id"], ["media_servers.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_item_id", "server_id", name="uq_media_item_copy"),
        sa.UniqueConstraint(
            "server_id",
            "media_type",
            "server_item_id",
            name="uq_media_item_copy_server",
        ),
    )
    with op.batch_alter_table("media_item_copies") as batch_op:
        batch_op.create_index(
            "ix_media_item_copies_library", ["library_id", "removed_at"], unique=False
        )
        batch_op.create_index(
            "ix_media_item_copies_media_item_id", ["media_item_id"], unique=False
        )
    # The labels a title holds are its server's.
    connection.execute(
        sa.text(
            "INSERT INTO media_item_copies (media_item_id, server_id, media_type, "
            "server_item_id, library_id, added_at, removed_at, verified_at, plays, "
            "last_played_at, unplayed, in_progress, user_rating, labels, "
            "director_etag) "
            "SELECT i.id, :server, i.media_type, i.server_item_id, "
            ":server || ':' || i.library_id, i.server_added_at, i.server_removed_at, "
            "i.server_verified_at, i.plays, i.last_played_at, i.unplayed, "
            "i.in_progress, i.user_rating, COALESCE((SELECT json_group_array(name) "
            "FROM (SELECT t.name AS name FROM media_item_terms AS l "
            "JOIN terms AS t ON t.id = l.term_id "
            "WHERE l.media_item_id = i.id AND l.kind = 'label' "
            "ORDER BY l.position)), '[]'), i.director_etag "
            "FROM media_items AS i "
            "WHERE i.server_item_id IS NOT NULL AND i.library_id IS NOT NULL"
        ),
        {"server": _SERVER},
    )

    op.create_table(
        "season_copies",
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("server_id", sa.Integer(), nullable=False),
        sa.Column("server_item_id", auto_string(), nullable=False),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["server_id"], ["media_servers.id"], ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("season_id", "server_id"),
    )
    connection.execute(
        sa.text(
            "INSERT INTO season_copies (season_id, server_id, server_item_id) "
            "SELECT id, :server, server_item_id FROM seasons "
            "WHERE server_item_id IS NOT NULL"
        ),
        {"server": _SERVER},
    )
    with op.batch_alter_table("seasons") as batch_op:
        batch_op.drop_column("server_item_id")

    with op.batch_alter_table("media_items") as batch_op:
        batch_op.drop_index("ix_media_items_library_id")
        batch_op.drop_index("ix_media_items_monitored_library")
        batch_op.drop_index("ix_media_items_server_identity")
        batch_op.drop_index("ix_media_items_server_item_id")
        batch_op.drop_index("ix_media_items_visible_library")
        batch_op.drop_constraint("fk_media_items_library", type_="foreignkey")
        batch_op.drop_constraint("ck_media_items_movie_fields", type_="check")
        batch_op.create_check_constraint(
            "ck_media_items_movie_fields",
            "media_type = 'movie' OR (tmdb_collection_id IS NULL AND edition IS NULL"
            " AND versions IS NULL)",
        )
        batch_op.drop_column("server_verified_at")
        batch_op.drop_column("library_id")
        batch_op.drop_column("server_item_id")
        batch_op.drop_column("director_etag")

    _rewrite_payloads(_scoped)
    _rewrite_json("state", "saved_schedules", _per_server_checkpoint)
    # Their findings name no server, so they cannot be fixed on one.
    connection.execute(
        sa.text(
            "UPDATE job_runs SET cleared = 1 "
            "WHERE kind IN ('server_audit', 'server_audit_fix')"
        )
    )


def downgrade() -> None:
    """Keep the lead copy of each title and the libraries of server 1.

    One server's facts fit the earlier schema; another server's copies,
    libraries and collection parts are let go, as a change of media server
    would.
    """
    connection = op.get_bind()
    _rewrite_payloads(_unscoped)
    _rewrite_json("state", "saved_schedules", _single_checkpoint)
    lead = (
        connection.execute(
            sa.text("SELECT MIN(id) FROM media_servers WHERE removed_at IS NULL")
        ).scalar()
        or _SERVER
    )

    with op.batch_alter_table("media_items") as batch_op:
        batch_op.add_column(sa.Column("director_etag", auto_string(), nullable=True))
        batch_op.add_column(sa.Column("server_item_id", auto_string(), nullable=True))
        batch_op.add_column(sa.Column("library_id", auto_string(), nullable=True))
        batch_op.add_column(
            sa.Column("server_verified_at", sa.DateTime(), nullable=True)
        )
        batch_op.drop_constraint("ck_media_items_movie_fields", type_="check")
        batch_op.create_check_constraint(
            "ck_media_items_movie_fields",
            "media_type = 'movie' OR (tmdb_collection_id IS NULL AND edition IS NULL"
            " AND versions IS NULL AND director_etag IS NULL)",
        )
    connection.execute(
        sa.text(
            "UPDATE media_items SET (server_item_id, library_id, server_verified_at, "
            "director_etag) = (SELECT c.server_item_id, substr(c.library_id, "
            "instr(c.library_id, ':') + 1), c.verified_at, c.director_etag "
            "FROM media_item_copies AS c WHERE c.media_item_id = media_items.id "
            "AND c.server_id = :lead)"
        ),
        {"lead": lead},
    )
    with op.batch_alter_table("media_items") as batch_op:
        batch_op.create_foreign_key(
            "fk_media_items_library",
            "libraries",
            ["library_id", "media_type"],
            ["id", "media_type"],
            ondelete="RESTRICT",
        )
        batch_op.create_index(
            "ix_media_items_visible_library",
            ["server_removed_at", "library_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_media_items_server_item_id", ["server_item_id"], unique=False
        )
        batch_op.create_index(
            "ix_media_items_server_identity",
            ["media_type", "server_item_id"],
            unique=False,
        )
        batch_op.create_index(
            "ix_media_items_monitored_library",
            ["monitored", "library_id"],
            unique=False,
        )
        batch_op.create_index("ix_media_items_library_id", ["library_id"], unique=False)

    with op.batch_alter_table("seasons") as batch_op:
        batch_op.add_column(sa.Column("server_item_id", auto_string(), nullable=True))
    connection.execute(
        sa.text(
            "UPDATE seasons SET server_item_id = (SELECT server_item_id "
            "FROM season_copies AS c WHERE c.season_id = seasons.id "
            "AND c.server_id = :lead)"
        ),
        {"lead": lead},
    )
    op.drop_table("season_copies")
    op.drop_table("media_item_copies")

    with op.batch_alter_table("media_collections") as batch_op:
        batch_op.add_column(sa.Column("server_path", auto_string(), nullable=True))
    connection.execute(
        sa.text(
            "UPDATE media_collections SET server_path = (SELECT server_path "
            "FROM collection_libraries AS p "
            "WHERE p.collection_id = media_collections.id "
            "AND p.server_id = :lead AND p.server_path IS NOT NULL "
            "ORDER BY p.id LIMIT 1)"
        ),
        {"lead": lead},
    )
    connection.execute(
        sa.text("DELETE FROM collection_libraries WHERE server_id != :lead"),
        {"lead": lead},
    )
    connection.execute(
        sa.text(
            "UPDATE collection_libraries SET library_id = "
            "substr(library_id, instr(library_id, ':') + 1)"
        )
    )
    with op.batch_alter_table("collection_libraries") as batch_op:
        batch_op.drop_constraint("fk_collection_libraries_server", type_="foreignkey")
        batch_op.drop_column("server_path")
        batch_op.drop_column("server_id")

    connection.execute(
        sa.text("DELETE FROM libraries WHERE server_id != :lead"), {"lead": lead}
    )
    connection.execute(
        sa.text("UPDATE libraries SET id = substr(id, instr(id, ':') + 1)")
    )
    with op.batch_alter_table("libraries") as batch_op:
        batch_op.drop_constraint("fk_libraries_server", type_="foreignkey")
        batch_op.drop_index("ix_libraries_server_id")
        batch_op.drop_column("server_id")

    identity = connection.execute(
        sa.text("SELECT identity FROM media_servers WHERE id = :lead"), {"lead": lead}
    ).scalar()
    if identity:
        connection.execute(
            sa.text(
                "INSERT OR REPLACE INTO task_schedule (task_name, enabled, "
                "cron_expression, payload) VALUES (:name, 0, '', :payload)"
            ),
            {
                "name": _SERVER_TASK,
                "payload": json.dumps({"last_media_server": identity}),
            },
        )
    op.drop_table("media_servers")
