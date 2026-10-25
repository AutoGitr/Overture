"""Persist collection template sources and unmanaged import preferences."""

import json
from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op

from overture.schemas.sync import SyncScheduleConfig
from overture.utils.collection_formats import format_summary, literal_template

revision: str = "5cff4899af03"
down_revision: str | Sequence[str] | None = "9a1b2c3d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Preserve existing literal overrides and capture the unrendered summary."""
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "collection_import_unmanaged",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
    with op.batch_alter_table("app_settings") as batch:
        batch.alter_column("collection_import_unmanaged", server_default=None)
    with op.batch_alter_table("media_collections") as batch:
        batch.add_column(
            sa.Column(
                "summary_source", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT c.id, c.title, c.collection_group, c.active_start_mmdd, "
            "c.active_end_mmdd, c.summary, c.sort_title, "
            "COALESCE(c.summary_format, r.summary_format) AS summary_format, "
            "COALESCE(c.sort_title_format, r.sort_title_format) AS sort_title_format "
            "FROM media_collections c LEFT JOIN collection_rules r "
            "ON r.collection_id=c.id"
        )
    ).mappings()
    for row in rows:
        summary_source = row["summary"]
        summary_format = row["summary_format"]
        if (
            summary_source is not None
            and summary_format
            and "{summary}" in summary_format
        ):
            marker = "\x00summary\x00"
            preview = format_summary(
                summary_format,
                title=row["title"],
                group=row["collection_group"],
                start_date=row["active_start_mmdd"],
                end_date=row["active_end_mmdd"],
                summary=marker,
            )
            parts = preview.split(marker)
            if (
                len(parts) == 2
                and summary_source.startswith(parts[0])
                and summary_source.endswith(parts[1])
                and len(summary_source) >= len(parts[0]) + len(parts[1])
            ):
                summary_source = summary_source[
                    len(parts[0]) : len(summary_source) - len(parts[1])
                ]
            else:
                # Keep displayed text when the original input cannot be recovered.
                summary_format = literal_template(summary_source)
        connection.execute(
            sa.text(
                "UPDATE media_collections SET summary_source=:summary, "
                "summary_format=:summary_format, sort_title_format=:sort_title_format "
                "WHERE id=:id"
            ),
            {
                "id": row["id"],
                "summary": summary_source,
                "summary_format": summary_format
                if summary_format is not None or row["summary"] is None
                else literal_template(row["summary"]),
                "sort_title_format": row["sort_title_format"]
                if row["sort_title_format"] is not None or row["sort_title"] is None
                else literal_template(row["sort_title"]),
            },
        )

    # Older forms wrote display overrides to the collection projection only.
    metadata = sa.MetaData()
    rules = sa.Table("collection_rules", metadata, autoload_with=connection)
    collections = sa.Table("media_collections", metadata, autoload_with=connection)
    for column in (
        "collection_mode",
        "order_type",
        "collection_filtering",
        "visible_home",
        "visible_shared",
        "visible_library",
    ):
        previous = (
            sa.select(collections.c[column])
            .where(collections.c.id == rules.c.collection_id)
            .scalar_subquery()
        )
        connection.execute(
            rules.update().values(
                {
                    column: sa.func.coalesce(rules.c[column], previous),
                }
            )
        )

    schedules = connection.execute(
        sa.text("SELECT id, payload_json FROM saved_schedules WHERE kind='sync'")
    ).mappings()
    for schedule in schedules:
        payload = SyncScheduleConfig.model_validate(
            json.loads(schedule["payload_json"])
        )
        connection.execute(
            sa.text("UPDATE saved_schedules SET payload_json=:payload WHERE id=:id"),
            {
                "id": schedule["id"],
                "payload": payload.model_dump_json(),
            },
        )


def downgrade() -> None:
    """Keep rendered metadata and expressions while removing the new columns."""
    connection = op.get_bind()
    schedules = connection.execute(
        sa.text("SELECT id, payload_json FROM saved_schedules WHERE kind='sync'")
    ).mappings()
    for schedule in schedules:
        payload = json.loads(schedule["payload_json"])
        payload.pop("include_collections", None)
        connection.execute(
            sa.text("UPDATE saved_schedules SET payload_json=:payload WHERE id=:id"),
            {"id": schedule["id"], "payload": json.dumps(payload)},
        )
    with op.batch_alter_table("media_collections") as batch:
        batch.drop_column("summary_source")
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("collection_import_unmanaged")
