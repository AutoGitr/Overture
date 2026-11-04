"""Item sort titles, and durations in seconds.

Revision ID: 7fc9ce3c2813
Revises: d55c703635bb
Create Date: 2026-11-04 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "7fc9ce3c2813"
down_revision: str | Sequence[str] | None = "d55c703635bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add sort titles and keep durations to the second."""
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column("sort_title", auto_string(), nullable=True))
        batch.add_column(sa.Column("duration_seconds", sa.Integer(), nullable=True))
    op.execute("UPDATE media_items SET duration_seconds = duration_minutes * 60")
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("duration_minutes")


def downgrade() -> None:
    """Return durations to whole minutes and drop sort titles."""
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column("duration_minutes", sa.Integer(), nullable=True))
    op.execute("UPDATE media_items SET duration_minutes = duration_seconds / 60")
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("duration_seconds")
        batch.drop_column("sort_title")
