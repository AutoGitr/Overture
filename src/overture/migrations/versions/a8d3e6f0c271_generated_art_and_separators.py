"""Art Overture draws from a title, and separators heading Plex groups.

Revision ID: a8d3e6f0c271
Revises: f7c4a9e2b158
Create Date: 2026-11-08 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a8d3e6f0c271"
down_revision: str | Sequence[str] | None = "f7c4a9e2b158"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS_BEFORE = "kind IN ('regular', 'smart')"
_KINDS = "kind IN ('regular', 'smart', 'separator')"


def _kind(*kinds: str) -> sa.Enum:
    return sa.Enum(*kinds, name="collectionkind", native_enum=False)


def upgrade() -> None:
    """Add the columns; no collection has drawn art or a separator yet."""
    with op.batch_alter_table("art_slots") as batch:
        batch.add_column(
            sa.Column(
                "generated_style",
                sa.Enum("dark", "light", "accent", name="artstyle", native_enum=False),
                nullable=True,
            )
        )
        batch.create_check_constraint(
            "ck_art_slots_generated",
            "generated_style IS NULL OR upload_hash IS NOT NULL",
        )
        batch.create_check_constraint(
            "ck_art_slots_generated_style",
            "generated_style IN ('dark', 'light', 'accent')",
        )
    for table in ("collection_rules", "collection_groups"):
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("auto_generate_art", sa.Boolean(), nullable=True)
            )
    with op.batch_alter_table("collection_groups") as batch:
        batch.add_column(
            sa.Column(
                "separator", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
    with op.batch_alter_table("collection_groups") as batch:
        batch.alter_column("separator", server_default=None)
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "collection_auto_generate_art",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column("collection_auto_generate_art", server_default=None)
    with op.batch_alter_table("media_collections") as batch:
        batch.drop_constraint("ck_media_collections_kind", type_="check")
        batch.alter_column("kind", type_=_kind("regular", "smart", "separator"))
        batch.create_check_constraint("ck_media_collections_kind", _KINDS)


def downgrade() -> None:
    """Drop separators and the drawn art's style; the drawn images stay chosen."""
    op.execute("DELETE FROM media_collections WHERE kind = 'separator'")
    with op.batch_alter_table("media_collections") as batch:
        batch.drop_constraint("ck_media_collections_kind", type_="check")
        batch.alter_column("kind", type_=_kind("regular", "smart"))
        batch.create_check_constraint("ck_media_collections_kind", _KINDS_BEFORE)
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("collection_auto_generate_art")
    with op.batch_alter_table("collection_groups") as batch:
        batch.drop_column("separator")
    for table in ("collection_rules", "collection_groups"):
        with op.batch_alter_table(table) as batch:
            batch.drop_column("auto_generate_art")
    with op.batch_alter_table("art_slots") as batch:
        batch.drop_constraint("ck_art_slots_generated_style", type_="check")
        batch.drop_constraint("ck_art_slots_generated", type_="check")
        batch.drop_column("generated_style")
