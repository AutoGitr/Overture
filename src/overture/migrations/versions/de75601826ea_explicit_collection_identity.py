"""Replace inferred collection matching with explicit TMDB identity."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "de75601826ea"
down_revision: str | Sequence[str] | None = "6bb24ff9b36c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Keep every existing TMDB ID as an explicit identity."""
    with op.batch_alter_table("media_collections") as batch_op:
        batch_op.drop_constraint("ck_media_collections_tmdb_match", type_="check")
        batch_op.drop_column("tmdb_match")


def downgrade() -> None:
    """Restore explicit choices; historical automatic votes cannot be recovered."""
    with op.batch_alter_table("media_collections") as batch_op:
        batch_op.add_column(
            sa.Column(
                "tmdb_match", sa.String(9), nullable=False, server_default="manual"
            )
        )
    op.execute(
        "UPDATE media_collections SET tmdb_match='unmatched' "
        "WHERE tmdb_collection_id IS NULL"
    )
    with op.batch_alter_table("media_collections") as batch_op:
        batch_op.alter_column("tmdb_match", server_default=None)
        batch_op.create_check_constraint(
            "ck_media_collections_tmdb_match",
            "tmdb_match IN ('auto', 'manual', 'unmatched')",
        )
