"""Name Automatic art's fallback and its colours after generated art.

Automatic art's ``draw`` choices become ``generate``, and each policy's
``drawn_style`` column becomes ``generated_style``, matching the ``generated``
art source and art slot columns.

Revision ID: f2b6d9a4c731
Revises: c9e4b1a7d385
Create Date: 2026-11-13 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f2b6d9a4c731"
down_revision: str | Sequence[str] | None = "c9e4b1a7d385"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: A name before and after this revision.
type Names = tuple[str, str]

#: Each policy table with the prefix of its Automatic art columns.
_POLICY_TABLES = (
    ("app_settings", "collection_"),
    ("collection_groups", ""),
    ("collection_rules", ""),
)
_SOURCES = ("off", "overturedb", "tmdb", "overturedb_tmdb")
_GENERATING: tuple[Names, ...] = (
    ("overturedb_draw", "overturedb_generate"),
    ("tmdb_draw", "tmdb_generate"),
    ("overturedb_tmdb_draw", "overturedb_tmdb_generate"),
    ("draw", "generate"),
)
_STYLE: Names = ("drawn_style", "generated_style")
_STYLES = ("dark", "light", "accent")


def _auto_art(index: int) -> tuple[str, ...]:
    return (*_SOURCES, *(names[index] for names in _GENERATING))


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _rename(old: int, new: int) -> None:
    """Rename every choice and column from its name at *old* to its name at *new*."""
    for table, prefix in _POLICY_TABLES:
        auto_art = f"{prefix}auto_art"
        style = tuple(f"{prefix}{name}" for name in _STYLE)
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_{auto_art}", type_="check")
            batch.drop_constraint(f"ck_{table}_{style[old]}", type_="check")
        for names in _GENERATING:
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {auto_art} = :new WHERE {auto_art} = :old"  # noqa: S608 -- fixed table and column names
                ).bindparams(old=names[old], new=names[new])
            )
        with op.batch_alter_table(table) as batch:
            batch.alter_column(style[old], new_column_name=style[new])
            batch.alter_column(
                auto_art,
                type_=sa.Enum(*_auto_art(new), name="autoart", native_enum=False),
                existing_type=sa.Enum(
                    *_auto_art(old), name="autoart", native_enum=False
                ),
            )
            batch.create_check_constraint(
                f"ck_{table}_{auto_art}", _check(auto_art, _auto_art(new))
            )
            batch.create_check_constraint(
                f"ck_{table}_{style[new]}", _check(style[new], _STYLES)
            )


def upgrade() -> None:
    _rename(0, 1)


def downgrade() -> None:
    _rename(1, 0)
