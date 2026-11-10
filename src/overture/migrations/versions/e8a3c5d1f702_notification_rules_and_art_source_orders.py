"""Notification rules per kind of run, automatic art in source order, theme auto-search.

A library sync stored each separator's kind as the server's, a regular
collection, so separators it changed are separators again.

Drawn backgrounds never show text and drawn posters always do, so a drawing
records whether its poster leaves out the group instead of whether it is
textless.

Revision ID: e8a3c5d1f702
Revises: b4d7e2a9c815
Create Date: 2026-11-10 16:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e8a3c5d1f702"
down_revision: str | Sequence[str] | None = "b4d7e2a9c815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_AUTO_ART = ("off", "match", "match_or_draw", "draw")
_AUTO_ART = (
    "off",
    "overturedb",
    "tmdb",
    "overturedb_tmdb",
    "overturedb_draw",
    "tmdb_draw",
    "overturedb_tmdb_draw",
    "draw",
)
#: Matching tried OvertureDB, then TMDB; it keeps that order.
_UPGRADED = {"match": "overturedb_tmdb", "match_or_draw": "overturedb_tmdb_draw"}
_COMPLETED = ("never", "always", "changes", "errors")
#: Each table's Automatic art column.
_AUTO_ART_COLUMNS = (
    ("app_settings", "collection_auto_art"),
    ("collection_groups", "auto_art"),
    ("collection_rules", "auto_art"),
)


def _enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False)


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _retype_auto_art(
    values: tuple[str, ...], converted: dict[str, str], before: tuple[str, ...]
) -> None:
    """Give each Automatic art column *values*, converting stored choices."""
    conn = op.get_bind()
    for table, column in _AUTO_ART_COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_{column}", type_="check")
        for old, new in converted.items():
            conn.exec_driver_sql(
                f"UPDATE {table} SET {column} = ? WHERE {column} = ?",  # noqa: S608 -- fixed table and column names
                (new, old),
            )
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                column,
                type_=_enum("autoart", values),
                existing_type=_enum("autoart", before),
            )
            batch.create_check_constraint(
                f"ck_{table}_{column}", _check(column, values)
            )


def _restore_separators(conn: sa.Connection) -> None:
    """Make each separated group's lost separator one again.

    A separator is titled after its group and selects nothing in each of its
    libraries; the oldest such collection of a group without a separator is it.
    """
    # Whether each library of a collection selects nothing.
    empty: dict[int, list[bool]] = {}
    for collection_id, stored in conn.exec_driver_sql(
        "SELECT collection_id, criteria FROM collection_libraries"
    ).all():
        part: dict[str, object] = json.loads(stored) if stored else {}
        empty.setdefault(collection_id, []).append(
            bool(part) and not part.get("conditions") and not part.get("groups")
        )
    for group_id, name in conn.exec_driver_sql(
        "SELECT id, name FROM collection_groups WHERE separator = 1 AND id NOT IN "
        "(SELECT group_id FROM media_collections WHERE kind = 'separator' "
        "AND group_id IS NOT NULL)"
    ).all():
        lost = [
            collection_id
            for (collection_id,) in conn.exec_driver_sql(
                "SELECT c.id FROM media_collections c "
                "JOIN collection_rules r ON r.collection_id = c.id "
                "WHERE c.group_id = ? AND lower(c.title) = lower(?) ORDER BY c.id",
                (group_id, name),
            ).all()
            if empty.get(collection_id) and all(empty[collection_id])
        ]
        if lost:
            conn.exec_driver_sql(
                "UPDATE media_collections SET kind = 'separator' WHERE id = ?",
                (lost[0],),
            )


def upgrade() -> None:
    """Add the rules table and the setting, and order each Automatic art choice."""
    op.create_table(
        "notification_rules",
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("failed", sa.Boolean(), nullable=False),
        sa.Column("stopped", sa.Boolean(), nullable=False),
        sa.Column("completed", _enum("notifycompleted", _COMPLETED), nullable=False),
        sa.Column("scheduled_only", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            _check("completed", _COMPLETED), name="ck_notification_rules_completed"
        ),
        sa.PrimaryKeyConstraint("kind"),
    )
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "auto_search_themes",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column("auto_search_themes", server_default=None)
    _retype_auto_art(_AUTO_ART, _UPGRADED, _OLD_AUTO_ART)
    _swap_drawing_flag("generated_textless", "generated_title_only")
    _restore_separators(op.get_bind())


def _swap_drawing_flag(old: str, new: str) -> None:
    """Replace one drawing flag with the other, which starts off.

    The two say different things, so neither converts into the other; each
    drawing is drawn again on the next sync with the flag off.
    """
    with op.batch_alter_table("art_slots") as batch:
        batch.drop_constraint(f"ck_art_slots_{old}", type_="check")
        batch.drop_column(old)
        batch.add_column(
            sa.Column(new, sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.create_check_constraint(
            f"ck_art_slots_{new}", f"NOT {new} OR generated_style IS NOT NULL"
        )
    with op.batch_alter_table("art_slots") as batch:
        batch.alter_column(new, server_default=None)


def downgrade() -> None:
    """Drop the rules and the setting; a source order becomes Match.

    Restored separators stay separators, which the older schema also knows.

    A choice of one source, or of TMDB first, has no older equivalent but
    Match, which tries every source.
    """
    downgraded = {
        value: ("match_or_draw" if value.endswith("draw") else "match")
        for value in _AUTO_ART
        if value not in {"off", "draw"}
    }
    _swap_drawing_flag("generated_title_only", "generated_textless")
    _retype_auto_art(_OLD_AUTO_ART, downgraded, _AUTO_ART)
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("auto_search_themes")
    op.drop_table("notification_rules")
