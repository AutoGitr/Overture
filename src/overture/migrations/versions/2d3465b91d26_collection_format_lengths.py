"""Let the global collection formats be as long as a group's or collection's.

Revision ID: 2d3465b91d26
Revises: d4f9a2b6e831
Create Date: 2026-11-22 02:35:09.024722

The settings held the sort title and summary formats a group or collection
inherits to 200 and 2,000 characters, below the 400 and 20,000 the same
formats may be where they are set. Widening the columns keeps every value.
"""

from collections.abc import Sequence

from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "2d3465b91d26"
down_revision: str | Sequence[str] | None = "d4f9a2b6e831"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Each column, with its length before and after.
_LENGTHS = {
    "collection_sort_title_format": (200, 400),
    "collection_summary_format": (2000, 20000),
}


def _resize(*, upgrade: bool) -> None:
    with op.batch_alter_table("app_settings") as batch:
        for column, (before, after) in _LENGTHS.items():
            old, new = (before, after) if upgrade else (after, before)
            batch.alter_column(
                column,
                existing_type=auto_string(length=old),
                type_=auto_string(length=new),
                existing_nullable=False,
            )


def upgrade() -> None:
    _resize(upgrade=True)


def downgrade() -> None:
    # SQLite keeps a longer value in a shorter column, so no format is lost.
    _resize(upgrade=False)
