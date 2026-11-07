"""Artwork people upload: a slot selects a link or an uploaded image.

Revision ID: f3b8d2a61c47
Revises: e1f4a7c92b3d
Create Date: 2026-11-07 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "f3b8d2a61c47"
down_revision: str | Sequence[str] | None = "e1f4a7c92b3d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the uploaded image a slot selects and an art job writes.

    Every existing selection is a link, so no row changes.
    """
    with op.batch_alter_table("art_slots") as batch:
        batch.add_column(sa.Column("upload_hash", auto_string(), nullable=True))
        batch.create_check_constraint(
            "ck_art_slots_selection", "url IS NULL OR upload_hash IS NULL"
        )
    with op.batch_alter_table("download_jobs") as batch:
        batch.add_column(sa.Column("upload_hash", auto_string(), nullable=True))


def downgrade() -> None:
    """Drop uploads; a slot selecting one keeps its file and loses the selection."""
    with op.batch_alter_table("download_jobs") as batch:
        batch.drop_column("upload_hash")
    with op.batch_alter_table("art_slots") as batch:
        batch.drop_constraint("ck_art_slots_selection", type_="check")
        batch.drop_column("upload_hash")
    op.execute("DELETE FROM art_slots WHERE url IS NULL AND file_hash IS NULL")
