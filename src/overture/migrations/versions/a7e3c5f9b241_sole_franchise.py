"""A collection is the TMDB franchise its criteria select alone, not their lowest.

Revision ID: a7e3c5f9b241
Revises: d2f8a4c6e913
Create Date: 2026-11-27 12:00:00.000000

Collections whose criteria name several franchises, such as a universe, took
the lowest-numbered one as theirs. They keep none, so a franchise set makes
each franchise's collection beside them, and the art and theme the franchise
has stay with the franchise.
"""

import json
from collections.abc import Iterator, Sequence
from typing import Any

from alembic import op

revision: str = "a7e3c5f9b241"
down_revision: str | Sequence[str] | None = "d2f8a4c6e913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _franchises(group: dict[str, Any]) -> Iterator[int]:
    """The TMDB franchises a stored filter group selects, as the app reads it."""
    conditions: list[dict[str, Any]] = group.get("conditions") or []
    for condition in conditions:
        source: dict[str, Any] = condition.get("source") or {}
        if (
            condition.get("kind") == "source"
            and condition.get("operator", "is") == "is"
            and source.get("type") == "tmdb_collection"
        ):
            yield int(source["collection_id"])
    children: list[dict[str, Any]] = group.get("groups") or []
    for child in children:
        yield from _franchises(child)


def upgrade() -> None:
    conn = op.get_bind()
    named: dict[int, set[int]] = {}
    for collection_id, criteria in conn.exec_driver_sql(
        "SELECT collection_id, criteria FROM collection_libraries "
        "WHERE criteria IS NOT NULL"
    ):
        named.setdefault(collection_id, set()).update(_franchises(json.loads(criteria)))
    for collection_id, franchises in named.items():
        if len(franchises) > 1:
            conn.exec_driver_sql(
                "UPDATE media_collections SET tmdb_collection_id = NULL "
                "WHERE id = ? AND tmdb_collection_id = ?",
                (collection_id, min(franchises)),
            )


def downgrade() -> None:
    """The franchises stay cleared: a collection's next criteria save sets one."""
