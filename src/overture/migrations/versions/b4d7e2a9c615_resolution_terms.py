"""A title's resolutions are terms: a movie's versions, a show's episodes.

Revision ID: b4d7e2a9c615
Revises: c6e2a8f4d913
Create Date: 2026-11-24 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d7e2a9c615"
down_revision: str | Sequence[str] | None = "c6e2a8f4d913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BEFORE = (
    "genre",
    "actor",
    "director",
    "writer",
    "producer",
    "country",
    "label",
    "tmdb_keyword",
    "company",
    "network",
    "streaming",
    "origin_country",
)
_KINDS = (*_BEFORE, "resolution")


def _enum(values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name="termkind", native_enum=False)


def _retype(values: tuple[str, ...], before: tuple[str, ...]) -> None:
    """Admit *values* as the kinds of terms and of their links."""
    check = f"kind IN ({', '.join(f"'{value}'" for value in values)})"
    for table, table_kwargs in (
        ("terms", {}),
        # The links are clustered by title and kind, without a rowid.
        ("media_item_terms", {"sqlite_with_rowid": False}),
    ):
        with op.batch_alter_table(table, table_kwargs=table_kwargs) as batch:
            batch.drop_constraint(f"ck_{table}_kind", type_="check")
            batch.alter_column("kind", type_=_enum(values), existing_type=_enum(before))
            batch.create_check_constraint(f"ck_{table}_kind", check)


def upgrade() -> None:
    """Each title's one resolution becomes the first of its resolution terms."""
    _retype(_KINDS, _BEFORE)
    op.execute(
        "INSERT INTO terms (kind, name) SELECT DISTINCT 'resolution', resolution "
        "FROM media_items WHERE resolution IS NOT NULL AND resolution != ''"
    )
    op.execute(
        "INSERT INTO media_item_terms (media_item_id, kind, position, term_id) "
        "SELECT m.id, 'resolution', 0, t.id FROM media_items AS m "
        "JOIN terms AS t ON t.kind = 'resolution' AND t.name = m.resolution"
    )
    with op.batch_alter_table("media_items") as batch:
        batch.drop_column("resolution")


def downgrade() -> None:
    """A title keeps its first resolution; the rest are dropped."""
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column("resolution", sa.String(), nullable=True))
    op.execute(
        "UPDATE media_items SET resolution = ("
        "SELECT t.name FROM media_item_terms AS l "
        "JOIN terms AS t ON t.id = l.term_id "
        "WHERE l.media_item_id = media_items.id AND l.kind = 'resolution' "
        "ORDER BY l.position LIMIT 1)"
    )
    op.execute("DELETE FROM media_item_terms WHERE kind = 'resolution'")
    op.execute("DELETE FROM terms WHERE kind = 'resolution'")
    _retype(_BEFORE, _KINDS)
