"""Keep custom library filters saved under a name.

Revision ID: c3e7a1f9b204
Revises: b6f1d3a8e524
Create Date: 2026-11-16 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "c3e7a1f9b204"
down_revision: str | Sequence[str] | None = "b6f1d3a8e524"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_filters",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "media_type",
            sa.Enum("movie", "show", name="mediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column("name", auto_string(), nullable=False),
        sa.Column("criteria", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_saved_filters_media_type"
        ),
        sa.CheckConstraint(
            "json_valid(criteria)", name="ck_saved_filters_criteria_json"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "media_type", "name", name="uq_saved_filters_media_type_name"
        ),
    )


def downgrade() -> None:
    op.drop_table("saved_filters")
