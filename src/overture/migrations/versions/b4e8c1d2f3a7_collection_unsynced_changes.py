"""Track collection changes saved in Overture and not yet sent to the server.

Revision ID: b4e8c1d2f3a7
Revises: 7d3f2a9c4b81
Create Date: 2026-10-27 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4e8c1d2f3a7"
down_revision: str | Sequence[str] | None = "7d3f2a9c4b81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Every existing collection matches what Overture last sent the server."""
    with op.batch_alter_table("media_collections") as batch_op:
        batch_op.add_column(
            sa.Column(
                "unsynced", sa.Boolean(), nullable=False, server_default=sa.false()
            )
        )
    with op.batch_alter_table("media_collections") as batch_op:
        batch_op.alter_column(
            "unsynced", existing_type=sa.Boolean(), server_default=None
        )


def downgrade() -> None:
    """Unsent changes stay saved; only the marker that they are unsent is lost."""
    with op.batch_alter_table("media_collections") as batch_op:
        batch_op.drop_column("unsynced")
