"""Remember which file holds each saved selection.

A title's artwork slots and theme record the hash of the file Overture wrote or
verified for the selection, so a file replaced outside Overture is told apart
from the selection and restored. The files on disk now are the best record of
what Overture wrote, so every selected title slot and theme with a recorded
file takes that file's hash. Collection slots record none: their art is on the
media server, not in a media folder.

Revision ID: d2a7f5c3e9b1
Revises: b7e2c4f9a1d6
Create Date: 2026-11-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "d2a7f5c3e9b1"
down_revision: str | Sequence[str] | None = "b7e2c4f9a1d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("art_slots") as batch:
        batch.add_column(sa.Column("selection_hash", auto_string(), nullable=True))
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(
            sa.Column("theme_selection_hash", auto_string(), nullable=True)
        )
    op.execute(
        "UPDATE art_slots SET selection_hash = file_hash "
        "WHERE collection_id IS NULL AND file_hash IS NOT NULL "
        "AND (url IS NOT NULL OR upload_hash IS NOT NULL)"
    )
    op.execute(
        "UPDATE media_items SET theme_selection_hash = theme_file_hash "
        "WHERE youtube_id IS NOT NULL AND theme_file_hash IS NOT NULL"
    )


def downgrade() -> None:
    """Drop the hashes; the selections and files stay as they are."""
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("theme_selection_hash")
    with op.batch_alter_table("art_slots") as batch:
        batch.drop_column("selection_hash")
