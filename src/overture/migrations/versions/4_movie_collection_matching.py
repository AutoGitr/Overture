"""Remove TMDB matches from show collections, which TMDB does not support.

Revision ID: 4
Revises: 3
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4"
down_revision: str | Sequence[str] | None = "3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE media_collections SET tmdb_collection_id=NULL, "
            "tmdb_match='auto' WHERE media_type='show'"
        )
    )


def downgrade() -> None:
    """Invalid matches cannot be recovered and remain cleared."""
