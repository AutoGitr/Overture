"""Add the require-a-group setting; auto-advance gains a slots-only mode.

Revision ID: b4e8c2d6a9f1
Revises: a7d2e9c4f1b3
Create Date: 2026-10-28 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "b4e8c2d6a9f1"
down_revision: str | Sequence[str] | None = "a7d2e9c4f1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUTO_ADVANCE_CHECK = "ck_app_settings_auto_advance"


def upgrade() -> None:
    """Turned-on auto-advance kept moving to the next item, as slots_and_items does."""
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "collection_require_group",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "auto_advance_mode",
                sqlmodel.sql.sqltypes.AutoString(length=15),
                nullable=False,
                server_default="off",
            )
        )
    op.execute(
        "UPDATE app_settings SET auto_advance_mode = "
        "CASE WHEN auto_advance THEN 'slots_and_items' ELSE 'off' END"
    )
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column("collection_require_group", server_default=None)
        batch.drop_column("auto_advance")
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column(
            "auto_advance_mode", new_column_name="auto_advance", server_default=None
        )
        batch.create_check_constraint(
            _AUTO_ADVANCE_CHECK, "auto_advance IN ('off', 'slots', 'slots_and_items')"
        )


def downgrade() -> None:
    """Either mode that moves on becomes the old on."""
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_constraint(_AUTO_ADVANCE_CHECK, type_="check")
        batch.add_column(
            sa.Column(
                "auto_advance_flag",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    op.execute("UPDATE app_settings SET auto_advance_flag = auto_advance != 'off'")
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("auto_advance")
        batch.drop_column("collection_require_group")
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column(
            "auto_advance_flag", new_column_name="auto_advance", server_default=None
        )
