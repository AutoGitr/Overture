"""Fold ``task_schedule`` into ``saved_schedules`` so one table holds all schedules.

Revision ID: d4f9a2b6e831
Revises: c3e8a1f5d927
Create Date: 2026-11-21 12:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "d4f9a2b6e831"
down_revision: str | Sequence[str] | None = "c3e8a1f5d927"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = ("assets", "sync")
_KINDS = ("assets", "sync", "backup", "catalog")


def _enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name="schedulekind", native_enum=False)


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _retype(values: tuple[str, ...], before: tuple[str, ...]) -> None:
    with op.batch_alter_table("saved_schedules") as batch:
        batch.drop_constraint("ck_saved_schedules_kind", type_="check")
        batch.alter_column("kind", type_=_enum(values), existing_type=_enum(before))
        batch.create_check_constraint("ck_saved_schedules_kind", _check("kind", values))


def upgrade() -> None:
    """Extend ``saved_schedules.kind``, move backup/catalog rows, drop old table."""
    _retype(_KINDS, _BEFORE)
    conn = op.get_bind()
    conn.exec_driver_sql(
        "INSERT INTO saved_schedules ("
        "kind, name, enabled, cron_expression, payload, state, created_at, updated_at"
        ") "
        "SELECT "
        "task_name, "
        "task_name, "
        "enabled, "
        "CASE "
        "WHEN NULLIF(cron_expression, '') IS NOT NULL THEN cron_expression "
        "WHEN task_name = 'backup' THEN '0 3 * * *' "
        "ELSE '0 0 * * *' "
        "END, "
        "payload, "
        "'{}', "
        "COALESCE(updated_at, CURRENT_TIMESTAMP), "
        "COALESCE(updated_at, CURRENT_TIMESTAMP) "
        "FROM task_schedule "
        "WHERE task_name IN ('backup', 'catalog')"
    )
    op.drop_table("task_schedule")


def downgrade() -> None:
    """Restore ``task_schedule`` and narrow ``saved_schedules.kind`` again."""
    op.create_table(
        "task_schedule",
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cron_expression", auto_string(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("task_name", auto_string(), nullable=False),
        sa.CheckConstraint(
            "json_valid(payload) AND json_type(payload) != 'null'",
            name="ck_task_schedule_payload_json",
        ),
        sa.PrimaryKeyConstraint("task_name"),
    )
    conn = op.get_bind()
    conn.exec_driver_sql(
        "INSERT INTO task_schedule "
        "(task_name, enabled, cron_expression, payload, updated_at) "
        "SELECT kind, enabled, cron_expression, payload, updated_at "
        "FROM saved_schedules WHERE kind IN ('backup', 'catalog')"
    )
    conn.exec_driver_sql(
        "DELETE FROM saved_schedules WHERE kind IN ('backup', 'catalog')"
    )
    _retype(_BEFORE, _KINDS)
