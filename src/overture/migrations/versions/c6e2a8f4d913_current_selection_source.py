"""Make an Assets run's current selection a step of its source orders.

Revision ID: c6e2a8f4d913
Revises: 2d3465b91d26
Create Date: 2026-11-23 18:00:00.000000

A saved Assets schedule kept what a slot holds unless ``overwrite_existing``
was on, which let every source replace it. Its art and theme source orders
now hold ``current_selection``: first keeps what a slot holds, as the switch
off did, and last lets every source replace it, as the switch on did.
"""

import json
from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "c6e2a8f4d913"
down_revision: str | Sequence[str] | None = "2d3465b91d26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CURRENT = "current_selection"
#: Each workflow of a schedule's payload that holds a source order, with
#: every source it had before this revision.
_WORKFLOWS = {
    "art": ["overturedb", "local_art_matching"],
    "themes": ["overturedb", "themerrdb", "youtube_search"],
}


def _convert(convert: Callable[[dict[str, Any]], None]) -> None:
    """Rewrite each saved Assets schedule's payload with *convert*."""
    conn = op.get_bind()
    for schedule_id, stored in conn.execute(
        sa.text("SELECT id, payload FROM saved_schedules WHERE kind = 'assets'")
    ).all():
        payload: dict[str, Any] = json.loads(stored)
        convert(payload)
        conn.execute(
            sa.text("UPDATE saved_schedules SET payload = :payload WHERE id = :id"),
            {"payload": json.dumps(payload), "id": schedule_id},
        )


def _add_current(payload: dict[str, Any]) -> None:
    replace = bool(payload.pop("overwrite_existing", False))
    for workflow in _WORKFLOWS:
        if (config := payload.get(workflow)) is not None:
            order: list[str] = config["source_order"]
            config["source_order"] = (
                [*order, _CURRENT] if replace else [_CURRENT, *order]
            )


def _drop_current(payload: dict[str, Any]) -> None:
    # The switch let every source replace what a slot holds, so a source above
    # Current selection in either order turns it on for the whole schedule.
    # An order of Current selection alone, which only kept what slots hold,
    # had no form: it takes every source, kept from replacing.
    replace = False
    for workflow, every in _WORKFLOWS.items():
        if (config := payload.get(workflow)) is not None:
            order: list[str] = config["source_order"]
            replace = replace or order.index(_CURRENT) > 0
            sources = [step for step in order if step != _CURRENT]
            config["source_order"] = sources or every
    payload["overwrite_existing"] = replace


def upgrade() -> None:
    _convert(_add_current)


def downgrade() -> None:
    _convert(_drop_current)
