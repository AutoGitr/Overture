"""Collection management and artwork

Revision ID: 5
Revises: 4
Create Date: 2026-10-24 19:42:01.836320

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ede4b777b0f9"
down_revision: str | Sequence[str] | None = "4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""

    op.create_table(
        "collection_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column[str](
            "source_type",
            sa.Enum(
                "mdblist", "tmdb", "filter", name="rulesourcetype", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column[str](
            "source_identifier", sqlmodel.sql.sqltypes.AutoString(), nullable=False
        ),
        sa.Column[str](
            "filter_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column(
            "sync_mode",
            sa.Enum("sync", "append", name="syncmode", native_enum=False),
            nullable=True,
        ),
        sa.Column("minimum_items", sa.Integer(), nullable=True),
        sa.Column("delete_below_minimum", sa.Boolean(), nullable=True),
        sa.Column("sync_interval_hours", sa.Integer(), nullable=False),
        sa.Column("last_synced_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.Column[str]("last_error", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "source_type IN ('mdblist', 'tmdb', 'filter')",
            name="ck_collection_rules_source_type",
        ),
        sa.CheckConstraint(
            "sync_mode IN ('sync', 'append')", name="ck_collection_rules_sync_mode"
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["media_collections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("collection_rules", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_collection_rules_collection_id"),
            ["collection_id"],
            unique=True,
        )

    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "collection_sync_mode",
                sa.Enum("sync", "append", name="syncmode", native_enum=False),
                nullable=False,
                server_default=sa.text("'sync'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_mode_default",
                sa.Enum(
                    "default",
                    "hide_items",
                    "show_items",
                    "hide",
                    name="collectionmode",
                    native_enum=False,
                ),
                nullable=False,
                server_default=sa.text("'default'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_minimum_items",
                sa.Integer(),
                nullable=False,
                server_default=sa.text("1"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_delete_below_minimum",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_auto_match_art",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "collection_auto_match_theme",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )

    with op.batch_alter_table("art_slots", schema=None) as batch_op:
        batch_op.add_column(sa.Column("collection_id", sa.Integer(), nullable=True))
        batch_op.create_index(
            batch_op.f("ix_art_slots_collection_id"), ["collection_id"], unique=False
        )
        batch_op.create_unique_constraint(
            "uq_art_slots_collection", ["collection_id", "art_type"]
        )
        batch_op.create_foreign_key(
            "fk_art_slots_collection",
            "media_collections",
            ["collection_id"],
            ["id"],
            ondelete="CASCADE",
        )

    with op.batch_alter_table("media_collection_members", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "position", sa.Integer(), nullable=False, server_default=sa.text("0")
            )
        )

    with op.batch_alter_table("media_collections", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("sort_title", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
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
                nullable=False,
                server_default=sa.text("'release'"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "visible_home",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )

    with op.batch_alter_table("media_items", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "genres", sa.JSON(), nullable=False, server_default=sa.text("'[]'")
            )
        )

    for table, fields in {
        "app_settings": (
            "collection_sync_mode",
            "collection_mode_default",
            "collection_minimum_items",
            "collection_delete_below_minimum",
            "collection_auto_match_art",
            "collection_auto_match_theme",
        ),
        "media_collection_members": ("position",),
        "media_collections": ("order_type", "visible_home"),
        "media_items": ("genres",),
    }.items():
        with op.batch_alter_table(table) as batch_op:
            for field in fields:
                batch_op.alter_column(field, server_default=None)
    for table, checks in {
        "app_settings": {
            "collection_sync_mode": "'sync', 'append'",
            "collection_mode_default": "'default', 'hide_items', 'show_items', 'hide'",
        },
        "media_collections": {
            "collection_mode": "'default', 'hide_items', 'show_items', 'hide'",
            "order_type": "'release', 'alpha', 'custom'",
        },
    }.items():
        with op.batch_alter_table(table) as batch_op:
            for field, values in checks.items():
                batch_op.create_check_constraint(
                    f"ck_{table}_{field}", f"{field} IN ({values})"
                )
    with op.batch_alter_table("art_slots") as batch_op:
        batch_op.create_check_constraint(
            "ck_art_slots_owner",
            "(media_item_id IS NOT NULL) + (season_id IS NOT NULL) "
            "+ (collection_id IS NOT NULL) = 1",
        )


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DELETE FROM art_slots WHERE collection_id IS NOT NULL")
    with op.batch_alter_table("art_slots") as batch_op:
        batch_op.drop_constraint("ck_art_slots_owner", type_="check")
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.drop_constraint("ck_app_settings_collection_sync_mode", type_="check")
        batch_op.drop_constraint(
            "ck_app_settings_collection_mode_default", type_="check"
        )
    with op.batch_alter_table("media_collections") as batch_op:
        batch_op.drop_constraint("ck_media_collections_collection_mode", type_="check")
        batch_op.drop_constraint("ck_media_collections_order_type", type_="check")
    with op.batch_alter_table("media_items", schema=None) as batch_op:
        batch_op.drop_column("genres")

    with op.batch_alter_table("media_collections", schema=None) as batch_op:
        batch_op.drop_column("visible_home")
        batch_op.drop_column("order_type")
        batch_op.drop_column("collection_mode")
        batch_op.drop_column("sort_title")

    with op.batch_alter_table("media_collection_members", schema=None) as batch_op:
        batch_op.drop_column("position")

    with op.batch_alter_table("art_slots", schema=None) as batch_op:
        batch_op.drop_constraint("fk_art_slots_collection", type_="foreignkey")
        batch_op.drop_constraint("uq_art_slots_collection", type_="unique")
        batch_op.drop_index(batch_op.f("ix_art_slots_collection_id"))
        batch_op.drop_column("collection_id")

    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.drop_column("collection_auto_match_theme")
        batch_op.drop_column("collection_auto_match_art")
        batch_op.drop_column("collection_delete_below_minimum")
        batch_op.drop_column("collection_minimum_items")
        batch_op.drop_column("collection_mode_default")
        batch_op.drop_column("collection_sync_mode")

    with op.batch_alter_table("collection_rules", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_collection_rules_collection_id"))

    op.drop_table("collection_rules")
