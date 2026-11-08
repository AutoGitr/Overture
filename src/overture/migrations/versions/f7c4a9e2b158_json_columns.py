"""JSON columns are typed JSON, named for what they hold, and hold valid JSON.

Revision ID: f7c4a9e2b158
Revises: e5b2d8f1a346
Create Date: 2026-11-08 12:50:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "f7c4a9e2b158"
down_revision: str | Sequence[str] | None = "e5b2d8f1a346"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Each table's JSON columns: the stored name before, and the name now.
_RENAMED = {
    "collection_libraries": {"criteria_json": "criteria"},
    "collection_groups": {"generator_json": "generator"},
    "saved_schedules": {
        "payload_json": "payload",
        "state_json": "state",
        "last_run_json": "last_run_summary",
    },
    "task_schedule": {"payload_json": "payload"},
}
#: JSON columns whose name stays.
_KEPT = {
    "job_runs": ("summary",),
    "job_results": ("payload",),
    "job_log_lines": ("entry",),
    "public_dataset_drafts": ("entry",),
}
#: Columns that held JSON as text rather than as typed JSON.
_FROM_TEXT = {"criteria_json", "generator_json"}


def _check(table: str, column: str) -> str:
    return f"ck_{table}_{column}_json"


def upgrade() -> None:
    """Rename and retype; the stored text is the same JSON either way."""
    for table, columns in _RENAMED.items():
        with op.batch_alter_table(table) as batch:
            for old, new in columns.items():
                batch.alter_column(old, new_column_name=new, type_=sa.JSON())
                batch.create_check_constraint(_check(table, new), f"json_valid({new})")
    for table, kept in _KEPT.items():
        with op.batch_alter_table(table) as batch:
            for column in kept:
                batch.create_check_constraint(
                    _check(table, column), f"json_valid({column})"
                )


def downgrade() -> None:
    """Drop the checks and restore the stored names and text columns."""
    for table, kept in _KEPT.items():
        with op.batch_alter_table(table) as batch:
            for column in kept:
                batch.drop_constraint(_check(table, column), type_="check")
    for table, columns in _RENAMED.items():
        with op.batch_alter_table(table) as batch:
            for old, new in columns.items():
                batch.drop_constraint(_check(table, new), type_="check")
                batch.alter_column(
                    new,
                    new_column_name=old,
                    type_=auto_string() if old in _FROM_TEXT else sa.JSON(),
                )
