"""Every director of a movie, and set collections whose value is deselected.

Revision ID: c6d2e8f41a90
Revises: b3a91c4e5f27
Create Date: 2026-11-05 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "c6d2e8f41a90"
down_revision: str | Sequence[str] | None = "b3a91c4e5f27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep the stored director as the first of a list, and add the set flag.

    Clearing the director Etag makes the next sync read every director of
    movies whose listing omits them (Jellyfin and Emby).
    """
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(
            sa.Column("directors", sa.JSON(), nullable=False, server_default="[]")
        )
    op.execute(
        "UPDATE media_items SET directors = json_array(director), "
        "director_etag = NULL WHERE director IS NOT NULL"
    )
    with op.batch_alter_table("media_items") as batch:
        batch.alter_column("directors", server_default=None)
        batch.drop_column("director")
    with op.batch_alter_table("media_collections") as batch:
        batch.add_column(
            sa.Column(
                "deselected",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    with op.batch_alter_table("media_collections") as batch:
        batch.alter_column("deselected", server_default=None)


def downgrade() -> None:
    """Keep each movie's first director and drop the set flag."""
    with op.batch_alter_table("media_collections") as batch:
        batch.drop_column("deselected")
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column("director", auto_string(), nullable=True))
    op.execute("UPDATE media_items SET director = json_extract(directors, '$[0]')")
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("directors")
