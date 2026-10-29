"""Groups own sync schedules; Assets runs combine libraries and collections.

Revision ID: e9c4a7b1d3f5
Revises: d8b3f6a2c9e4
Create Date: 2026-10-29 18:00:00.000000

"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "e9c4a7b1d3f5"
down_revision: str | Sequence[str] | None = "d8b3f6a2c9e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RULE_SCHEDULE = ("sync_schedule", "sync_enabled")


#: Each JSON payload this revision rewrites, as its SELECT and its UPDATE.
_ASSETS_SCHEDULES = (
    "SELECT id, payload_json FROM saved_schedules WHERE kind = 'assets'",
    "UPDATE saved_schedules SET payload_json = :payload WHERE id = :id",
)
_PRESETS = (
    "SELECT id, payload_json FROM collection_presets",
    "UPDATE collection_presets SET payload_json = :payload WHERE id = :id",
)


def _rewrite(statements: tuple[str, str], change: Any) -> None:
    """Apply *change* to every payload *statements* select, saving those it changes."""
    select, update = statements
    bind = op.get_bind()
    for identity, raw in bind.execute(sa.text(select)):
        payload = json.loads(raw)
        if change(payload):
            bind.execute(
                sa.text(update), {"payload": json.dumps(payload), "id": identity}
            )


def _combine_collections(payload: dict[str, Any]) -> bool:
    """A Themes run that included collections now selects every collection."""
    themes: dict[str, Any] | None = payload.get("themes")
    if not themes or "include_collections" not in themes:
        return False
    included = bool(themes.pop("include_collections"))
    scoped = payload.get("all_collections") or payload.get("collection_groups")
    if included and not scoped and payload.get("item_ids") is None:
        payload["all_collections"] = True
    return True


def _drop_rule_schedule(payload: dict[str, Any]) -> bool:
    """A preset's collection rule no longer carries its own schedule."""
    collection: dict[str, Any] = payload.get("collection") or {}
    rule: dict[str, Any] | None = collection.get("rule")
    if not rule or not set(_RULE_SCHEDULE) & set(rule):
        return False
    for name in _RULE_SCHEDULE:
        rule.pop(name, None)
    return True


def upgrade() -> None:
    """Collections follow their group's schedule, and groups are required.

    Requiring a group became the default, so the existing row turns it on too.
    """
    with op.batch_alter_table("collection_rules") as batch:
        for name in _RULE_SCHEDULE:
            batch.drop_column(name)
    _rewrite(_ASSETS_SCHEDULES, _combine_collections)
    _rewrite(_PRESETS, _drop_rule_schedule)
    op.execute("UPDATE app_settings SET collection_require_group = 1")


def _split_collections(payload: dict[str, Any]) -> bool:
    """Libraries beside collections become libraries with collection themes.

    The earlier schema ran one scope; collection art beside libraries is dropped.
    """
    themes: dict[str, Any] | None = payload.get("themes")
    if themes is not None:
        themes.setdefault("include_collections", False)
    if not payload.get("library_ids") or not (
        payload.get("all_collections") or payload.get("collection_groups")
    ):
        return themes is not None
    payload.pop("all_collections", None)
    payload.pop("collection_groups", None)
    if themes is not None:
        themes["include_collections"] = True
    return True


def downgrade() -> None:
    """Rules inherit their schedule again, and Assets runs pick one scope."""
    with op.batch_alter_table("collection_rules") as batch:
        batch.add_column(sa.Column("sync_schedule", sa.String(), nullable=True))
        batch.add_column(sa.Column("sync_enabled", sa.Boolean(), nullable=True))
    _rewrite(_ASSETS_SCHEDULES, _split_collections)
