"""Each server copy of a title or season records the image version it shows.

Revision ID: d2f8a4c6e913
Revises: b4d7e2a9c615
Create Date: 2026-11-24 19:00:00.000000

Only a sync reads what a server shows, so the copies hold no version until
the next one; until then Overture shows no server image for them.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f8a4c6e913"
down_revision: str | Sequence[str] | None = "b4d7e2a9c615"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    ("media_item_copies", "poster_version"),
    ("media_item_copies", "background_version"),
    ("season_copies", "poster_version"),
)


def upgrade() -> None:
    for table in dict.fromkeys(table for table, _ in _COLUMNS):
        with op.batch_alter_table(table) as batch:
            for column in (name for owner, name in _COLUMNS if owner == table):
                batch.add_column(sa.Column(column, sa.String(), nullable=True))


def downgrade() -> None:
    """The versions go; the next sync after upgrading reads them again."""
    for table in dict.fromkeys(table for table, _ in _COLUMNS):
        with op.batch_alter_table(table) as batch:
            for column in (name for owner, name in _COLUMNS if owner == table):
                batch.drop_column(column)
