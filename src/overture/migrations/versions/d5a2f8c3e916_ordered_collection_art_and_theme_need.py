"""Order Automatic art and OvertureDB posters, and let collections need no theme.

Each ``auto_art`` choice becomes the list of sources it tried, first to last
(``off`` the empty list), and each ``overturedb_posters`` choice the list of the
one style it took. ``themes`` says whether collections need a theme.

Revision ID: d5a2f8c3e916
Revises: 3ae7fb38a1bb
Create Date: 2026-11-18 12:00:00.000000

"""

import json
from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "d5a2f8c3e916"
down_revision: str | Sequence[str] | None = "3ae7fb38a1bb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Each policy table with the prefix of its policy columns.
_POLICY_TABLES = (
    ("app_settings", "collection_"),
    ("collection_groups", ""),
    ("collection_rules", ""),
)
_AUTO_ART = (
    "off",
    "overturedb",
    "tmdb",
    "overturedb_tmdb",
    "overturedb_generate",
    "tmdb_generate",
    "overturedb_tmdb_generate",
    "generate",
)
_STYLES = ("individual", "matte", "overlay")
#: The order the single choices tried their sources in.
_SOURCE_ORDER = ("overturedb", "tmdb", "generate")


def _enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False)


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _auto_art_order(choice: str) -> str:
    return json.dumps([] if choice == "off" else choice.split("_"))


def _auto_art_choice(stored: str) -> str:
    # A single choice tries OvertureDB before TMDB and generates last, so an
    # order that differs keeps the sources it names in that order.
    order: list[str] = json.loads(stored)
    return "_".join(source for source in _SOURCE_ORDER if source in order) or "off"


def _style_order(style: str) -> str:
    return json.dumps([style])


def _style_choice(stored: str) -> str:
    # No single choice takes no OvertureDB poster; Individual is the default.
    styles: list[str] = json.loads(stored)
    return next(iter(styles), "individual")


def _retype(
    table: str,
    column: str,
    convert: Callable[[str], str],
    *,
    before: sa.types.TypeEngine[Any],
    after: sa.types.TypeEngine[Any],
    checks: tuple[str, tuple[str, str]],
) -> None:
    """Convert each stored value of *column* and give it type *after*.

    *checks* names the check constraint to drop, and the one to create.
    """
    drop, create = checks
    with op.batch_alter_table(table) as batch:
        batch.drop_constraint(drop, type_="check")
    conn = op.get_bind()
    for row_id, value in conn.exec_driver_sql(
        f"SELECT id, {column} FROM {table} WHERE {column} IS NOT NULL"  # noqa: S608 -- fixed table and column names
    ).all():
        conn.exec_driver_sql(
            f"UPDATE {table} SET {column} = ? WHERE id = ?",  # noqa: S608 -- fixed table and column names
            (convert(value), row_id),
        )
    with op.batch_alter_table(table) as batch:
        batch.alter_column(column, type_=after, existing_type=before)
        batch.create_check_constraint(*create)


def upgrade() -> None:
    """Turn the two choices into ordered lists and add the theme setting."""
    for table, prefix in _POLICY_TABLES:
        upgrades: tuple[tuple[str, tuple[str, ...], Callable[[str], str]], ...] = (
            (f"{prefix}auto_art", _AUTO_ART, _auto_art_order),
            (f"{prefix}overturedb_posters", _STYLES, _style_order),
        )
        for column, values, convert in upgrades:
            _retype(
                table,
                column,
                convert,
                before=_enum("enum", values),
                after=sa.JSON(),
                checks=(
                    f"ck_{table}_{column}",
                    (f"ck_{table}_{column}_json", f"json_valid({column})"),
                ),
            )
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column(
                    f"{prefix}themes",
                    sa.Boolean(),
                    nullable=not prefix,
                    server_default=sa.true() if prefix else None,
                )
            )
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column("collection_themes", server_default=None)


def downgrade() -> None:
    """Keep the first style and the sources each order names, in the old order."""
    for table, prefix in _POLICY_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column(f"{prefix}themes")
        downgrades: tuple[tuple[str, tuple[str, ...], Callable[[str], str]], ...] = (
            (f"{prefix}auto_art", _AUTO_ART, _auto_art_choice),
            (f"{prefix}overturedb_posters", _STYLES, _style_choice),
        )
        for column, values, convert in downgrades:
            _retype(
                table,
                column,
                convert,
                before=sa.JSON(),
                after=_enum("enum", values),
                checks=(
                    f"ck_{table}_{column}_json",
                    (f"ck_{table}_{column}", _check(column, values)),
                ),
            )
