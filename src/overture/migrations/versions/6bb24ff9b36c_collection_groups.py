"""Collection groups

Revision ID: 6bb24ff9b36c
Revises: ede4b777b0f9
Create Date: 2026-10-24 22:35:00.638747

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6bb24ff9b36c"
down_revision: str | Sequence[str] | None = "ede4b777b0f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("media_collections", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "collection_group", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch_op.create_index(
            batch_op.f("ix_media_collections_collection_group"),
            ["collection_group"],
            unique=False,
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("media_collections", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_media_collections_collection_group"))
        batch_op.drop_column("collection_group")
