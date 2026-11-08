"""Movies and shows keep only their own fields, and only shows have seasons.

Revision ID: a4d7c1e93f20
Revises: f3b8d2a61c47
Create Date: 2026-11-08 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4d7c1e93f20"
down_revision: str | Sequence[str] | None = "f3b8d2a61c47"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Names the baseline's unnamed foreign key so the batch can drop it.
_NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"}

_MOVIE_FIELDS = (
    "media_type = 'movie' OR (tmdb_collection_id IS NULL AND edition IS NULL"
    " AND versions IS NULL AND director_etag IS NULL)"
)
_SHOW_FIELDS = "media_type = 'show' OR (show_status IS NULL AND last_aired IS NULL)"


def upgrade() -> None:
    """Clear the other type's fields, as enrichment now writes them, then enforce it.

    TMDB enrichment recorded a show status, last air date and networks for
    movies too; it now records them for shows only.
    """
    op.execute(
        "UPDATE media_items SET show_status = NULL, last_aired = NULL, "
        "networks = '[]' WHERE media_type = 'movie'"
    )
    op.execute(
        "UPDATE media_items SET tmdb_collection_id = NULL, edition = NULL, "
        "versions = NULL, director_etag = NULL WHERE media_type = 'show'"
    )
    with op.batch_alter_table("media_items") as batch:
        batch.create_unique_constraint("uq_media_items_typed", ["id", "media_type"])
        batch.create_check_constraint("ck_media_items_movie_fields", _MOVIE_FIELDS)
        batch.create_check_constraint("ck_media_items_show_fields", _SHOW_FIELDS)
    with op.batch_alter_table("seasons", naming_convention=_NAMING) as batch:
        batch.add_column(
            sa.Column(
                "media_type",
                sa.Enum("movie", "show", name="mediatype", native_enum=False),
                nullable=False,
                server_default="show",
            )
        )
        batch.drop_constraint(
            "fk_seasons_media_item_id_media_items", type_="foreignkey"
        )
        batch.create_foreign_key(
            "fk_seasons_show",
            "media_items",
            ["media_item_id", "media_type"],
            ["id", "media_type"],
            ondelete="CASCADE",
        )
        batch.create_check_constraint(
            "ck_seasons_media_type", "media_type IN ('movie', 'show')"
        )
        batch.create_check_constraint("ck_seasons_show", "media_type = 'show'")


def downgrade() -> None:
    """Drop the constraints; the cleared fields of the other type stay empty."""
    with op.batch_alter_table("seasons") as batch:
        batch.drop_constraint("ck_seasons_show", type_="check")
        batch.drop_constraint("ck_seasons_media_type", type_="check")
        batch.drop_constraint("fk_seasons_show", type_="foreignkey")
        batch.drop_column("media_type")
        batch.create_foreign_key(
            "fk_seasons_media_item_id_media_items",
            "media_items",
            ["media_item_id"],
            ["id"],
            ondelete="CASCADE",
        )
    with op.batch_alter_table("media_items") as batch:
        batch.drop_constraint("ck_media_items_show_fields", type_="check")
        batch.drop_constraint("ck_media_items_movie_fields", type_="check")
        batch.drop_constraint("uq_media_items_typed", type_="unique")
