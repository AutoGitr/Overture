"""collection group policies

Revision ID: 8bfb249cdcbd
Revises: de75601826ea
Create Date: 2026-10-25 08:23:23.478015

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8bfb249cdcbd"
down_revision: str | Sequence[str] | None = "de75601826ea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "collection_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "server_type",
            sa.Enum("plex", "jellyfin", "emby", name="servertype", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "media_type",
            sa.Enum("movie", "show", name="mediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column[str]("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column[str](
            "sync_mode",
            sa.Enum("sync", "append", name="syncmode", native_enum=False),
            nullable=True,
        ),
        sa.Column("minimum_items", sa.Integer(), nullable=True),
        sa.Column("delete_below_minimum", sa.Boolean(), nullable=True),
        sa.Column[str](
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
        ),
        sa.Column[str](
            "sort_title_format", sqlmodel.sql.sqltypes.AutoString(), nullable=True
        ),
        sa.Column("auto_match_art", sa.Boolean(), nullable=True),
        sa.Column("auto_match_theme", sa.Boolean(), nullable=True),
        sa.CheckConstraint(
            "collection_mode IN ('default', 'hide_items', 'show_items', 'hide')",
            name="ck_collection_groups_collection_mode",
        ),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_collection_groups_media_type"
        ),
        sa.CheckConstraint(
            "server_type IN ('plex', 'jellyfin', 'emby')",
            name="ck_collection_groups_server_type",
        ),
        sa.CheckConstraint(
            "sync_mode IN ('sync', 'append')", name="ck_collection_groups_sync_mode"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_type", "media_type", "name"),
    )
    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "collection_sort_title_format",
                sqlmodel.sql.sqltypes.AutoString(length=200),
                nullable=False,
                server_default="",
            )
        )

    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.alter_column("collection_sort_title_format", server_default=None)

    with op.batch_alter_table("collection_rules", schema=None) as batch_op:
        batch_op.add_column(sa.Column("auto_match_art", sa.Boolean(), nullable=True))
        batch_op.add_column(sa.Column("auto_match_theme", sa.Boolean(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("collection_rules", schema=None) as batch_op:
        batch_op.drop_column("auto_match_theme")
        batch_op.drop_column("auto_match_art")

    with op.batch_alter_table("app_settings", schema=None) as batch_op:
        batch_op.drop_column("collection_sort_title_format")

    op.drop_table("collection_groups")
