"""Hold "no value" in a JSON column as SQL NULL, never as JSON's null.

A JSON column left empty held JSON's ``null``, which a SQL ``IS NULL`` test
does not see, so a query or migration filtering on it read text it could not
use. Such values become SQL NULL, and every JSON column refuses JSON's null.

Revision ID: a1f6c3e8d590
Revises: f5d1b7e3a982
Create Date: 2026-11-20 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a1f6c3e8d590"
down_revision: str | Sequence[str] | None = "f5d1b7e3a982"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Each table's JSON columns, and whether each may hold no value.
_JSON_COLUMNS: dict[str, dict[str, bool]] = {
    "app_settings": {
        "collection_auto_art": False,
        "collection_overturedb_posters": False,
    },
    "catalog_drafts": {"entry": False},
    "collection_groups": {
        "auto_art": True,
        "overturedb_posters": True,
        "generator": True,
    },
    "collection_libraries": {"criteria": True},
    "collection_rules": {"auto_art": True, "overturedb_posters": True},
    "job_log_lines": {"entry": False},
    "job_results": {"payload": False},
    "job_runs": {"summary": False},
    "media_item_copies": {"labels": False},
    "saved_filters": {"criteria": False},
    "saved_schedules": {
        "payload": False,
        "state": False,
        "last_run_summary": True,
    },
    "task_schedule": {"payload": False},
}


def _check(table: str, column: str) -> str:
    return f"ck_{table}_{column}_json"


def _recreate_checks(sql: str) -> None:
    for table, columns in _JSON_COLUMNS.items():
        with op.batch_alter_table(table) as batch:
            for column in columns:
                batch.drop_constraint(_check(table, column), type_="check")
                batch.create_check_constraint(
                    _check(table, column), sql.format(column=column)
                )


def upgrade() -> None:
    for table, columns in _JSON_COLUMNS.items():
        for column, nullable in columns.items():
            if nullable:
                op.execute(
                    f"UPDATE {table} SET {column} = NULL "  # noqa: S608 -- fixed table and column names
                    f"WHERE json_type({column}) = 'null'"
                )
    _recreate_checks("json_valid({column}) AND json_type({column}) != 'null'")


def downgrade() -> None:
    """Admit JSON's null again; SQL NULL reads the same to the earlier schema."""
    _recreate_checks("json_valid({column})")
