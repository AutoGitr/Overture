"""The media server's libraries are rows that items and collections reference.

Revision ID: d6a1b3c8f957
Revises: c2f9a7d4e815
Create Date: 2026-11-08 12:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "d6a1b3c8f957"
down_revision: str | Sequence[str] | None = "c2f9a7d4e815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_REFERENCES = (
    ("media_items", "fk_media_items_library"),
    ("collection_libraries", "fk_collection_libraries_library"),
)


def upgrade() -> None:
    """Add a row for each library items and collections name.

    A migration cannot ask the server for titles, so each is titled by its
    key until the next sync, which records every library before its items.
    """
    op.create_table(
        "libraries",
        sa.Column("id", auto_string(), nullable=False),
        sa.Column(
            "media_type",
            sa.Enum("movie", "show", name="mediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column("title", auto_string(), nullable=False),
        sa.Column("removed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_libraries_media_type"
        ),
        sa.PrimaryKeyConstraint("id", "media_type"),
    )
    op.create_index(
        "uq_libraries_listed",
        "libraries",
        ["id"],
        unique=True,
        sqlite_where=sa.text("removed_at IS NULL"),
    )
    op.execute(
        "INSERT INTO libraries (id, media_type, title) "
        "SELECT library_id, media_type, library_id FROM media_items "
        "WHERE library_id IS NOT NULL "
        "UNION SELECT library_id, media_type, library_id FROM collection_libraries"
    )
    for table, name in _REFERENCES:
        with op.batch_alter_table(table) as batch:
            batch.create_foreign_key(
                name,
                "libraries",
                ["library_id", "media_type"],
                ["id", "media_type"],
                ondelete="RESTRICT",
            )


def downgrade() -> None:
    """Drop the libraries; items and collections keep their library keys."""
    for table, name in _REFERENCES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(name, type_="foreignkey")
    op.drop_table("libraries")
