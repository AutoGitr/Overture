"""A collection or set saved from an OvertureDB preset keeps the item it came from.

Revision ID: b9d4f2a7e135
Revises: a7e3c5f9b241
Create Date: 2026-11-27 13:00:00.000000

Nothing saved before came from a tracked preset, so the table starts empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9d4f2a7e135"
down_revision: str | Sequence[str] | None = "a7e3c5f9b241"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "preset_uses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("preset_id", sa.String(), nullable=False),
        sa.Column("item", sa.String(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["media_collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["collection_groups.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("collection_id"),
        sa.UniqueConstraint("group_id"),
        sa.CheckConstraint(
            "(collection_id IS NOT NULL) + (group_id IS NOT NULL) = 1",
            name="ck_preset_uses_owner",
        ),
        sa.CheckConstraint(
            "json_valid(definition) AND json_type(definition) != 'null'",
            name="ck_preset_uses_definition_json",
        ),
    )


def downgrade() -> None:
    """What was saved stays; only the record of its preset goes."""
    op.drop_table("preset_uses")
