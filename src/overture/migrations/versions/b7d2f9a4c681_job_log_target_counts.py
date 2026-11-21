"""Count a run's outcomes only from its log: per line and per target.

A log line can sum up several targets that share an outcome and reason, and
says how many. A run's summary counts its log's targets per outcome
(``log_targets``) instead of keeping a counter field per outcome. A stored
summary's counters were exactly those target counts, so they become its
``log_targets``; an outcome without a counter keeps its line count.

Revision ID: b7d2f9a4c681
Revises: a1f6c3e8d590
Create Date: 2026-11-20 17:00:00.000000

"""

import json
from collections.abc import Callable, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "b7d2f9a4c681"
down_revision: str | Sequence[str] | None = "a1f6c3e8d590"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ASSETS_COUNTERS = {
    "queued": "Queued",
    "downloaded": "Downloaded",
    "adopted": "Adopted",
    "skipped": "Skipped",
    "no_match": "No match",
    "errors": "Error",
}

#: Each job kind's counter fields, by the outcome whose targets they counted.
_COUNTERS: dict[str, dict[str, str]] = {
    "sync": {
        "added": "Added",
        "updated": "Updated",
        "unchanged": "Unchanged",
        "removed": "Removed",
        "errors": "Error",
    },
    "bulk_art": _ASSETS_COUNTERS,
    "bulk_theme": _ASSETS_COUNTERS,
    "server_audit_fix": {
        "verified": "Matched",
        "unchanged": "Mismatch",
        "errors": "Error",
    },
    "server_audit": {"errors": "Error"},
    "asset_scan": {"errors": "Error"},
}


def _rewrite_summaries(change: Callable[[str, dict[str, Any]], None]) -> None:
    connection = op.get_bind()
    for run_id, kind, summary in connection.execute(
        sa.text("SELECT id, kind, summary FROM job_runs")
    ).all():
        stored = json.loads(summary)
        change(kind, stored)
        connection.execute(
            sa.text("UPDATE job_runs SET summary = :summary WHERE id = :id"),
            {"summary": json.dumps(stored), "id": run_id},
        )


def upgrade() -> None:
    def count_targets(kind: str, summary: dict[str, Any]) -> None:
        targets = dict(summary.get("log_outcomes") or {})
        for field, outcome in _COUNTERS.get(kind, {}).items():
            if (count := summary.pop(field, None)) is not None:
                targets[outcome] = count
        summary["log_targets"] = {
            outcome: count for outcome, count in targets.items() if count
        }

    _rewrite_summaries(count_targets)


def downgrade() -> None:
    def restore_counters(kind: str, summary: dict[str, Any]) -> None:
        targets: dict[str, int] = summary.pop("log_targets", None) or {}
        for field, outcome in _COUNTERS.get(kind, {}).items():
            summary[field] = targets.get(outcome, 0)
        if isinstance(summary.get("log"), dict):
            summary["log"].pop("count", None)

    _rewrite_summaries(restore_counters)
    # The earlier entries name no count, and the earlier app refuses one.
    op.execute("UPDATE job_log_lines SET entry = json_remove(entry, '$.count')")
