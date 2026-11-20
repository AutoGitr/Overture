"""Name the collections criteria test by ID rather than by title.

A **Collection** condition named a collection by its title, so renaming the
collection left the condition testing a title no collection has. It now holds
the collection's ID. Each stored title becomes the ID of the listed collection
with that title, among those in the criteria's libraries, as the criteria
matched it: a title several collections share becomes a group testing each of
them, and one no collection has becomes an ID no collection has.

Revision ID: d7b3e9a1c524
Revises: c4f8a2e6b913
Create Date: 2026-11-18 21:10:00.000000

"""

import json
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

revision: str = "d7b3e9a1c524"
down_revision: str | Sequence[str] | None = "c4f8a2e6b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The ID a title no collection has becomes; no collection is numbered 0.
_NONE = "0"

#: Each listed collection's ID with its title.
type Titles = Mapping[int, str]
#: Rewrites one Collection condition into the conditions or group it becomes.
type Rewrite = Callable[[dict[str, Any]], dict[str, Any]]


def _rewrite(group: dict[str, Any], rewrite: Rewrite) -> dict[str, Any]:
    """Return *group* with every Collection condition, nested ones too, rewritten."""
    conditions: list[dict[str, Any]] = []
    groups = [_rewrite(nested, rewrite) for nested in group.get("groups", [])]
    for condition in group.get("conditions", []):
        if condition.get("kind") == "field" and condition.get("field") == "collection":
            rewritten = rewrite(condition)
            if rewritten.get("kind") == "field":
                conditions.append(rewritten)
            else:
                groups.append(rewritten)
        else:
            conditions.append(condition)
    return {**group, "conditions": conditions, "groups": groups}


def _by_id(titles: Titles) -> Rewrite:
    def rewrite(condition: dict[str, Any]) -> dict[str, Any]:
        wanted = str(condition["value"]).casefold()
        ids = sorted(
            collection_id
            for collection_id, title in titles.items()
            if title.casefold() == wanted
        )
        if len(ids) <= 1:
            return {**condition, "value": str(ids[0]) if ids else _NONE}
        # A title tested every collection holding it; "is not" excluded each.
        negated = condition.get("operator") == "is_not"
        return {
            "mode": "all" if negated else "any",
            "conditions": [{**condition, "value": str(i)} for i in ids],
            "groups": [],
        }

    return rewrite


def _by_title(titles: Titles) -> Rewrite:
    def rewrite(condition: dict[str, Any]) -> dict[str, Any]:
        value = str(condition["value"])
        title = titles.get(int(value)) if value.isdecimal() else None
        return {**condition, "value": title if title is not None else value}

    return rewrite


def _convert(by: Callable[[Titles], Rewrite]) -> None:
    connection = op.get_bind()
    titles: dict[int, str] = dict(
        connection.execute(
            sa.text(
                "SELECT id, title FROM media_collections "
                "WHERE last_synced_at IS NOT NULL"
            )
        ).all()
    )
    in_library: dict[str, set[int]] = {}
    for collection_id, library_id in connection.execute(
        sa.text("SELECT collection_id, library_id FROM collection_libraries")
    ):
        in_library.setdefault(library_id, set()).add(collection_id)

    def scope(library_ids: Sequence[str]) -> Titles:
        held = set[int]().union(*(in_library.get(i, set()) for i in library_ids))
        return {key: title for key, title in titles.items() if key in held}

    for part_id, library_id, criteria in connection.execute(
        sa.text(
            "SELECT id, library_id, criteria FROM collection_libraries "
            "WHERE criteria IS NOT NULL"
        )
    ):
        converted = _rewrite(json.loads(criteria), by(scope([library_id])))
        connection.execute(
            sa.text("UPDATE collection_libraries SET criteria = :c WHERE id = :id"),
            {"c": json.dumps(converted), "id": part_id},
        )
    for filter_id, criteria in connection.execute(
        sa.text("SELECT id, criteria FROM saved_filters")
    ):
        converted = _rewrite(json.loads(criteria), by(titles))
        connection.execute(
            sa.text("UPDATE saved_filters SET criteria = :c WHERE id = :id"),
            {"c": json.dumps(converted), "id": filter_id},
        )
    for group_id, generator in connection.execute(
        sa.text(
            "SELECT id, generator FROM collection_groups WHERE generator IS NOT NULL"
        )
    ):
        stored = json.loads(generator)
        rewrite = by(scope(stored.get("library_ids", [])))
        stored["criteria"] = _rewrite(stored.get("criteria", {}), rewrite)
        stored["custom_values"] = [
            {**value, "criteria": _rewrite(value["criteria"], rewrite)}
            for value in stored.get("custom_values", [])
        ]
        connection.execute(
            sa.text("UPDATE collection_groups SET generator = :g WHERE id = :id"),
            {"g": json.dumps(stored), "id": group_id},
        )


def upgrade() -> None:
    _convert(_by_id)


def downgrade() -> None:
    """Name each collection by its title again; a missing one keeps its ID.

    A group a shared title became stays a group, testing that title in each.
    """
    _convert(_by_title)
