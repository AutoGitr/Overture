"""Collections that span libraries, and groups shared by movies and shows.

Revision ID: e1f4a7c92b3d
Revises: c6d2e8f41a90
Create Date: 2026-11-06 12:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "e1f4a7c92b3d"
down_revision: str | Sequence[str] | None = "c6d2e8f41a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: What a show group is renamed to when it cannot merge with a movie group.
_SHOW_GROUP_SUFFIX = " (Shows)"

#: The tables whose rows go with a collection.
_COLLECTION_CHILDREN = (
    "art_slots",
    "collection_libraries",
    "collection_rules",
    "download_jobs",
    "media_collection_members",
)

_GROUP_IDENTITY = {"id", "server_type", "media_type", "name", "generated_at"}


def _extend_schedules(connection: sa.Connection, name: str, renamed: str) -> None:
    """A schedule that named the group by name keeps running both halves of it."""
    schedules = connection.execute(
        sa.text("SELECT id, payload_json FROM saved_schedules")
    ).mappings()
    for schedule in schedules:
        payload = json.loads(schedule["payload_json"])
        groups = payload.get("collection_groups")
        if groups and name in groups:
            payload["collection_groups"] = [*groups, renamed]
            connection.execute(
                sa.text(
                    "UPDATE saved_schedules SET payload_json = :payload WHERE id = :id"
                ),
                {"payload": json.dumps(payload), "id": schedule["id"]},
            )


def _merge_groups(connection: sa.Connection) -> None:
    """Make each group name unique per server, losing no group's settings.

    Same-named movie and show groups merge unless they set a field differently,
    or both are sets; then the show group and its collections are renamed.
    """
    groups = connection.execute(
        sa.text("SELECT * FROM collection_groups ORDER BY id")
    ).mappings()
    by_name: dict[tuple[str, str], list[dict[str, object]]] = {}
    for group in groups:
        by_name.setdefault((group["server_type"], group["name"]), []).append(
            dict(group)
        )
    taken = {name for _, name in by_name}
    for (server, name), rows in by_name.items():
        if len(rows) < 2:
            continue
        kept, other = rows
        fields = set(kept) - _GROUP_IDENTITY
        conflicts = any(
            kept[field] is not None
            and other[field] is not None
            and kept[field] != other[field]
            for field in fields
        )
        if conflicts:
            renamed = f"{name}{_SHOW_GROUP_SUFFIX}"
            while renamed in taken:
                renamed += "+"
            taken.add(renamed)
            parameters = {"name": name, "new": renamed, "server": server}
            connection.execute(
                sa.text("UPDATE collection_groups SET name = :new WHERE id = :id"),
                {"new": renamed, "id": other["id"]},
            )
            _extend_schedules(connection, name, renamed)
            connection.execute(
                sa.text(
                    "UPDATE media_collections SET collection_group = :new "
                    "WHERE collection_group = :name AND server_type = :server "
                    "AND media_type = 'show'"
                ),
                parameters,
            )
            continue
        merged = {
            field: other[field]
            for field in fields
            if kept[field] is None and other[field] is not None
        }
        if merged:
            assignments = ", ".join(f"{field} = :{field}" for field in merged)
            connection.execute(
                sa.text(f"UPDATE collection_groups SET {assignments} WHERE id = :id"),  # noqa: S608 -- field names come from the table itself
                {**merged, "id": kept["id"]},
            )
        connection.execute(
            sa.text("DELETE FROM collection_groups WHERE id = :id"), {"id": other["id"]}
        )


def _delete_collections(connection: sa.Connection, ids: Sequence[int]) -> None:
    """Delete collections and what hangs off them: migrations run without cascades."""
    for collection_id in ids:
        for table in _COLLECTION_CHILDREN:
            connection.execute(
                sa.text(f"DELETE FROM {table} WHERE collection_id = :id"),  # noqa: S608 -- literal table names
                {"id": collection_id},
            )
        connection.execute(
            sa.text("DELETE FROM media_collections WHERE id = :id"),
            {"id": collection_id},
        )


def _merge_set_collections(connection: sa.Connection) -> None:
    """Make a set's per-library collections of one value a single collection.

    A value's collection now spans the set's libraries. The oldest keeps its
    art, theme and settings; the next sync folds extra Jellyfin BoxSets into one.
    """
    rows = connection.execute(
        sa.text(
            "SELECT id, server_type, collection_group, generated_value, child_count "
            "FROM media_collections WHERE generated_value IS NOT NULL ORDER BY id"
        )
    ).mappings()
    kept: dict[tuple[str, str, str], dict[str, object]] = {}
    for row in rows:
        key = (row["server_type"], row["collection_group"], row["generated_value"])
        lead = kept.setdefault(key, dict(row))
        if lead["id"] == row["id"]:
            continue
        parameters = {"lead": lead["id"], "other": row["id"]}
        connection.execute(
            sa.text(
                "UPDATE collection_libraries SET collection_id = :lead "
                "WHERE collection_id = :other"
            ),
            parameters,
        )
        connection.execute(
            sa.text(
                "UPDATE OR IGNORE media_collection_members SET collection_id = :lead "
                "WHERE collection_id = :other"
            ),
            parameters,
        )
        connection.execute(
            sa.text(
                "UPDATE media_collections SET child_count = child_count + :count "
                "WHERE id = :lead"
            ),
            {"count": row["child_count"], "lead": lead["id"]},
        )
        _delete_collections(connection, [row["id"]])


def upgrade() -> None:
    """Move each collection's library, criteria and server ID to its own table."""
    op.create_table(
        "collection_libraries",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("library_id", auto_string(), nullable=False),
        sa.Column(
            "media_type",
            sa.Enum(
                "movie",
                "show",
                name="mediatype",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("server_item_id", auto_string(), nullable=True),
        sa.Column("criteria_json", auto_string(), nullable=True),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["media_collections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_collection_libraries_media_type"
        ),
        sa.UniqueConstraint(
            "collection_id", "library_id", name="uq_collection_library"
        ),
    )
    with op.batch_alter_table("collection_libraries") as batch:
        batch.create_index("ix_collection_libraries_collection_id", ["collection_id"])
        batch.create_index("ix_collection_libraries_media_type", ["media_type"])
        batch.create_index("ix_collection_libraries_server_item_id", ["server_item_id"])

    connection = op.get_bind()
    # A library-less BoxSet has no members to list; the next sync sees it anew.
    _delete_collections(
        connection,
        connection.execute(
            sa.text(
                "SELECT id FROM media_collections WHERE library_id IS NULL "
                "AND id NOT IN (SELECT collection_id FROM collection_rules)"
            )
        )
        .scalars()
        .all(),
    )
    connection.execute(
        sa.text(
            "INSERT INTO collection_libraries "
            "(collection_id, library_id, media_type, server_item_id, criteria_json) "
            "SELECT c.id, COALESCE(c.library_id, ''), c.media_type, c.server_item_id, "
            "r.criteria_json FROM media_collections c "
            "LEFT JOIN collection_rules r ON r.collection_id = c.id"
        )
    )
    _merge_groups(connection)
    _merge_set_collections(connection)
    with op.batch_alter_table("collection_groups", recreate="always") as batch:
        batch.drop_constraint("ck_collection_groups_media_type", type_="check")
        batch.drop_column("media_type")
        batch.create_unique_constraint("uq_collection_group", ["server_type", "name"])
    with op.batch_alter_table("collection_rules", recreate="always") as batch:
        batch.drop_column("criteria_json")
    with op.batch_alter_table("media_collections", recreate="always") as batch:
        batch.drop_constraint("uq_media_collection_server_item", type_="unique")
        batch.drop_constraint("ck_media_collections_media_type", type_="check")
        batch.drop_index("ix_media_collections_server_item_id")
        batch.drop_index("ix_media_collections_media_type")
        batch.drop_index("ix_media_collections_library_id")
        batch.drop_column("server_item_id")
        batch.drop_column("media_type")
        batch.drop_column("library_id")


def downgrade() -> None:
    """Return each collection to its first library, and groups to one media type.

    The earlier schema holds one library per collection, so a collection keeps
    its first library's criteria and server copy; its other server copies stay
    on the server, for the next sync to list as unmanaged. A group is copied to
    each media type its collections hold, so every collection keeps its defaults.
    """
    with op.batch_alter_table("media_collections", recreate="always") as batch:
        batch.add_column(sa.Column("server_item_id", auto_string(), nullable=True))
        batch.add_column(
            sa.Column(
                "media_type",
                sa.Enum("movie", "show", name="mediatype", native_enum=False),
                nullable=False,
                server_default="movie",
            )
        )
        batch.add_column(sa.Column("library_id", auto_string(), nullable=True))
    with op.batch_alter_table("collection_rules", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "criteria_json", auto_string(), nullable=False, server_default="{}"
            )
        )
    with op.batch_alter_table("collection_groups", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "media_type",
                sa.Enum("movie", "show", name="mediatype", native_enum=False),
                nullable=False,
                server_default="movie",
            )
        )
        batch.drop_constraint("uq_collection_group", type_="unique")
        batch.create_unique_constraint(
            "uq_collection_group_media", ["server_type", "media_type", "name"]
        )

    def first(column: str, owner: str) -> str:
        return (
            f"(SELECT {column} FROM collection_libraries l "  # noqa: S608 -- literal names
            f"WHERE l.collection_id = {owner} ORDER BY l.id LIMIT 1)"
        )

    row = "media_collections.id"
    rule = "collection_rules.collection_id"
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE media_collections SET "  # noqa: S608 -- literal names
            f"server_item_id = {first('server_item_id', row)}, "
            f"library_id = {first('library_id', row)}, "
            f"media_type = COALESCE({first('media_type', row)}, 'movie')"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE collection_rules SET criteria_json = "  # noqa: S608 -- literal names
            f"COALESCE({first('criteria_json', rule)}, '{{}}')"
        )
    )
    columns = [
        name
        for name in sa.inspect(connection).get_columns("collection_groups")
        if name["name"] not in {"id", "media_type"}
    ]
    names = ", ".join(column["name"] for column in columns)
    connection.execute(
        sa.text(
            f"INSERT INTO collection_groups ({names}, media_type) "  # noqa: S608 -- column names come from the table itself
            f"SELECT {names}, 'show' FROM collection_groups g WHERE EXISTS ("
            "SELECT 1 FROM media_collections c WHERE c.media_type = 'show' "
            "AND c.collection_group = g.name AND c.server_type = g.server_type)"
        )
    )
    connection.execute(
        sa.text(
            "DELETE FROM collection_groups WHERE media_type = 'movie' AND EXISTS ("
            "SELECT 1 FROM collection_groups s WHERE s.media_type = 'show' "
            "AND s.name = collection_groups.name "
            "AND s.server_type = collection_groups.server_type) AND NOT EXISTS ("
            "SELECT 1 FROM media_collections c WHERE c.media_type = 'movie' "
            "AND c.collection_group = collection_groups.name "
            "AND c.server_type = collection_groups.server_type)"
        )
    )
    with op.batch_alter_table("collection_groups", recreate="always") as batch:
        batch.alter_column("media_type", server_default=None)
        batch.create_check_constraint(
            "ck_collection_groups_media_type", "media_type IN ('movie', 'show')"
        )
    with op.batch_alter_table("collection_rules", recreate="always") as batch:
        batch.alter_column("criteria_json", server_default=None)
    with op.batch_alter_table("media_collections", recreate="always") as batch:
        batch.alter_column("media_type", server_default=None)
        batch.create_check_constraint(
            "ck_media_collections_media_type", "media_type IN ('movie', 'show')"
        )
        batch.create_unique_constraint(
            "uq_media_collection_server_item", ["server_type", "server_item_id"]
        )
        batch.create_index("ix_media_collections_library_id", ["library_id"])
        batch.create_index("ix_media_collections_media_type", ["media_type"])
        batch.create_index("ix_media_collections_server_item_id", ["server_item_id"])
    op.drop_table("collection_libraries")
