"""collections overhaul

Revision ID: 9a1b2c3d4e5f
Revises: 8bfb249cdcbd
Create Date: 2026-10-25 11:25:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a1b2c3d4e5f"
down_revision: str | Sequence[str] | None = "8bfb249cdcbd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _legacy_builder_json(
    source_type: str, source_identifier: str, filter_json: str | None
) -> str:
    if source_type == "tmdb":
        return json.dumps(
            [{"type": "tmdb_collection", "collection_id": int(source_identifier)}]
        )
    if source_type == "mdblist":
        return json.dumps([{"type": "mdblist", "identifiers": [source_identifier]}])
    raw = json.loads(filter_json or "{}")
    conditions: list[dict[str, object]] = []
    if raw.get("decade") is not None:
        conditions.append(
            {"field": "decade", "operator": "is", "value": int(raw["decade"])}
        )
    if raw.get("studio"):
        conditions.append(
            {"field": "studio", "operator": "is", "value": str(raw["studio"])}
        )
    if raw.get("genre"):
        conditions.append(
            {"field": "genre", "operator": "is", "value": str(raw["genre"])}
        )
    return json.dumps(
        [
            {
                "type": "library_filter",
                "filter_group": {"mode": "all", "conditions": conditions, "groups": []},
            }
        ]
    )


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "collection_order_default",
                sa.Enum(
                    "release",
                    "alpha",
                    "custom",
                    name="collectionorder",
                    native_enum=False,
                ),
                nullable=False,
                server_default="release",
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_filtering_default",
                sa.Enum(
                    "admin",
                    "user",
                    name="collectionfiltering",
                    native_enum=False,
                ),
                nullable=False,
                server_default="admin",
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_visible_home",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_visible_shared",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_visible_library",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_summary_format",
                sqlmodel.sql.sqltypes.AutoString(length=2000),
                nullable=False,
                server_default="",
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_delete_when_inactive",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_sync_interval_hours",
                sa.Integer(),
                nullable=False,
                server_default="24",
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_sync_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch_op.create_check_constraint(
            "ck_app_settings_collection_order_default",
            "collection_order_default IN ('release', 'alpha', 'custom')",
        )
        batch_op.create_check_constraint(
            "ck_app_settings_collection_filtering_default",
            "collection_filtering_default IN ('admin', 'user')",
        )

    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.alter_column("collection_order_default", server_default=None)
        batch_op.alter_column("collection_filtering_default", server_default=None)
        batch_op.alter_column("collection_visible_home", server_default=None)
        batch_op.alter_column("collection_visible_shared", server_default=None)
        batch_op.alter_column("collection_visible_library", server_default=None)
        batch_op.alter_column("collection_summary_format", server_default=None)
        batch_op.alter_column("collection_delete_when_inactive", server_default=None)
        batch_op.alter_column("collection_sync_interval_hours", server_default=None)
        batch_op.alter_column("collection_sync_enabled", server_default=None)

    with op.batch_alter_table("collection_groups", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "order_type",
                sa.Enum(
                    "release",
                    "alpha",
                    "custom",
                    name="collectionorder",
                    native_enum=False,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_filtering",
                sa.Enum(
                    "admin",
                    "user",
                    name="collectionfiltering",
                    native_enum=False,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("visible_home", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("visible_shared", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("visible_library", sa.Boolean(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "summary_format", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "active_start_mmdd", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "active_end_mmdd", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column("delete_when_inactive", sa.Boolean(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("sync_interval_hours", sa.Integer(), nullable=True)
        )
        batch_op.add_column(sa.Column("sync_enabled", sa.Boolean(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "dynamic_tmdb_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.create_check_constraint(
            "ck_collection_groups_order_type",
            "order_type IN ('release', 'alpha', 'custom')",
        )
        batch_op.create_check_constraint(
            "ck_collection_groups_collection_filtering",
            "collection_filtering IN ('admin', 'user')",
        )

    with op.batch_alter_table("collection_rules", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "builders_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "smart_filter_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "managed_label", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_mode",
                sa.Enum(
                    "default",
                    "hide_items",
                    "show_items",
                    "hide",
                    name="collectionmode",
                    native_enum=False,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "order_type",
                sa.Enum(
                    "release",
                    "alpha",
                    "custom",
                    name="collectionorder",
                    native_enum=False,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_filtering",
                sa.Enum(
                    "admin",
                    "user",
                    name="collectionfiltering",
                    native_enum=False,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("visible_home", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("visible_shared", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("visible_library", sa.Boolean(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "sort_title_format", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "summary_format", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "active_start_mmdd", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "active_end_mmdd", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column("delete_when_inactive", sa.Boolean(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_collection_rules_collection_mode",
            "collection_mode IN ('default', 'hide_items', 'show_items', 'hide')",
        )
        batch_op.create_check_constraint(
            "ck_collection_rules_order_type",
            "order_type IN ('release', 'alpha', 'custom')",
        )
        batch_op.create_check_constraint(
            "ck_collection_rules_collection_filtering",
            "collection_filtering IN ('admin', 'user')",
        )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT id, source_type, source_identifier, filter_json "
            "FROM collection_rules WHERE builders_json IS NULL"
        )
    ).fetchall()
    for row_id, source_type, source_identifier, filter_json in rows:
        connection.execute(
            sa.text(
                "UPDATE collection_rules SET builders_json = :builders_json "
                "WHERE id = :row_id"
            ),
            {
                "row_id": row_id,
                "builders_json": _legacy_builder_json(
                    str(source_type), str(source_identifier), filter_json
                ),
            },
        )

    with op.batch_alter_table("media_collections", schema=None) as batch_op:
        batch_op.alter_column("server_item_id", nullable=True)
        batch_op.add_column(
            sa.Column(
                "kind",
                sa.Enum("regular", "smart", name="collectionkind", native_enum=False),
                nullable=False,
                server_default="regular",
            )
        )
        batch_op.add_column(
            sa.Column(
                "sort_title_format", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "summary_format", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_filtering",
                sa.Enum(
                    "admin",
                    "user",
                    name="collectionfiltering",
                    native_enum=False,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "visible_shared",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "visible_library",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(
            sa.Column(
                "active_start_mmdd", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column(
                "active_end_mmdd", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column("delete_when_inactive", sa.Boolean(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("auto_generated_tmdb_id", sa.Integer(), nullable=True)
        )
        batch_op.create_index(
            batch_op.f("ix_media_collections_auto_generated_tmdb_id"),
            ["auto_generated_tmdb_id"],
            unique=False,
        )
        batch_op.create_check_constraint(
            "ck_media_collections_kind",
            "kind IN ('regular', 'smart')",
        )
        batch_op.create_check_constraint(
            "ck_media_collections_collection_filtering",
            "collection_filtering IN ('admin', 'user')",
        )

    with op.batch_alter_table("media_collections", schema=None) as batch_op:
        batch_op.alter_column("kind", server_default=None)
        batch_op.alter_column("visible_shared", server_default=None)
        batch_op.alter_column("visible_library", server_default=None)

    with op.batch_alter_table("media_items", schema=None) as batch_op:
        for column_name in (
            "actors",
            "writers",
            "producers",
            "countries",
            "labels",
            "tags",
        ):
            batch_op.add_column(
                sa.Column(
                    column_name,
                    sa.JSON(),
                    nullable=False,
                    server_default="[]",
                )
            )
        batch_op.add_column(
            sa.Column(
                "content_rating", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(
            sa.Column("resolution", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "audio_language", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.add_column(sa.Column("rating", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("duration_minutes", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("unplayed", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("in_progress", sa.Boolean(), nullable=True))
        batch_op.add_column(
            sa.Column("release_date", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )

    with op.batch_alter_table("media_items", schema=None) as batch_op:
        for column_name in (
            "actors",
            "writers",
            "producers",
            "countries",
            "labels",
            "tags",
        ):
            batch_op.alter_column(column_name, server_default=None)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("media_items", schema=None) as batch_op:
        for column_name in (
            "release_date",
            "in_progress",
            "unplayed",
            "duration_minutes",
            "rating",
            "audio_language",
            "resolution",
            "content_rating",
            "tags",
            "labels",
            "countries",
            "producers",
            "writers",
            "actors",
        ):
            batch_op.drop_column(column_name)

    op.execute(sa.text("DELETE FROM media_collections WHERE server_item_id IS NULL"))
    with op.batch_alter_table("media_collections", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_media_collections_collection_filtering", type_="check"
        )
        batch_op.drop_constraint("ck_media_collections_kind", type_="check")
        batch_op.drop_index(batch_op.f("ix_media_collections_auto_generated_tmdb_id"))
        batch_op.drop_column("auto_generated_tmdb_id")
        batch_op.drop_column("delete_when_inactive")
        batch_op.drop_column("active_end_mmdd")
        batch_op.drop_column("active_start_mmdd")
        batch_op.drop_column("visible_library")
        batch_op.drop_column("visible_shared")
        batch_op.drop_column("collection_filtering")
        batch_op.drop_column("summary_format")
        batch_op.drop_column("sort_title_format")
        batch_op.drop_column("kind")
        batch_op.alter_column("server_item_id", nullable=False)

    with op.batch_alter_table("collection_rules", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_collection_rules_collection_filtering", type_="check"
        )
        batch_op.drop_constraint("ck_collection_rules_order_type", type_="check")
        batch_op.drop_constraint("ck_collection_rules_collection_mode", type_="check")
        batch_op.drop_column("delete_when_inactive")
        batch_op.drop_column("active_end_mmdd")
        batch_op.drop_column("active_start_mmdd")
        batch_op.drop_column("summary_format")
        batch_op.drop_column("sort_title_format")
        batch_op.drop_column("visible_library")
        batch_op.drop_column("visible_shared")
        batch_op.drop_column("visible_home")
        batch_op.drop_column("collection_filtering")
        batch_op.drop_column("order_type")
        batch_op.drop_column("collection_mode")
        batch_op.drop_column("managed_label")
        batch_op.drop_column("smart_filter_json")
        batch_op.drop_column("builders_json")

    with op.batch_alter_table("collection_groups", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_collection_groups_collection_filtering", type_="check"
        )
        batch_op.drop_constraint("ck_collection_groups_order_type", type_="check")
        batch_op.drop_column("dynamic_tmdb_json")
        batch_op.drop_column("sync_enabled")
        batch_op.drop_column("sync_interval_hours")
        batch_op.drop_column("delete_when_inactive")
        batch_op.drop_column("active_end_mmdd")
        batch_op.drop_column("active_start_mmdd")
        batch_op.drop_column("summary_format")
        batch_op.drop_column("visible_library")
        batch_op.drop_column("visible_shared")
        batch_op.drop_column("visible_home")
        batch_op.drop_column("collection_filtering")
        batch_op.drop_column("order_type")

    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.drop_constraint(
            "ck_app_settings_collection_filtering_default", type_="check"
        )
        batch_op.drop_constraint(
            "ck_app_settings_collection_order_default", type_="check"
        )
        batch_op.drop_column("collection_sync_enabled")
        batch_op.drop_column("collection_sync_interval_hours")
        batch_op.drop_column("collection_delete_when_inactive")
        batch_op.drop_column("collection_summary_format")
        batch_op.drop_column("collection_visible_library")
        batch_op.drop_column("collection_visible_shared")
        batch_op.drop_column("collection_visible_home")
        batch_op.drop_column("collection_filtering_default")
        batch_op.drop_column("collection_order_default")
