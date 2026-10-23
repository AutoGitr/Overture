"""Synced collections, TMDB collection matches and the OvertureDB catalog view.

Revision ID: 2
Revises: 1
Create Date: 2026-10-23 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

# revision identifiers, used by Alembic.
revision: str = "2"
down_revision: str | Sequence[str] | None = "1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "media_collections",
        sa.Column("server_item_id", auto_string(), nullable=False),
        sa.Column("media_type", auto_string(length=5), nullable=False),
        sa.Column("server_type", auto_string(length=8), nullable=False),
        sa.Column("title", auto_string(), nullable=False),
        sa.Column("summary", auto_string(), nullable=True),
        sa.Column("library_id", auto_string(), nullable=True),
        sa.Column("child_count", sa.Integer(), nullable=False),
        sa.Column("thumb_url", auto_string(), nullable=True),
        sa.Column("art_url", auto_string(), nullable=True),
        sa.Column("server_link", auto_string(), nullable=True),
        sa.Column("server_path", auto_string(), nullable=True),
        sa.Column("server_added_at", sa.DateTime(), nullable=True),
        sa.Column("provider_tmdb_id", sa.Integer(), nullable=True),
        sa.Column("tmdb_collection_id", sa.Integer(), nullable=True),
        sa.Column("tmdb_match", auto_string(length=9), nullable=False),
        sa.Column("youtube_id", auto_string(), nullable=True),
        sa.Column("youtube_title", auto_string(), nullable=True),
        sa.Column("youtube_duration", sa.Integer(), nullable=True),
        sa.Column("server_theme_id", auto_string(), nullable=True),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_media_collections_media_type"
        ),
        sa.CheckConstraint(
            "server_type IN ('plex', 'jellyfin', 'emby')",
            name="ck_media_collections_server_type",
        ),
        sa.CheckConstraint(
            "tmdb_match IN ('auto', 'manual', 'unmatched')",
            name="ck_media_collections_tmdb_match",
        ),
        sa.UniqueConstraint(
            "server_item_id", "media_type", name="uq_media_collection_server_media"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("library_id", "media_type", "server_item_id", "tmdb_collection_id"):
        op.create_index(f"ix_media_collections_{column}", "media_collections", [column])
    op.create_table(
        "media_collection_members",
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("media_item_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["media_collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("collection_id", "media_item_id"),
    )
    op.create_index(
        "ix_media_collection_members_item",
        "media_collection_members",
        ["media_item_id"],
    )
    op.create_table(
        "public_dataset_collections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("title", auto_string(), nullable=False),
        sa.Column("poster_url", auto_string(), nullable=True),
        sa.Column("background_url", auto_string(), nullable=True),
        sa.Column("youtube_id_overturedb", auto_string(), nullable=True),
        sa.Column("youtube_id_themerrdb", auto_string(), nullable=True),
        sa.Column("catalog_synced_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "youtube_id_overturedb IS NULL "
            "OR youtube_id_themerrdb IS NULL "
            "OR youtube_id_overturedb != youtube_id_themerrdb",
            name="ck_public_dataset_collection_different_youtube_ids",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tmdb_id"),
    )
    op.create_table(
        "public_dataset_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_type", auto_string(length=10), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("tvdb_id", sa.Integer(), nullable=True),
        sa.Column("imdb_id", auto_string(), nullable=True),
        sa.Column("entry", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show', 'collection')",
            name="ck_public_dataset_drafts_media_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    for column in ("imdb_id", "media_type", "tmdb_id", "tvdb_id"):
        op.create_index(
            f"ix_public_dataset_drafts_{column}", "public_dataset_drafts", [column]
        )

    # Kept themes and monitor choices wait, unlisted, for the first sync to
    # adopt them by server ID, or drop them when the server no longer has them.
    op.execute(
        "INSERT INTO media_collections (server_item_id, media_type, server_type, "
        "youtube_id, youtube_title, youtube_duration, server_theme_id, monitored, "
        "created_at, updated_at, title, child_count, tmdb_match) "
        "SELECT server_item_id, media_type, server_type, youtube_id, youtube_title, "
        "youtube_duration, server_theme_id, monitored, created_at, updated_at, "
        "'', 0, 'auto' FROM collection_themes"
    )
    op.drop_index("ix_collection_themes_server_item_id", table_name="collection_themes")
    op.drop_index("ix_collection_themes_media_type", table_name="collection_themes")
    op.drop_index("ix_collection_themes_server_media", table_name="collection_themes")
    op.drop_table("collection_themes")

    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.alter_column(
            "plex_collections_enabled", new_column_name="collections_enabled"
        )
    with op.batch_alter_table("media_items") as batch_op:
        batch_op.add_column(
            sa.Column("tmdb_collection_id", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("tmdb_collection_checked_id", sa.Integer(), nullable=True)
        )
        batch_op.create_index(
            "ix_media_items_tmdb_collection_id", ["tmdb_collection_id"]
        )


def downgrade() -> None:
    """Downgrade schema.

    Collections whose theme or monitor choice was the user's go back to
    ``collection_themes``; the rest, TMDB matches and catalog drafts have no
    place in revision 1 and are dropped.
    """
    with op.batch_alter_table("media_items") as batch_op:
        batch_op.drop_index("ix_media_items_tmdb_collection_id")
        batch_op.drop_column("tmdb_collection_checked_id")
        batch_op.drop_column("tmdb_collection_id")
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.alter_column(
            "collections_enabled", new_column_name="plex_collections_enabled"
        )

    op.create_table(
        "collection_themes",
        sa.Column("server_item_id", auto_string(), nullable=False),
        sa.Column("media_type", auto_string(length=5), nullable=False),
        sa.Column("server_type", auto_string(length=8), nullable=False),
        sa.Column("youtube_id", auto_string(), nullable=True),
        sa.Column("youtube_title", auto_string(), nullable=True),
        sa.Column("youtube_duration", sa.Integer(), nullable=True),
        sa.Column("server_theme_id", auto_string(), nullable=True),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_collection_themes_media_type"
        ),
        sa.CheckConstraint(
            "server_type IN ('plex', 'jellyfin', 'emby')",
            name="ck_collection_themes_server_type",
        ),
        sa.UniqueConstraint(
            "server_item_id", "media_type", name="uq_collection_theme_server_media"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_collection_themes_server_item_id", "collection_themes", ["server_item_id"]
    )
    op.create_index(
        "ix_collection_themes_media_type", "collection_themes", ["media_type"]
    )
    op.create_index(
        "ix_collection_themes_server_media",
        "collection_themes",
        ["server_item_id", "media_type"],
    )
    op.execute(
        "INSERT INTO collection_themes (server_item_id, media_type, server_type, "
        "youtube_id, youtube_title, youtube_duration, server_theme_id, monitored, "
        "created_at, updated_at) "
        "SELECT server_item_id, media_type, server_type, youtube_id, youtube_title, "
        "youtube_duration, server_theme_id, monitored, created_at, updated_at "
        "FROM media_collections WHERE youtube_id IS NOT NULL OR NOT monitored"
    )

    op.drop_table("public_dataset_drafts")
    op.drop_table("public_dataset_collections")
    op.drop_table("media_collection_members")
    op.drop_table("media_collections")
