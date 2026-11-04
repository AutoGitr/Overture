"""Drop saved collection presets.

Revision ID: b3a91c4e5f27
Revises: 7fc9ce3c2813
Create Date: 2026-11-04 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "b3a91c4e5f27"
down_revision: str | Sequence[str] | None = "7fc9ce3c2813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """New collections start from Create and Split by, so presets go."""
    op.drop_table("collection_presets")


def downgrade() -> None:
    """Recreate the table empty: the dropped presets cannot be restored."""
    op.create_table(
        "collection_presets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "media_type",
            sa.Enum("movie", "show", name="mediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column("label", auto_string(), nullable=False),
        sa.Column("description", auto_string(), nullable=False),
        sa.Column("payload_json", auto_string(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_collection_presets_media_type"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_type", "label"),
    )
