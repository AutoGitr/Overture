"""Choose whether generated posters show a collection's group.

Posters Automatic art generates show the group above the title, as they did,
unless a collection, its group or the global default says otherwise.

Revision ID: f5d1b7e3a982
Revises: e2a6c8f4d137
Create Date: 2026-11-18 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f5d1b7e3a982"
down_revision: str | Sequence[str] | None = "e2a6c8f4d137"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OVERRIDES = ("collection_groups", "collection_rules")


def upgrade() -> None:
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "collection_generated_title_only",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        # The default fills the existing row; the app writes the column itself.
        batch.alter_column("collection_generated_title_only", server_default=None)
    for table in _OVERRIDES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("generated_title_only", sa.Boolean(), nullable=True)
            )


def downgrade() -> None:
    for table in _OVERRIDES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("generated_title_only")
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("collection_generated_title_only")
