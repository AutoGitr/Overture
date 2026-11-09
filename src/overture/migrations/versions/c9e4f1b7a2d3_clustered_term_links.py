"""Term links are clustered by title and kind, and state their kind.

Revision ID: c9e4f1b7a2d3
Revises: a8d3e6f0c271
Create Date: 2026-11-09 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9e4f1b7a2d3"
down_revision: str | Sequence[str] | None = "a8d3e6f0c271"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_KINDS = (
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


def upgrade() -> None:
    """Rebuild the links in key order, numbering each title's values per kind."""
    op.create_index("uq_terms_id_kind", "terms", ["id", "kind"], unique=True)
    quoted = ", ".join(f"'{kind}'" for kind in _KINDS)
    op.create_table(
        "media_item_terms_clustered",
        sa.Column("media_item_id", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(*_KINDS, name="termkind", native_enum=False),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("term_id", sa.Integer(), nullable=False),
        sa.CheckConstraint(f"kind IN ({quoted})", name="ck_media_item_terms_kind"),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["term_id", "kind"],
            ["terms.id", "terms.kind"],
            name="fk_media_item_terms_term",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("media_item_id", "kind", "position"),
        sqlite_with_rowid=False,
    )
    op.execute(
        "INSERT INTO media_item_terms_clustered "
        "(media_item_id, kind, position, term_id) "
        "SELECT l.media_item_id, t.kind, ROW_NUMBER() OVER ("
        "PARTITION BY l.media_item_id, t.kind ORDER BY l.position, l.term_id"
        ") - 1, l.term_id FROM media_item_terms AS l "
        "JOIN terms AS t ON t.id = l.term_id ORDER BY 1, 2, 3"
    )
    op.drop_index("ix_media_item_terms_term", table_name="media_item_terms")
    op.drop_table("media_item_terms")
    op.rename_table("media_item_terms_clustered", "media_item_terms")
    op.create_index(
        "uq_media_item_terms_term",
        "media_item_terms",
        ["term_id", "media_item_id"],
        unique=True,
    )


def downgrade() -> None:
    """Rebuild the links keyed by title and term."""
    op.create_table(
        "media_item_terms_keyed",
        sa.Column("media_item_id", sa.Integer(), nullable=False),
        sa.Column("term_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("media_item_id", "term_id"),
    )
    op.execute(
        "INSERT INTO media_item_terms_keyed (media_item_id, term_id, position) "
        "SELECT media_item_id, term_id, position FROM media_item_terms"
    )
    op.drop_index("uq_media_item_terms_term", table_name="media_item_terms")
    op.drop_table("media_item_terms")
    op.rename_table("media_item_terms_keyed", "media_item_terms")
    op.create_index("ix_media_item_terms_term", "media_item_terms", ["term_id"])
    op.drop_index("uq_terms_id_kind", table_name="terms")
