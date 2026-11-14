"""Split collection OvertureDB posters into individual, matte and overlay.

Collection entries and ``catalog_collections`` carry ``poster_url_individual``,
``poster_url_matte`` and ``poster_url_overlay``, and ``overturedb_posters``
choices ``consistent`` become ``overlay``.

Revision ID: a4e9c2b8f517
Revises: f2b6d9a4c731
Create Date: 2026-11-14 18:20:00.000000

"""

import json
from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "a4e9c2b8f517"
down_revision: str | Sequence[str] | None = "f2b6d9a4c731"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_POLICY_TABLES = (
    ("app_settings", "collection_"),
    ("collection_groups", ""),
    ("collection_rules", ""),
)
_OLD_STYLES = ("individual", "consistent")
_NEW_STYLES = ("individual", "matte", "overlay")


def _enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name="collectionposterstyle", native_enum=False)


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _update_policies(
    *,
    before: tuple[str, ...],
    after: tuple[str, ...],
    replacements: tuple[tuple[str, str], ...],
) -> None:
    for table, prefix in _POLICY_TABLES:
        column = f"{prefix}overturedb_posters"
        constraint = f"ck_{table}_{column}"
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(constraint, type_="check")
        for old, new in replacements:
            op.execute(
                sa.text(
                    f"UPDATE {table} SET {column} = :new WHERE {column} = :old"  # noqa: S608 -- fixed table and column names
                ).bindparams(old=old, new=new)
            )
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                column,
                type_=_enum(after),
                existing_type=_enum(before),
            )
            batch.create_check_constraint(constraint, _check(column, after))


def _convert_drafts(convert: Callable[[dict[str, Any]], None]) -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, entry FROM catalog_drafts WHERE media_type = 'collection'")
    ).all()
    for row_id, raw in rows:
        entry = json.loads(raw)
        convert(entry)
        conn.execute(
            sa.text("UPDATE catalog_drafts SET entry = :entry WHERE id = :id"),
            {"id": row_id, "entry": json.dumps(entry)},
        )


def _split_posters(entry: dict[str, Any]) -> None:
    entry["poster_url_individual"] = entry.pop("poster_url")
    entry["poster_url_matte"] = None
    entry["poster_url_overlay"] = entry.pop("consistent_poster_url", None)


def _join_posters(entry: dict[str, Any]) -> None:
    entry["poster_url"] = entry.pop("poster_url_individual")
    # The previous revision has one consistent poster, the overlay layout's, so
    # a matte poster has nowhere to go.
    del entry["poster_url_matte"]
    if (overlay := entry.pop("poster_url_overlay")) is not None:
        entry["consistent_poster_url"] = overlay


def upgrade() -> None:
    _update_policies(
        before=_OLD_STYLES,
        after=_NEW_STYLES,
        replacements=(("consistent", "overlay"),),
    )
    with op.batch_alter_table("catalog_collections") as batch:
        batch.alter_column("poster_url", new_column_name="poster_url_individual")
        batch.add_column(sa.Column("poster_url_matte", sa.String(), nullable=True))
        batch.alter_column(
            "consistent_poster_url", new_column_name="poster_url_overlay"
        )
    _convert_drafts(_split_posters)


def downgrade() -> None:
    _convert_drafts(_join_posters)
    with op.batch_alter_table("catalog_collections") as batch:
        batch.alter_column("poster_url_individual", new_column_name="poster_url")
        batch.drop_column("poster_url_matte")
        batch.alter_column(
            "poster_url_overlay", new_column_name="consistent_poster_url"
        )
    _update_policies(
        before=_NEW_STYLES,
        after=_OLD_STYLES,
        replacements=(("matte", "consistent"), ("overlay", "consistent")),
    )
