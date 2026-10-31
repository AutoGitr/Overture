"""Require managed collection groups.

Revision ID: afe164bdef63
Revises: e9c4a7b1d3f5
Create Date: 2026-10-30

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.utils.collection_groups import collection_group

revision: str = "afe164bdef63"
down_revision: str | Sequence[str] | None = "e9c4a7b1d3f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Give managed collections a group and remove the optional membership setting."""
    bind = op.get_bind()
    for identity, name in bind.execute(
        sa.text(
            "SELECT id, collection_group FROM media_collections WHERE id IN "
            "(SELECT collection_id FROM collection_rules)"
        )
    ):
        bind.execute(
            sa.text(
                "UPDATE media_collections SET collection_group = :name WHERE id = :id"
            ),
            {"id": identity, "name": collection_group(name)},
        )
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("collection_require_group")


def downgrade() -> None:
    """Restore the setting; assigned groups remain to preserve users' organisation."""
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "collection_require_group",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column("collection_require_group", server_default=None)
