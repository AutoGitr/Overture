"""Presets added from OvertureDB are kept, and what they created names them.

Revision ID: e7c1a9b3f204
Revises: d2f8a4c6e913
Create Date: 2026-11-25 12:00:00.000000

Nothing existing came from a preset, so its new columns stay empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7c1a9b3f204"
down_revision: str | Sequence[str] | None = "d2f8a4c6e913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("media_collections", "collection_groups")


def upgrade() -> None:
    op.create_table(
        "added_presets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("file", sa.JSON(), nullable=False),
        sa.Column("added_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint(
            "json_valid(file) AND json_type(file) != 'null'",
            name="ck_added_presets_file_json",
        ),
    )
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("preset_id", sa.String(), nullable=True))
            batch.add_column(sa.Column("preset_item", sa.String(), nullable=True))


def downgrade() -> None:
    """What was added stays; only the record of where it came from goes."""
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("preset_item")
            batch.drop_column("preset_id")
    op.drop_table("added_presets")
