"""Share saved filters between movies and shows, one per name.

A filter keeps its media type only when it names titles by TMDB ID, which
differ between movies and shows. A movie and a show filter of the same name
and criteria become one; otherwise the show filter is renamed after its
media type.

Revision ID: f1b8d4e6a273
Revises: d5a2f8c3e916
Create Date: 2026-11-18 13:00:00.000000

"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "f1b8d4e6a273"
down_revision: str | Sequence[str] | None = "d5a2f8c3e916"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MEDIA_TYPE = sa.Enum("movie", "show", name="mediatype", native_enum=False)


def _names_titles(group: dict[str, Any]) -> bool:
    return any(
        condition.get("kind") == "source"
        and condition["source"].get("type") == "tmdb_item"
        for condition in group.get("conditions", [])
    ) or any(_names_titles(nested) for nested in group.get("groups", []))


def _share(conn: sa.Connection) -> None:
    rows = conn.exec_driver_sql(
        "SELECT id, media_type, name, criteria FROM saved_filters "
        "ORDER BY media_type, id"
    ).all()
    taken = {name.casefold() for _, _, name, _ in rows}
    kept: dict[str, tuple[str | None, object]] = {}
    for row_id, media_type, name, stored in rows:
        criteria = json.loads(stored)
        named = media_type if _names_titles(criteria) else None
        folded = name.casefold()
        if folded not in kept:
            kept[folded] = (named, criteria)
            conn.exec_driver_sql(
                "UPDATE saved_filters SET media_type = ? WHERE id = ?", (named, row_id)
            )
        elif kept[folded] == (named, criteria):
            conn.exec_driver_sql("DELETE FROM saved_filters WHERE id = ?", (row_id,))
        else:
            renamed = f"{name} (shows)"
            number = 2
            while renamed.casefold() in taken:
                renamed = f"{name} (shows {number})"
                number += 1
            taken.add(renamed.casefold())
            conn.exec_driver_sql(
                "UPDATE saved_filters SET name = ?, media_type = ? WHERE id = ?",
                (renamed, named, row_id),
            )


def upgrade() -> None:
    """Make each name one filter, typed only when it names titles by ID."""
    with op.batch_alter_table("saved_filters") as batch:
        batch.drop_constraint("uq_saved_filters_media_type_name", type_="unique")
        batch.alter_column("media_type", existing_type=_MEDIA_TYPE, nullable=True)
    _share(op.get_bind())
    with op.batch_alter_table("saved_filters") as batch:
        batch.create_unique_constraint("uq_saved_filters_name", ["name"])


def downgrade() -> None:
    """Keep each shared filter as a movie filter; it cannot be told apart."""
    op.execute("UPDATE saved_filters SET media_type = 'movie' WHERE media_type IS NULL")
    with op.batch_alter_table("saved_filters") as batch:
        batch.drop_constraint("uq_saved_filters_name", type_="unique")
        batch.alter_column("media_type", existing_type=_MEDIA_TYPE, nullable=False)
        batch.create_unique_constraint(
            "uq_saved_filters_media_type_name", ["media_type", "name"]
        )
