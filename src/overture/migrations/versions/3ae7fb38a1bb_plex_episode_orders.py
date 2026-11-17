"""Order show collections by their latest episode added and unplayed episodes.

Revision ID: 3ae7fb38a1bb
Revises: e4b1c8f2a903
Create Date: 2026-11-17 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3ae7fb38a1bb"
down_revision: str | Sequence[str] | None = "e4b1c8f2a903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "custom",
    "release.asc",
    "release.desc",
    "title.asc",
    "title.desc",
    "added.desc",
    "added.asc",
    "critic_rating.desc",
    "critic_rating.asc",
    "audience_rating.desc",
    "audience_rating.asc",
    "user_rating.desc",
    "user_rating.asc",
    "duration.desc",
    "duration.asc",
    "plays.desc",
    "plays.asc",
    "last_played.desc",
    "last_played.asc",
    "random",
)
_ORDERS = (
    *_BEFORE[:-1],
    "episode_added.desc",
    "episode_added.asc",
    "unplayed_episodes.desc",
    "unplayed_episodes.asc",
    "random",
)
#: Each table's order column, and whether it may inherit (hold NULL).
_COLUMNS = (
    ("media_collections", "order_type", False),
    ("collection_rules", "order_type", True),
    ("collection_groups", "order_type", True),
    ("app_settings", "collection_order_default", False),
)
#: The order a collection would sort by without the new ones, by the date the
#: latest episode was added, or else as it inherits or by release.
_DOWNGRADED = {
    "episode_added.desc": "added.desc",
    "episode_added.asc": "added.asc",
}
_DEFAULT = "release.asc"


def _enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name="collectionorder", native_enum=False)


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _retype(values: tuple[str, ...], before: tuple[str, ...]) -> None:
    for table, column, _ in _COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_{column}", type_="check")
            batch.alter_column(column, type_=_enum(values), existing_type=_enum(before))
            batch.create_check_constraint(
                f"ck_{table}_{column}", _check(column, values)
            )


def upgrade() -> None:
    """Admit the new orders in every order column."""
    _retype(_ORDERS, _BEFORE)


def downgrade() -> None:
    """Move collections off the new orders, then admit only the older ones."""
    conn = op.get_bind()
    for table, column, inherits in _COLUMNS:
        for new in _ORDERS:
            if new in _BEFORE:
                continue
            old = _DOWNGRADED.get(new)
            conn.exec_driver_sql(
                f"UPDATE {table} SET {column} = ? WHERE {column} = ?",  # noqa: S608 -- fixed table and column names
                (old or (None if inherits else _DEFAULT), new),
            )
    _retype(_BEFORE, _ORDERS)
