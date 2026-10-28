"""Store the catalog's no-theme flag on its titles and collections.

Revision ID: c5f9d3e7b1a2
Revises: b4e8c2d6a9f1
Create Date: 2026-10-28 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c5f9d3e7b1a2"
down_revision: str | Sequence[str] | None = "b4e8c2d6a9f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("public_dataset_items", "public_dataset_collections")


def upgrade() -> None:
    """Rows imported before the flag existed come from catalogs without it."""
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    "no_theme", sa.Boolean(), nullable=False, server_default=sa.false()
                )
            )
        with op.batch_alter_table(table) as batch:
            batch.alter_column("no_theme", server_default=None)


def downgrade() -> None:
    """The next catalog sync imports the flag again."""
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("no_theme")
