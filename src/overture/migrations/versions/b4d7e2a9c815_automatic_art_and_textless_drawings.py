"""Automatic art is one choice, and collections may need no background.

Collections sync on their groups' Sync schedules.

Revision ID: b4d7e2a9c815
Revises: c9e4f1b7a2d3
Create Date: 2026-11-10 12:00:00.000000

"""

import json
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "b4d7e2a9c815"
down_revision: str | Sequence[str] | None = "c9e4f1b7a2d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_AUTO_ART = ("off", "match", "match_or_draw", "draw")
_STYLES = ("dark", "light", "accent")
_POLICY_TABLES = ("collection_rules", "collection_groups")


def _enum(name: str, values: tuple[str, ...]) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False)


def _check(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(f"'{value}'" for value in values)})"


def _auto_art(match: object, draw: object) -> str:
    """The one choice a matching and a drawing switch made together."""
    if match and draw:
        return "match_or_draw"
    if match:
        return "match"
    return "draw" if draw else "off"


def _convert_auto_art(conn: sa.Connection) -> None:
    """Combine each tier's two switches, reading a missing one from the tier above.

    A group or collection that set either switch keeps exactly what the pair
    resolved to; one that set neither still inherits.
    """
    match, draw = conn.exec_driver_sql(
        "SELECT collection_auto_match_art, collection_auto_generate_art "
        "FROM app_settings"
    ).one_or_none() or (False, False)
    conn.exec_driver_sql(
        "UPDATE app_settings SET collection_auto_art = ?", (_auto_art(match, draw),)
    )
    groups: dict[int, tuple[object, object]] = {}
    for group_id, group_match, group_draw in conn.exec_driver_sql(
        "SELECT id, auto_match_art, auto_generate_art FROM collection_groups"
    ).all():
        resolved = (
            match if group_match is None else group_match,
            draw if group_draw is None else group_draw,
        )
        groups[group_id] = resolved
        if group_match is not None or group_draw is not None:
            conn.exec_driver_sql(
                "UPDATE collection_groups SET auto_art = ? WHERE id = ?",
                (_auto_art(*resolved), group_id),
            )
    for rule_id, group_id, rule_match, rule_draw in conn.exec_driver_sql(
        "SELECT r.id, c.group_id, r.auto_match_art, r.auto_generate_art "
        "FROM collection_rules r JOIN media_collections c ON c.id = r.collection_id "
        "WHERE r.auto_match_art IS NOT NULL OR r.auto_generate_art IS NOT NULL"
    ).all():
        inherited = groups.get(group_id, (match, draw))
        conn.exec_driver_sql(
            "UPDATE collection_rules SET auto_art = ? WHERE id = ?",
            (
                _auto_art(
                    inherited[0] if rule_match is None else rule_match,
                    inherited[1] if rule_draw is None else rule_draw,
                ),
                rule_id,
            ),
        )


def _schedule_collection_syncs(conn: sa.Connection) -> None:
    """Keep each scheduled collection sync as a Sync schedule of its groups.

    Groups that synced on the same cron share one schedule; a group that never
    saved its own policy followed the application's, as Ungrouped did.
    """
    enabled, cron = conn.exec_driver_sql(
        "SELECT collection_sync_enabled, collection_sync_schedule FROM app_settings"
    ).one_or_none() or (False, "0 3 * * *")
    by_cron: dict[str, set[str]] = {}
    if enabled:
        by_cron.setdefault(cron, set()).add("Ungrouped")
    for name, group_enabled, group_cron in conn.exec_driver_sql(
        "SELECT name, sync_enabled, sync_schedule FROM collection_groups"
    ).all():
        if enabled if group_enabled is None else group_enabled:
            by_cron.setdefault(group_cron or cron, set()).add(name)
        else:
            for names in by_cron.values():
                names.discard(name)
    taken = {
        name
        for (name,) in conn.exec_driver_sql(
            "SELECT name FROM saved_schedules WHERE kind = 'sync'"
        ).all()
    }
    now = datetime.now(UTC).replace(tzinfo=None).isoformat(sep=" ")
    for cron_expression, names in sorted(by_cron.items()):
        if not names:
            continue
        name = (
            "Collections" if len(by_cron) == 1 else f"Collections ({cron_expression})"
        )
        while name in taken:
            name += " (collections)"
        taken.add(name)
        payload = {
            "include_collections": False,
            "collection_groups": sorted(names),
            "items": False,
            "mode": "full",
            "library_ids": [],
            "download_overturedb_art": False,
            "download_themes": "off",
        }
        conn.exec_driver_sql(
            "INSERT INTO saved_schedules (kind, name, enabled, cron_expression, "
            "payload, state, created_at, updated_at) VALUES "
            "('sync', ?, 1, ?, ?, '{}', ?, ?)",
            (name, cron_expression, json.dumps(payload), now, now),
        )


def upgrade() -> None:
    """Add the new choices, convert the old ones, then drop them."""
    with op.batch_alter_table("art_slots") as batch:
        batch.add_column(
            sa.Column(
                "generated_textless",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.create_check_constraint(
            "ck_art_slots_generated_textless",
            "NOT generated_textless OR generated_style IS NOT NULL",
        )
    with op.batch_alter_table("art_slots") as batch:
        batch.alter_column("generated_textless", server_default=None)
    for table in _POLICY_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(
                sa.Column("auto_art", _enum("autoart", _AUTO_ART), nullable=True)
            )
            batch.add_column(
                sa.Column("drawn_style", _enum("artstyle", _STYLES), nullable=True)
            )
            batch.add_column(sa.Column("backgrounds", sa.Boolean(), nullable=True))
            batch.create_check_constraint(
                f"ck_{table}_auto_art", _check("auto_art", _AUTO_ART)
            )
            batch.create_check_constraint(
                f"ck_{table}_drawn_style", _check("drawn_style", _STYLES)
            )
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "collection_auto_art",
                _enum("autoart", _AUTO_ART),
                nullable=False,
                server_default="off",
            )
        )
        batch.add_column(
            sa.Column(
                "collection_drawn_style",
                _enum("artstyle", _STYLES),
                nullable=False,
                server_default="dark",
            )
        )
        batch.add_column(
            sa.Column(
                "collection_backgrounds",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
        batch.create_check_constraint(
            "ck_app_settings_collection_auto_art",
            _check("collection_auto_art", _AUTO_ART),
        )
        batch.create_check_constraint(
            "ck_app_settings_collection_drawn_style",
            _check("collection_drawn_style", _STYLES),
        )

    conn = op.get_bind()
    _convert_auto_art(conn)
    _schedule_collection_syncs(conn)

    with op.batch_alter_table("app_settings") as batch:
        for column in ("collection_auto_art", "collection_drawn_style"):
            batch.alter_column(column, server_default=None)
        batch.alter_column("collection_backgrounds", server_default=None)
        for column in (
            "collection_auto_match_art",
            "collection_auto_generate_art",
            "collection_sync_schedule",
            "collection_sync_enabled",
        ):
            batch.drop_column(column)
    for table in _POLICY_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_column("auto_match_art")
            batch.drop_column("auto_generate_art")
    with op.batch_alter_table("collection_groups") as batch:
        batch.drop_column("sync_schedule")
        batch.drop_column("sync_enabled")


_SPLIT_APPLICATION_AUTO_ART = (
    "UPDATE app_settings SET "
    "collection_auto_match_art = collection_auto_art IN ('match', 'match_or_draw'), "
    "collection_auto_generate_art = collection_auto_art IN ('draw', 'match_or_draw')"
)
_SPLIT_AUTO_ART = (
    _SPLIT_APPLICATION_AUTO_ART,
    *(
        f"UPDATE {table} SET auto_match_art = auto_art IN ('match', 'match_or_draw'), "  # noqa: S608 -- the two fixed policy tables
        "auto_generate_art = auto_art IN ('draw', 'match_or_draw') "
        "WHERE auto_art IS NOT NULL"
        for table in _POLICY_TABLES
    ),
)


def downgrade() -> None:
    """Split automatic art back into its two switches.

    Drawn style, backgrounds and textless drawings have no earlier column:
    drawn art is dark again, a textless drawing is drawn with its title the
    next time it is drawn, and every collection wants a background. The Sync
    schedules made for collection groups stay, as schedules anyone could save,
    and the per-group schedules come back off.
    """
    with op.batch_alter_table("collection_groups") as batch:
        batch.add_column(sa.Column("sync_schedule", sa.String(), nullable=True))
        batch.add_column(sa.Column("sync_enabled", sa.Boolean(), nullable=True))
    for table in _POLICY_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("auto_match_art", sa.Boolean(), nullable=True))
            batch.add_column(
                sa.Column("auto_generate_art", sa.Boolean(), nullable=True)
            )
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "collection_auto_match_art",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "collection_auto_generate_art",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch.add_column(
            sa.Column(
                "collection_sync_schedule",
                sa.String(length=100),
                nullable=False,
                server_default="0 3 * * *",
            )
        )
        batch.add_column(
            sa.Column(
                "collection_sync_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
    for statement in _SPLIT_AUTO_ART:
        op.execute(statement)
    with op.batch_alter_table("app_settings") as batch:
        for column in (
            "collection_auto_match_art",
            "collection_auto_generate_art",
            "collection_sync_schedule",
            "collection_sync_enabled",
        ):
            batch.alter_column(column, server_default=None)
        batch.drop_constraint("ck_app_settings_collection_auto_art", type_="check")
        batch.drop_constraint("ck_app_settings_collection_drawn_style", type_="check")
        batch.drop_column("collection_auto_art")
        batch.drop_column("collection_drawn_style")
        batch.drop_column("collection_backgrounds")
    for table in _POLICY_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_auto_art", type_="check")
            batch.drop_constraint(f"ck_{table}_drawn_style", type_="check")
            batch.drop_column("auto_art")
            batch.drop_column("drawn_style")
            batch.drop_column("backgrounds")
    with op.batch_alter_table("art_slots") as batch:
        batch.drop_constraint("ck_art_slots_generated_textless", type_="check")
        batch.drop_column("generated_textless")
