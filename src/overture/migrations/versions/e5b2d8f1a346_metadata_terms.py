"""Titles hold their genres, people and other values as shared term rows.

Revision ID: e5b2d8f1a346
Revises: d6a1b3c8f957
Create Date: 2026-11-08 12:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "e5b2d8f1a346"
down_revision: str | Sequence[str] | None = "d6a1b3c8f957"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Each list column and the kind of term its values become.
_COLUMNS = {
    "genres": "genre",
    "actors": "actor",
    "directors": "director",
    "writers": "writer",
    "producers": "producer",
    "countries": "country",
    "labels": "label",
    "tmdb_keywords": "tmdb_keyword",
    "companies": "company",
    "networks": "network",
    "streaming": "streaming",
    "origin_countries": "origin_country",
}

_KINDS = ", ".join(f"'{kind}'" for kind in _COLUMNS.values())


def _values(column: str) -> str:
    """Each item's distinct non-empty values of *column*, at their first place.

    Only movies have directors, as the app records them.
    """
    movies_only = " AND m.media_type = 'movie'" if column == "directors" else ""
    return (
        f"SELECT m.id AS item_id, j.value AS name, MIN(CAST(j.key AS INTEGER)) "  # noqa: S608 -- constant SQL
        f"AS place FROM media_items AS m, json_each(m.{column}) AS j "
        f"WHERE j.value != ''{movies_only} GROUP BY m.id, j.value"
    )


def upgrade() -> None:
    """Move each list into term rows and links, numbered as the app numbers them."""
    op.create_table(
        "terms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(*_COLUMNS.values(), name="termkind", native_enum=False),
            nullable=False,
        ),
        sa.Column("name", auto_string(), nullable=False),
        sa.CheckConstraint(f"kind IN ({_KINDS})", name="ck_terms_kind"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "name", name="uq_terms"),
    )
    op.create_table(
        "media_item_terms",
        sa.Column("media_item_id", sa.Integer(), nullable=False),
        sa.Column("term_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("media_item_id", "term_id"),
    )
    op.create_index("ix_media_item_terms_term", "media_item_terms", ["term_id"])
    for column, kind in _COLUMNS.items():
        values = _values(column)
        op.execute(
            "INSERT OR IGNORE INTO terms (kind, name) "  # noqa: S608 -- constant SQL
            f"SELECT DISTINCT '{kind}', name FROM ({values})"
        )
        op.execute(
            "INSERT INTO media_item_terms (media_item_id, term_id, position) "  # noqa: S608 -- constant SQL
            "SELECT v.item_id, t.id, "
            "ROW_NUMBER() OVER (PARTITION BY v.item_id ORDER BY v.place) - 1 "
            f"FROM ({values}) AS v JOIN terms AS t "
            f"ON t.kind = '{kind}' AND t.name = v.name"
        )
    with op.batch_alter_table("media_items") as batch:
        for column in _COLUMNS:
            batch.drop_column(column)


def downgrade() -> None:
    """Rebuild each list column from the item's terms, in order."""
    with op.batch_alter_table("media_items") as batch:
        for column in _COLUMNS:
            batch.add_column(
                sa.Column(column, sa.JSON(), nullable=False, server_default="[]")
            )
    for column, kind in _COLUMNS.items():
        op.execute(
            f"UPDATE media_items SET {column} = COALESCE((SELECT "  # noqa: S608 -- constant SQL
            "json_group_array(name) FROM (SELECT t.name AS name FROM "
            "media_item_terms AS l JOIN terms AS t ON t.id = l.term_id "
            f"WHERE l.media_item_id = media_items.id AND t.kind = '{kind}' "
            "ORDER BY l.position)), '[]')"
        )
    with op.batch_alter_table("media_items") as batch:
        for column in _COLUMNS:
            batch.alter_column(column, server_default=None)
    op.drop_index("ix_media_item_terms_term", table_name="media_item_terms")
    op.drop_table("media_item_terms")
    op.drop_table("terms")
