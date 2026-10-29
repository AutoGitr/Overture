"""Add the OvertureDB settings; sets remove vanished values with below-minimum ones.

Revision ID: d8b3f6a2c9e4
Revises: c5f9d3e7b1a2
Create Date: 2026-10-29 12:00:00.000000

"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "d8b3f6a2c9e4"
down_revision: str | Sequence[str] | None = "c5f9d3e7b1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SETTINGS = ("overturedb_no_theme", "overturedb_browse")


def _merge_removal(generator: dict[str, Any], delete_below: bool | None) -> bool | None:
    """Drop ``remove_vanished``; a set that used it now deletes below minimum."""
    if generator.pop("remove_vanished", False) and delete_below is None:
        return True
    return delete_below


def upgrade() -> None:
    """Both settings start on, as they behaved before they existed."""
    with op.batch_alter_table("app_settings") as batch:
        for name in _SETTINGS:
            batch.add_column(
                sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true())
            )
    with op.batch_alter_table("app_settings") as batch:
        for name in _SETTINGS:
            batch.alter_column(name, server_default=None)

    bind = op.get_bind()
    for identity, generator_json, delete_below in bind.execute(
        sa.text(
            "SELECT id, generator_json, delete_below_minimum FROM collection_groups "
            "WHERE generator_json IS NOT NULL"
        )
    ):
        generator = json.loads(generator_json)
        merged = _merge_removal(
            generator, None if delete_below is None else bool(delete_below)
        )
        bind.execute(
            sa.text(
                "UPDATE collection_groups SET generator_json = :generator, "
                "delete_below_minimum = :delete_below WHERE id = :id"
            ),
            {
                "generator": json.dumps(generator),
                "delete_below": merged,
                "id": identity,
            },
        )
    for identity, payload_json in bind.execute(
        sa.text("SELECT id, payload_json FROM collection_presets")
    ):
        payload = json.loads(payload_json)
        preset_set = payload.get("set")
        if not preset_set:
            continue
        policy = preset_set.setdefault("policy", {})
        policy["delete_below_minimum"] = _merge_removal(
            preset_set["generator"], policy.get("delete_below_minimum")
        )
        bind.execute(
            sa.text(
                "UPDATE collection_presets SET payload_json = :payload WHERE id = :id"
            ),
            {"payload": json.dumps(payload), "id": identity},
        )


def downgrade() -> None:
    """Sets remove vanished values exactly when they delete below-minimum ones."""
    with op.batch_alter_table("app_settings") as batch:
        for name in _SETTINGS:
            batch.drop_column(name)

    bind = op.get_bind()
    for identity, generator_json, delete_below in bind.execute(
        sa.text(
            "SELECT id, generator_json, delete_below_minimum FROM collection_groups "
            "WHERE generator_json IS NOT NULL"
        )
    ):
        generator = json.loads(generator_json)
        generator["remove_vanished"] = bool(delete_below)
        bind.execute(
            sa.text(
                "UPDATE collection_groups SET generator_json = :generator "
                "WHERE id = :id"
            ),
            {"generator": json.dumps(generator), "id": identity},
        )
    for identity, payload_json in bind.execute(
        sa.text("SELECT id, payload_json FROM collection_presets")
    ):
        payload = json.loads(payload_json)
        preset_set = payload.get("set")
        if not preset_set:
            continue
        policy: dict[str, Any] = preset_set.get("policy") or {}
        preset_set["generator"]["remove_vanished"] = bool(
            policy.get("delete_below_minimum")
        )
        bind.execute(
            sa.text(
                "UPDATE collection_presets SET payload_json = :payload WHERE id = :id"
            ),
            {"payload": json.dumps(payload), "id": identity},
        )
