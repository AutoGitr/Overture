"""Movies and shows keep only their own fields.

Revision ID: a4d7c1e93f20
Revises: f3b8d2a61c47
Create Date: 2026-11-08 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "a4d7c1e93f20"
down_revision: str | Sequence[str] | None = "f3b8d2a61c47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MOVIE_FIELDS = (
    "media_type = 'movie' OR (tmdb_collection_id IS NULL AND edition IS NULL"
    " AND versions IS NULL AND director_etag IS NULL)"
)
_SHOW_FIELDS = "media_type = 'show' OR (show_status IS NULL AND last_aired IS NULL)"


def upgrade() -> None:
    """Clear cross-type fields on media_items and enforce per-type constraints."""
    op.execute(
        "UPDATE media_items SET show_status = NULL, last_aired = NULL, "
        "networks = '[]' WHERE media_type = 'movie'"
    )
    op.execute(
        "UPDATE media_items SET tmdb_collection_id = NULL, edition = NULL, "
        "versions = NULL, director_etag = NULL WHERE media_type = 'show'"
    )
    with op.batch_alter_table("media_items") as batch:
        batch.create_check_constraint("ck_media_items_movie_fields", _MOVIE_FIELDS)
        batch.create_check_constraint("ck_media_items_show_fields", _SHOW_FIELDS)


def downgrade() -> None:
    """Drop the constraints; the cleared fields of the other type stay empty."""
    with op.batch_alter_table("media_items") as batch:
        batch.drop_constraint("ck_media_items_show_fields", type_="check")
        batch.drop_constraint("ck_media_items_movie_fields", type_="check")
