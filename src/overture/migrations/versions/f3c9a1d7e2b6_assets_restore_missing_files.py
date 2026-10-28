"""Drop Retry saved downloads: every Assets run restores missing files.

Revision ID: f3c9a1d7e2b6
Revises: e6a1c2d3f4b5
Create Date: 2026-10-27 22:30:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3c9a1d7e2b6"
down_revision: str | Sequence[str] | None = "e6a1c2d3f4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Remove the option from saved Assets schedules."""
    connection = op.get_bind()
    schedules = connection.execute(
        sa.text("SELECT id, payload_json FROM saved_schedules WHERE kind='assets'")
    ).mappings()
    for schedule in schedules:
        payload = json.loads(schedule["payload_json"])
        if payload.pop("retry_saved_downloads", None) is None:
            continue
        connection.execute(
            sa.text("UPDATE saved_schedules SET payload_json=:payload WHERE id=:id"),
            {"id": schedule["id"], "payload": json.dumps(payload)},
        )


def downgrade() -> None:
    """Leave schedules as they are: the previous revision defaults the option off."""
