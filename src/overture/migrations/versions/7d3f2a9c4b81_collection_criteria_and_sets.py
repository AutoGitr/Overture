"""Collection criteria trees, collection sets, unified orders and item metadata.

Revision ID: 7d3f2a9c4b81
Revises: 5cff4899af03
Create Date: 2026-10-26 19:12:09.837829

"""

import json
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
import sqlmodel.sql.sqltypes
from alembic import op
from pydantic import ValidationError
from sqlalchemy.dialects import sqlite

from overture.domain import CollectionOrder, FieldKind, FilterField, SetDimension
from overture.schemas.collections import (
    FieldCondition,
    FilterGroup,
)
from overture.services.collections.fields import FIELDS

revision: str = "7d3f2a9c4b81"
down_revision: str | Sequence[str] | None = "5cff4899af03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_ORDERS = ("release", "alpha", "custom")
_ORDERS = {"release": "release.asc", "alpha": "title.asc", "custom": "custom"}
#: Smart sorts keep their names, except the rating Plex calls critic rating.
_SMART_SORTS = {"rating.desc": "critic_rating.desc"}
#: (table, column, nullable) of every collection order.
_ORDER_COLUMNS = (
    ("app_settings", "collection_order_default", False),
    ("collection_groups", "order_type", True),
    ("collection_rules", "order_type", True),
    ("media_collections", "order_type", False),
)
_FIELD_NAMES = {
    "tag": "label",
    "rating": "critic_rating",
    "duration_minutes": "duration",
}
_WITHIN_DAYS = {"added_within_days": "added", "released_within_days": "released"}
#: Text operators on fields that now hold tags keep their nearest meaning.
_TAG_OPERATORS = {"contains": "is", "starts_with": "is", "does_not_contain": "is_not"}


def _order_type(values: Sequence[str]) -> sa.Enum:
    return sa.Enum(*values, name="collectionorder", native_enum=False)


def _check(column: str, values: Sequence[str]) -> str:
    return f"{column} IN ({', '.join(repr(value) for value in values)})"


def _field_condition(raw: dict[str, Any]) -> dict[str, Any] | None:
    field, operator, value = raw["field"], raw.get("operator", "is"), raw["value"]
    if field in _WITHIN_DAYS:
        field, operator = _WITHIN_DAYS[field], "in_last"
    field = _FIELD_NAMES.get(field, field)
    kind = FIELDS[FilterField(field)].kind
    if kind is FieldKind.BOOLEAN and isinstance(value, str | int | float):
        value = str(value).strip().casefold() in {"1", "true", "yes"}
    if kind is FieldKind.TAG:
        operator = _TAG_OPERATORS.get(operator, operator)
    try:
        condition = FieldCondition.model_validate(
            {"field": field, "operator": operator, "value": value}
        )
    except ValidationError:
        # Only empty values fail, which never selected anything on purpose.
        return None
    return condition.model_dump(mode="json")


def _group(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": raw.get("mode", "all"),
        "conditions": [
            condition
            for entry in raw.get("conditions", [])
            if (condition := _field_condition(entry)) is not None
        ],
        "groups": [_group(group) for group in raw.get("groups", [])],
    }


def _all(*groups: dict[str, Any] | None) -> dict[str, Any]:
    present = [
        group
        for group in groups
        if group is not None and (group["conditions"] or group["groups"])
    ]
    if len(present) == 1:
        return present[0]
    return {"mode": "all", "conditions": [], "groups": present}


def _builders(builders: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Builders added their results together, so they become an any-group."""
    sources = [
        {"kind": "source", "operator": "is", "source": builder}
        for builder in builders
        if builder["type"] != "library_filter"
    ]
    filters = [
        _group(builder["filter_group"])
        for builder in builders
        if builder["type"] == "library_filter"
    ]
    if not sources and not filters:
        return None
    if len(sources) + len(filters) == 1:
        return filters[0] if filters else {"mode": "all", "conditions": sources}
    return {"mode": "any", "conditions": sources, "groups": filters}


def _criteria(row: dict[str, Any]) -> tuple[str | None, bool, int | None, str | None]:
    """Return a rule's criteria, whether it is smart, its limit and smart sort."""
    builders = _builders(json.loads(row["builders_json"] or "[]"))
    if not row["smart_filter_json"]:
        criteria = builders
        smart, limit, sort = False, None, None
    else:
        smart_filter = json.loads(row["smart_filter_json"])
        label = (
            {
                "mode": "all",
                "conditions": [
                    {
                        "kind": "field",
                        "field": "label",
                        "operator": "is",
                        "value": row["managed_label"],
                    }
                ],
            }
            if row["managed_label"] and builders is None
            else None
        )
        criteria = _all(_group(smart_filter.get("filter_group", {})), builders, label)
        smart, limit = True, smart_filter.get("limit")
        sort = smart_filter.get("sort_by", "release.desc")
        sort = _SMART_SORTS.get(sort, sort)
    if criteria is None or not (criteria["conditions"] or criteria.get("groups")):
        return None, smart, limit, sort
    return FilterGroup.model_validate(criteria).model_dump_json(), smart, limit, sort


def _generator(raw: str) -> str:
    """The generator as this revision stored it; later revisions convert it."""
    config = json.loads(raw)
    return json.dumps(
        {
            "dimension": SetDimension.FRANCHISE.value,
            "include": [],
            "exclude": [str(tmdb_id) for tmdb_id in config.get("exclude_tmdb_ids", [])],
            "top": None,
            "title_format": "{value}",
            "strip_prefix": config.get("strip_prefix", ""),
            "strip_suffix": config.get("strip_suffix", ""),
            "criteria": {"mode": "all", "conditions": [], "groups": []},
            "smart": False,
            "enabled": config.get("enabled", True),
            "library_id": config["library_id"],
        }
    )


_PREVIOUS_FIELDS = frozenset(
    {
        *("title", "genre", "studio", "actor", "director", "writer", "producer"),
        *("country", "label", "content_rating", "resolution", "year", "decade"),
        *("rating", "duration_minutes", "unplayed", "in_progress"),
    }
)
_PREVIOUS_OPERATORS = frozenset(
    {"is", "is_not", "contains", "does_not_contain", "starts_with", "gte", "lte"}
)
_PREVIOUS_SORTS = frozenset(
    {
        *("release.desc", "release.asc", "title.asc", "title.desc", "added.desc"),
        *("added.asc", "critic_rating.desc", "audience_rating.desc", "plays.desc"),
        *("duration.desc", "duration.asc", "random"),
    }
)


def _previous_condition(condition: dict[str, Any]) -> dict[str, Any] | None:
    if condition["kind"] != "field":
        return None
    field, operator, value = (
        condition["field"],
        condition["operator"],
        condition["value"],
    )
    days = {value: key for key, value in _WITHIN_DAYS.items()}
    if field in days and operator == "in_last":
        return {"field": days[field], "operator": "lte", "value": value}
    field = {value: key for key, value in _FIELD_NAMES.items() if key != "tag"}.get(
        field, field
    )
    if field not in _PREVIOUS_FIELDS or operator not in _PREVIOUS_OPERATORS:
        return None
    return {"field": field, "operator": operator, "value": value}


def _previous_group(group: dict[str, Any]) -> dict[str, Any] | None:
    conditions = [_previous_condition(entry) for entry in group["conditions"]]
    groups = [_previous_group(entry) for entry in group["groups"]]
    if None in conditions or None in groups:
        return None
    return {"mode": group["mode"], "conditions": conditions, "groups": groups}


def _filter_builder(group: dict[str, Any] | None) -> dict[str, Any] | None:
    return group and {"type": "library_filter", "filter_group": group}


def _previous_rule(row: dict[str, Any]) -> tuple[str | None, str | None] | None:
    """Return a rule's previous builders or smart filter, if it has any."""
    criteria = json.loads(row["criteria_json"])
    if row["smart"]:
        group = _previous_group(criteria)
        if group is None:
            return None
        sort = {value: key for key, value in _SMART_SORTS.items()}.get(
            row["order_type"], row["order_type"]
        )
        return None, json.dumps(
            {
                "filter_group": group,
                "sort_by": sort if sort in _PREVIOUS_SORTS else "release.desc",
                "limit": row["item_limit"],
            }
        )
    conditions = criteria["conditions"]
    if criteria["mode"] == "all" and len(conditions) + len(criteria["groups"]) > 1:
        if any(entry["kind"] == "source" for entry in conditions):
            return None
        builders = [_filter_builder(_previous_group(criteria))]
    else:
        builders = [
            {**entry["source"]}
            if entry["kind"] == "source" and entry["operator"] == "is"
            else _filter_builder(
                _previous_group({"mode": "all", "conditions": [entry], "groups": []})
                if entry["kind"] == "field"
                else None
            )
            for entry in conditions
        ] + [_filter_builder(_previous_group(group)) for group in criteria["groups"]]
    if None in builders:
        return None
    return json.dumps(builders), None


def _replace_orders(
    old: Sequence[str], new: Sequence[str], mapping: dict[str, str]
) -> None:
    connection = op.get_bind()
    for table, column, nullable in _ORDER_COLUMNS:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_{column}", type_="check")
            batch.alter_column(
                column,
                existing_type=_order_type(old),
                type_=_order_type(new),
                existing_nullable=nullable,
            )
        rows = sa.table(table, sa.column(column))
        for before, after in mapping.items():
            connection.execute(
                rows.update().where(rows.c[column] == before).values({column: after})
            )
        with op.batch_alter_table(table) as batch:
            batch.create_check_constraint(f"ck_{table}_{column}", _check(column, new))


def upgrade() -> None:
    """Convert rules into criteria trees, franchise discovery into sets, and orders."""
    connection = op.get_bind()
    orders = [order.value for order in CollectionOrder]
    _replace_orders(_OLD_ORDERS, orders, _ORDERS)

    with op.batch_alter_table("collection_rules") as batch:
        batch.add_column(
            sa.Column(
                "criteria_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch.add_column(
            sa.Column("smart", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.add_column(sa.Column("item_limit", sa.Integer(), nullable=True))
    rules = connection.execute(
        sa.text(
            "SELECT id, builders_json, smart_filter_json, managed_label "
            "FROM collection_rules"
        )
    ).mappings()
    for row in list(rules):
        criteria, smart, limit, sort = _criteria(dict(row))
        if criteria is None:
            # A rule without sources selected nothing and could not be saved.
            connection.execute(
                sa.text("DELETE FROM collection_rules WHERE id=:id"), {"id": row["id"]}
            )
            continue
        connection.execute(
            sa.text(
                "UPDATE collection_rules SET criteria_json=:criteria, smart=:smart, "
                "item_limit=:limit, order_type=COALESCE(:sort, order_type) "
                "WHERE id=:id"
            ),
            {
                "id": row["id"],
                "criteria": criteria,
                "smart": smart,
                "limit": limit,
                "sort": sort,
            },
        )
    with op.batch_alter_table("collection_rules") as batch:
        batch.alter_column(
            "criteria_json",
            existing_type=sqlmodel.sql.sqltypes.AutoString(),
            nullable=False,
        )
        batch.alter_column("smart", existing_type=sa.Boolean(), server_default=None)
        batch.drop_constraint("ck_collection_rules_source_type", type_="check")
        batch.drop_column("managed_label")
        batch.drop_column("source_type")
        batch.drop_column("builders_json")
        batch.drop_column("source_identifier")
        batch.drop_column("filter_json")
        batch.drop_column("smart_filter_json")

    with op.batch_alter_table("collection_groups") as batch:
        batch.add_column(
            sa.Column(
                "generator_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
        batch.add_column(
            sa.Column(
                "generated_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True
            )
        )
    groups = connection.execute(
        sa.text(
            "SELECT id, dynamic_tmdb_json FROM collection_groups "
            "WHERE dynamic_tmdb_json IS NOT NULL"
        )
    ).mappings()
    for row in list(groups):
        connection.execute(
            sa.text("UPDATE collection_groups SET generator_json=:value WHERE id=:id"),
            {"id": row["id"], "value": _generator(row["dynamic_tmdb_json"])},
        )
    with op.batch_alter_table("collection_groups") as batch:
        batch.drop_column("dynamic_tmdb_json")

    with op.batch_alter_table("media_collections") as batch:
        batch.add_column(
            sa.Column(
                "generated_value", sqlmodel.sql.sqltypes.AutoString(), nullable=True
            )
        )
    connection.execute(
        sa.text(
            "UPDATE media_collections SET generated_value=CAST("
            "auto_generated_tmdb_id AS TEXT) WHERE auto_generated_tmdb_id IS NOT NULL"
        )
    )
    with op.batch_alter_table("media_collections") as batch:
        batch.drop_index("ix_media_collections_auto_generated_tmdb_id")
        batch.drop_column("auto_generated_tmdb_id")

    # Jellyfin and Emby tags are Plex labels; ratings, play state and editions
    # are read by the next full library sync.
    items = connection.execute(
        sa.text("SELECT id, labels, tags FROM media_items WHERE tags != '[]'")
    ).mappings()
    for row in list(items):
        labels = list(
            dict.fromkeys([*json.loads(row["labels"]), *json.loads(row["tags"])])
        )
        connection.execute(
            sa.text("UPDATE media_items SET labels=:labels WHERE id=:id"),
            {"id": row["id"], "labels": json.dumps(labels)},
        )
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(
            sa.Column("edition", sqlmodel.sql.sqltypes.AutoString(), nullable=True)
        )
        batch.add_column(sa.Column("critic_rating", sa.Float(), nullable=True))
        batch.add_column(sa.Column("audience_rating", sa.Float(), nullable=True))
        batch.add_column(sa.Column("user_rating", sa.Float(), nullable=True))
        batch.add_column(sa.Column("plays", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "last_played_at", sqlmodel.sql.sqltypes.UTCDateTime(), nullable=True
            )
        )
        batch.drop_column("tags")
        batch.drop_column("audio_language")
        batch.drop_column("rating")


def downgrade() -> None:
    """Restore the previous columns.

    Criteria the previous builders cannot express, such as sources that must
    all hold an item, are removed with their rules; their collections keep
    their current members. Sets of other dimensions than TMDB franchises are
    removed likewise, and orders the previous version lacks become custom.
    """
    connection = op.get_bind()
    with op.batch_alter_table("media_items") as batch:
        batch.add_column(sa.Column("rating", sa.Float(), nullable=True))
        batch.add_column(sa.Column("audio_language", sa.VARCHAR(), nullable=True))
        batch.add_column(
            sa.Column(
                "tags", sqlite.JSON(), nullable=False, server_default=sa.text("'[]'")
            )
        )
        batch.drop_column("last_played_at")
        batch.drop_column("plays")
        batch.drop_column("user_rating")
        batch.drop_column("audience_rating")
        batch.drop_column("critic_rating")
        batch.drop_column("edition")
    with op.batch_alter_table("media_items") as batch:
        batch.alter_column("tags", existing_type=sqlite.JSON(), server_default=None)

    with op.batch_alter_table("media_collections") as batch:
        batch.add_column(
            sa.Column("auto_generated_tmdb_id", sa.Integer(), nullable=True)
        )
        batch.create_index(
            "ix_media_collections_auto_generated_tmdb_id",
            ["auto_generated_tmdb_id"],
            unique=False,
        )
    connection.execute(
        sa.text(
            "UPDATE media_collections SET auto_generated_tmdb_id=CAST("
            "generated_value AS INTEGER) WHERE generated_value GLOB '[0-9]*'"
        )
    )
    with op.batch_alter_table("media_collections") as batch:
        batch.drop_column("generated_value")

    with op.batch_alter_table("collection_groups") as batch:
        batch.add_column(sa.Column("dynamic_tmdb_json", sa.VARCHAR(), nullable=True))
    groups = connection.execute(
        sa.text(
            "SELECT id, generator_json FROM collection_groups "
            "WHERE generator_json IS NOT NULL"
        )
    ).mappings()
    for row in list(groups):
        generator: dict[str, Any] = json.loads(row["generator_json"])
        if generator["dimension"] != SetDimension.FRANCHISE:
            continue
        connection.execute(
            sa.text(
                "UPDATE collection_groups SET dynamic_tmdb_json=:value WHERE id=:id"
            ),
            {
                "id": row["id"],
                "value": json.dumps(
                    {
                        "enabled": generator.get("enabled", True),
                        "library_id": generator["library_id"],
                        "strip_prefix": generator.get("strip_prefix", ""),
                        "strip_suffix": generator.get("strip_suffix", ""),
                        "exclude_tmdb_ids": [
                            int(value)
                            for value in generator.get("exclude", [])
                            if value.isdigit()
                        ],
                        "auto_exclude_from_other_collections": True,
                    }
                ),
            },
        )
    with op.batch_alter_table("collection_groups") as batch:
        batch.drop_column("generated_at")
        batch.drop_column("generator_json")

    with op.batch_alter_table("collection_rules") as batch:
        batch.add_column(sa.Column("smart_filter_json", sa.VARCHAR(), nullable=True))
        batch.add_column(sa.Column("filter_json", sa.VARCHAR(), nullable=True))
        batch.add_column(
            sa.Column(
                "source_identifier", sa.VARCHAR(), nullable=False, server_default=""
            )
        )
        batch.add_column(sa.Column("builders_json", sa.VARCHAR(), nullable=True))
        batch.add_column(
            sa.Column(
                "source_type",
                sa.Enum(
                    "mdblist",
                    "tmdb",
                    "filter",
                    name="rulesourcetype",
                    native_enum=False,
                ),
                nullable=False,
                server_default="filter",
            )
        )
        batch.add_column(sa.Column("managed_label", sa.VARCHAR(), nullable=True))
        batch.create_check_constraint(
            "ck_collection_rules_source_type",
            _check("source_type", ("mdblist", "tmdb", "filter")),
        )
    rules = connection.execute(
        sa.text(
            "SELECT id, criteria_json, smart, item_limit, order_type "
            "FROM collection_rules"
        )
    ).mappings()
    for row in list(rules):
        previous = _previous_rule(dict(row))
        if previous is None:
            connection.execute(
                sa.text("DELETE FROM collection_rules WHERE id=:id"), {"id": row["id"]}
            )
            continue
        builders, smart_filter = previous
        connection.execute(
            sa.text(
                "UPDATE collection_rules SET builders_json=:builders, "
                "smart_filter_json=:smart_filter, order_type=:order WHERE id=:id"
            ),
            {
                "id": row["id"],
                "builders": builders,
                "smart_filter": smart_filter,
                # The smart sort held the order; the old order was independent.
                "order": None if smart_filter else row["order_type"],
            },
        )
    with op.batch_alter_table("collection_rules") as batch:
        batch.drop_column("item_limit")
        batch.drop_column("smart")
        batch.drop_column("criteria_json")

    orders = [order.value for order in CollectionOrder]
    previous = {"release.asc": "release", "title.asc": "alpha"}
    _replace_orders(
        orders,
        _OLD_ORDERS,
        {order: previous.get(order, "custom") for order in orders},
    )
