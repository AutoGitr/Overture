"""Cron collection schedules, member effects, TMDB facts and saved presets.

Revision ID: e6a1c2d3f4b5
Revises: b4e8c1d2f3a7
Create Date: 2026-10-27 15:10:38.827146

"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

revision: str = "e6a1c2d3f4b5"
down_revision: str | Sequence[str] | None = "b4e8c1d2f3a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The schedule a daily interval becomes, the new application default.
_DAILY = "0 3 * * *"
_SOURCE_SUMMARY = "{source_summary}"


def cron_for_hours(hours: int) -> str:
    """The cron schedule closest to running every *hours* hours."""
    if hours <= 0 or hours == 24:
        return _DAILY
    if hours < 24:
        step = max(divisor for divisor in (1, 2, 3, 4, 6, 8, 12) if divisor <= hours)
        return "0 * * * *" if step == 1 else f"0 */{step} * * *"
    if hours >= 168:
        return "0 3 * * 0"
    return f"0 3 */{hours // 24} * *"


def _hours_for_cron(schedule: str | None) -> int:
    """The interval a downgrade restores; anything else runs daily."""
    minute, hour, day, _, weekday = (schedule or _DAILY).split()
    if minute == "0" and day == "*" and weekday == "*":
        if hour == "*":
            return 1
        if hour.startswith("*/"):
            return int(hour[2:])
    if weekday != "*":
        return 168
    if day.startswith("*/"):
        return int(day[2:]) * 24
    return 24


def _without_biography(criteria: dict[str, Any]) -> bool:
    """Drop the person-source biography flag; return whether one was set."""
    found = False
    conditions: list[dict[str, Any]] = criteria.get("conditions", [])
    for condition in conditions:
        source: dict[str, Any] = condition.get("source") or {}
        found = bool(source.pop("use_biography", False)) or found
    groups: list[dict[str, Any]] = criteria.get("groups", [])
    for group in groups:
        found = _without_biography(group) or found
    return found


def _convert_settings(bind: sa.Connection) -> bool:
    """Convert the application interval; return its below-minimum default."""
    settings = bind.execute(
        sa.text(
            "SELECT collection_sync_interval_hours, collection_delete_below_minimum "
            "FROM app_settings"
        )
    ).first()
    delete_below_default = bool(settings[1]) if settings else False
    if settings is not None:
        bind.execute(
            sa.text(
                "UPDATE app_settings SET collection_sync_schedule = :schedule, "
                "collection_sync_enabled = collection_sync_enabled AND :hours > 0"
            ),
            {"schedule": cron_for_hours(int(settings[0])), "hours": int(settings[0])},
        )
    bind.execute(
        sa.text(
            "UPDATE app_settings SET tmdb_region = 'US', radarr_root_folder = '', "
            "sonarr_root_folder = ''"
        )
    )
    return delete_below_default


def _convert_rules(bind: sa.Connection) -> None:
    """Convert rule intervals and flags, and biography summaries."""
    biography_collections: set[int] = set()
    for rule_id, collection_id, hours, enabled, criteria_json in bind.execute(
        sa.text(
            "SELECT id, collection_id, sync_interval_hours, enabled, criteria_json "
            "FROM collection_rules"
        )
    ):
        criteria = json.loads(criteria_json)
        if _without_biography(criteria):
            biography_collections.add(collection_id)
        bind.execute(
            sa.text(
                "UPDATE collection_rules SET sync_schedule = :schedule, "
                "sync_enabled = :enabled, criteria_json = :criteria WHERE id = :id"
            ),
            {
                "schedule": cron_for_hours(int(hours)),
                # Enabled was the default; it now inherits.
                "enabled": None if enabled else False,
                "criteria": json.dumps(criteria),
                "id": rule_id,
            },
        )
    for collection_id in biography_collections:
        bind.execute(
            sa.text(
                "UPDATE media_collections SET summary_format = :summary "
                "WHERE id = :id AND summary_format IS NULL"
            ),
            {"summary": _SOURCE_SUMMARY, "id": collection_id},
        )


def _convert_groups(bind: sa.Connection, delete_below_default: bool) -> None:
    """Convert group intervals and set generators."""
    for group_id, hours, sync_enabled, delete_below, generator_json in bind.execute(
        sa.text(
            "SELECT id, sync_interval_hours, sync_enabled, delete_below_minimum, "
            "generator_json FROM collection_groups"
        )
    ):
        updates: dict[str, Any] = {
            "id": group_id,
            "schedule": None if hours is None else cron_for_hours(int(hours)),
            "enabled": sync_enabled,
            "generator": generator_json,
            "biography": False,
            "summary": _SOURCE_SUMMARY,
        }
        if generator_json:
            generator = json.loads(generator_json)
            generator["library_ids"] = [generator.pop("library_id")]
            if not generator.pop("enabled", True):
                updates["enabled"] = False
            # Vanished values were removed exactly when below-minimum ones were.
            generator["remove_vanished"] = bool(
                delete_below_default if delete_below is None else delete_below
            )
            updates["biography"] = _without_biography(generator.get("criteria") or {})
            updates["generator"] = json.dumps(generator)
        bind.execute(
            sa.text(
                "UPDATE collection_groups SET sync_schedule = :schedule, "
                "sync_enabled = :enabled, generator_json = :generator, "
                "summary_format = CASE WHEN :biography AND summary_format IS NULL "
                "THEN :summary ELSE summary_format END WHERE id = :id"
            ),
            updates,
        )


def upgrade() -> None:
    """Add the columns, then convert intervals, flags and set generators."""
    op.create_table(
        "collection_presets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "media_type",
            sa.Enum("movie", "show", name="mediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=False),
        sa.Column("payload_json", sa.String(), nullable=False),
        sa.Column("created_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_collection_presets_media_type"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_type", "label"),
    )
    with op.batch_alter_table("app_settings") as batch_op:
        for name, column in (
            ("collection_sync_schedule", sqlmodel.sql.sqltypes.AutoString(100)),
            ("tmdb_region", sqlmodel.sql.sqltypes.AutoString(2)),
            ("radarr_root_folder", sqlmodel.sql.sqltypes.AutoString(500)),
            ("sonarr_root_folder", sqlmodel.sql.sqltypes.AutoString(500)),
        ):
            batch_op.add_column(sa.Column(name, column, nullable=True))
        for name, default in (
            ("collection_request_missing", sa.false()),
            ("radarr_search", sa.true()),
            ("sonarr_search", sa.true()),
        ):
            batch_op.add_column(
                sa.Column(name, sa.Boolean(), nullable=False, server_default=default)
            )
        batch_op.add_column(sa.Column("radarr_quality_profile_id", sa.Integer()))
        batch_op.add_column(sa.Column("sonarr_quality_profile_id", sa.Integer()))
    for policy_table in ("collection_groups", "collection_rules"):
        with op.batch_alter_table(policy_table) as batch_op:
            batch_op.add_column(
                sa.Column("sync_schedule", sqlmodel.sql.sqltypes.AutoString())
            )
            if policy_table == "collection_rules":
                batch_op.add_column(sa.Column("sync_enabled", sa.Boolean()))
                batch_op.add_column(
                    sa.Column("source_summary", sqlmodel.sql.sqltypes.AutoString())
                )
            batch_op.add_column(sa.Column("request_missing", sa.Boolean()))
            batch_op.add_column(
                sa.Column("member_label", sqlmodel.sql.sqltypes.AutoString())
            )
            batch_op.add_column(
                sa.Column("arr_tag", sqlmodel.sql.sqltypes.AutoString())
            )
            batch_op.add_column(sa.Column("home_order", sa.Integer()))
    with op.batch_alter_table("media_items") as batch_op:
        for name in (
            "origin_countries",
            "tmdb_keywords",
            "companies",
            "networks",
            "streaming",
        ):
            batch_op.add_column(
                sa.Column(name, sa.JSON(), nullable=False, server_default="[]")
            )
        batch_op.add_column(sa.Column("versions", sa.Integer()))
        batch_op.add_column(
            sa.Column("original_language", sqlmodel.sql.sqltypes.AutoString())
        )
        batch_op.add_column(sa.Column("tmdb_rating", sa.Float()))
        batch_op.add_column(sa.Column("tmdb_votes", sa.Integer()))
        batch_op.add_column(
            sa.Column("show_status", sqlmodel.sql.sqltypes.AutoString())
        )
        batch_op.add_column(sa.Column("last_aired", sqlmodel.sql.sqltypes.AutoString()))
        batch_op.add_column(
            sa.Column("tmdb_checked_at", sqlmodel.sql.sqltypes.UTCDateTime())
        )
        # No check date makes the next sync read every title's new TMDB facts.
        batch_op.alter_column(
            "tmdb_collection_checked_id", new_column_name="tmdb_checked_id"
        )

    bind = op.get_bind()
    delete_below_default = _convert_settings(bind)
    _convert_rules(bind)
    _convert_groups(bind, delete_below_default)

    with op.batch_alter_table("app_settings") as batch_op:
        for name, length in (
            ("collection_sync_schedule", 100),
            ("tmdb_region", 2),
            ("radarr_root_folder", 500),
            ("sonarr_root_folder", 500),
        ):
            batch_op.alter_column(
                name,
                existing_type=sqlmodel.sql.sqltypes.AutoString(length),
                nullable=False,
            )
        for name in ("collection_request_missing", "radarr_search", "sonarr_search"):
            batch_op.alter_column(name, existing_type=sa.Boolean(), server_default=None)
        batch_op.drop_column("collection_sync_interval_hours")
    with op.batch_alter_table("collection_groups") as batch_op:
        batch_op.drop_column("sync_interval_hours")
    with op.batch_alter_table("collection_rules") as batch_op:
        batch_op.drop_column("enabled")
        batch_op.drop_column("sync_interval_hours")
    with op.batch_alter_table("media_items") as batch_op:
        for name in (
            "origin_countries",
            "tmdb_keywords",
            "companies",
            "networks",
            "streaming",
        ):
            batch_op.alter_column(name, existing_type=sa.JSON(), server_default=None)


def downgrade() -> None:
    """Restore intervals and flags; TMDB facts, member effects and presets are dropped.

    A cron schedule becomes the interval it repeats at, approximately.
    Collections that took a ``{source_summary}`` template keep it as text.
    """
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "collection_sync_interval_hours",
                sa.Integer(),
                nullable=False,
                server_default="24",
            )
        )
    with op.batch_alter_table("collection_groups") as batch_op:
        batch_op.add_column(sa.Column("sync_interval_hours", sa.Integer()))
    with op.batch_alter_table("collection_rules") as batch_op:
        batch_op.add_column(
            sa.Column(
                "sync_interval_hours", sa.Integer(), nullable=False, server_default="24"
            )
        )
        batch_op.add_column(
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true())
        )
    bind = op.get_bind()
    settings = bind.execute(
        sa.text("SELECT collection_sync_schedule FROM app_settings")
    ).first()
    if settings is not None:
        bind.execute(
            sa.text("UPDATE app_settings SET collection_sync_interval_hours = :hours"),
            {"hours": _hours_for_cron(settings[0])},
        )
    for table, rules in (("collection_rules", True), ("collection_groups", False)):
        for row_id, schedule, sync_enabled in bind.execute(
            sa.text(f"SELECT id, sync_schedule, sync_enabled FROM {table}")  # noqa: S608 -- fixed table names
        ):
            values: dict[str, Any] = {
                "id": row_id,
                # A rule always had an interval; a group inherited without one.
                "hours": None
                if schedule is None and not rules
                else _hours_for_cron(schedule),
            }
            assignments = "sync_interval_hours = :hours"
            if rules:
                values["enabled"] = sync_enabled is None or bool(sync_enabled)
                assignments += ", enabled = :enabled"
            bind.execute(
                sa.text(f"UPDATE {table} SET {assignments} WHERE id = :id"),  # noqa: S608 -- fixed table names
                values,
            )
    for group_id, generator_json in bind.execute(
        sa.text(
            "SELECT id, generator_json FROM collection_groups "
            "WHERE generator_json IS NOT NULL"
        )
    ):
        generator = json.loads(generator_json)
        generator["library_id"] = generator.pop("library_ids")[0]
        for name in ("custom_values", "aliases", "remove_vanished"):
            generator.pop(name, None)
        bind.execute(
            sa.text(
                "UPDATE collection_groups SET generator_json = :generator "
                "WHERE id = :id"
            ),
            {"generator": json.dumps(generator), "id": group_id},
        )
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.alter_column(
            "collection_sync_interval_hours",
            existing_type=sa.Integer(),
            server_default=None,
        )
        for name in (
            "collection_sync_schedule",
            "collection_request_missing",
            "tmdb_region",
            "radarr_root_folder",
            "radarr_quality_profile_id",
            "radarr_search",
            "sonarr_root_folder",
            "sonarr_quality_profile_id",
            "sonarr_search",
        ):
            batch_op.drop_column(name)
    for policy_table in ("collection_groups", "collection_rules"):
        with op.batch_alter_table(policy_table) as batch_op:
            names = [
                "sync_schedule",
                "request_missing",
                "member_label",
                "arr_tag",
                "home_order",
            ]
            if policy_table == "collection_rules":
                names += ["sync_enabled", "source_summary"]
                batch_op.alter_column(
                    "sync_interval_hours",
                    existing_type=sa.Integer(),
                    server_default=None,
                )
                batch_op.alter_column(
                    "enabled", existing_type=sa.Boolean(), server_default=None
                )
            for name in names:
                batch_op.drop_column(name)
    with op.batch_alter_table("media_items") as batch_op:
        batch_op.alter_column(
            "tmdb_checked_id", new_column_name="tmdb_collection_checked_id"
        )
        for name in (
            "versions",
            "original_language",
            "origin_countries",
            "tmdb_rating",
            "tmdb_votes",
            "tmdb_keywords",
            "companies",
            "networks",
            "streaming",
            "show_status",
            "last_aired",
            "tmdb_checked_at",
        ):
            batch_op.drop_column(name)
    op.drop_table("collection_presets")
