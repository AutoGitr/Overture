"""Keep what each schedule's last run did; incremental polls report there too.

Revision ID: a7d2e9c4f1b3
Revises: f3c9a1d7e2b6
Create Date: 2026-10-27 23:00:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d2e9c4f1b3"
down_revision: str | Sequence[str] | None = "f3c9a1d7e2b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The last-poll figures an incremental schedule's state kept, and the names
#: its run summary counts them under.
_POLL_COUNTS = {"last_items_added": "added", "last_downloads": "queued"}


def upgrade() -> None:
    """Move the last poll's figures out of incremental schedule state."""
    with op.batch_alter_table("saved_schedules") as batch_op:
        batch_op.add_column(sa.Column("last_run_json", sa.JSON(), nullable=True))
    connection = op.get_bind()
    schedules = connection.execute(
        sa.text("SELECT id, state_json FROM saved_schedules WHERE kind='sync'")
    ).mappings()
    for schedule in schedules:
        state = json.loads(schedule["state_json"])
        duration = state.pop("last_duration_seconds", None)
        counts = {
            name: count
            for key, name in _POLL_COUNTS.items()
            if (count := state.pop(key, None))
        }
        summary = (
            {"duration_seconds": duration, "counts": counts, "failed": False}
            if duration is not None
            else None
        )
        connection.execute(
            sa.text(
                "UPDATE saved_schedules SET state_json=:state, last_run_json=:summary "
                "WHERE id=:id"
            ),
            {
                "id": schedule["id"],
                "state": json.dumps(state),
                "summary": None if summary is None else json.dumps(summary),
            },
        )


def downgrade() -> None:
    """Put an incremental schedule's last run back into its state."""
    connection = op.get_bind()
    schedules = connection.execute(
        sa.text(
            "SELECT id, state_json, last_run_json FROM saved_schedules "
            "WHERE kind='sync' AND last_run_json IS NOT NULL"
        )
    ).mappings()
    for schedule in schedules:
        state = json.loads(schedule["state_json"])
        if "checkpoint" not in state:
            continue
        summary = json.loads(schedule["last_run_json"])
        state["last_duration_seconds"] = summary.get("duration_seconds")
        for key, name in _POLL_COUNTS.items():
            state[key] = summary.get("counts", {}).get(name, 0)
        connection.execute(
            sa.text("UPDATE saved_schedules SET state_json=:state WHERE id=:id"),
            {"id": schedule["id"], "state": json.dumps(state)},
        )
    with op.batch_alter_table("saved_schedules") as batch_op:
        batch_op.drop_column("last_run_json")
