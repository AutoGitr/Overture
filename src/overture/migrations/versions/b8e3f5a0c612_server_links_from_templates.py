"""Server links come from the server's link templates, not stored copies.

Revision ID: b8e3f5a0c612
Revises: a4d7c1e93f20
Create Date: 2026-11-08 12:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "b8e3f5a0c612"
down_revision: str | Sequence[str] | None = "a4d7c1e93f20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("media_items", "media_collections")


def upgrade() -> None:
    """Drop the stored links; each is the template filled in with the server ID."""
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("server_link")


def downgrade() -> None:
    """Add the columns back empty; the next library sync writes them again."""
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("server_link", auto_string(), nullable=True))
