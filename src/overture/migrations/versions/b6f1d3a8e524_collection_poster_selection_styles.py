"""Record the poster style of every collection's selected poster link.

A collection's poster link is contributed to OvertureDB as the individual,
matte or overlay poster it was selected as, whatever the collection's policy
says later. A link OvertureDB already holds as one of the collection's posters
takes that style; every other link is an individual poster.

Revision ID: b6f1d3a8e524
Revises: a4e9c2b8f517
Create Date: 2026-11-14 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.catalog_contract.contract import catalog_art_url

revision: str = "b6f1d3a8e524"
down_revision: str | Sequence[str] | None = "a4e9c2b8f517"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STYLES = ("individual", "matte", "overlay")


def _canonical(url: str) -> str | None:
    try:
        return catalog_art_url(url)
    except ValueError:
        return None


def _held_style(url: str, held: dict[str, str | None]) -> str:
    """The style OvertureDB holds *url* as, else ``individual``."""
    canonical = _canonical(url)
    return next(
        (style for style in _STYLES if canonical and held[style] == canonical),
        "individual",
    )


def upgrade() -> None:
    with op.batch_alter_table("art_slots") as batch:
        batch.add_column(
            sa.Column(
                "poster_style",
                sa.Enum(*_STYLES, name="collectionposterstyle", native_enum=False),
                nullable=True,
            )
        )
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT slot.id, slot.url, entry.poster_url_individual, "
            "entry.poster_url_matte, entry.poster_url_overlay "
            "FROM art_slots AS slot "
            "JOIN media_collections AS owner ON owner.id = slot.collection_id "
            "LEFT JOIN catalog_collections AS entry "
            "ON entry.tmdb_id = owner.tmdb_collection_id "
            "WHERE slot.art_type = 'poster' AND slot.url IS NOT NULL"
        )
    ).all()
    for slot_id, url, *posters in rows:
        conn.execute(
            sa.text("UPDATE art_slots SET poster_style = :style WHERE id = :id"),
            {
                "id": slot_id,
                "style": _held_style(url, dict(zip(_STYLES, posters, strict=True))),
            },
        )
    with op.batch_alter_table("art_slots") as batch:
        batch.create_check_constraint(
            "ck_art_slots_poster_style",
            f"poster_style IN ({', '.join(f"'{style}'" for style in _STYLES)})",
        )
        batch.create_check_constraint(
            "ck_art_slots_collection_poster_style",
            "(poster_style IS NOT NULL) = (collection_id IS NOT NULL "
            "AND art_type = 'poster' AND url IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("art_slots") as batch:
        batch.drop_constraint("ck_art_slots_collection_poster_style", type_="check")
        batch.drop_constraint("ck_art_slots_poster_style", type_="check")
        batch.drop_column("poster_style")
