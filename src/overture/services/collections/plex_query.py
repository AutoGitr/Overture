"""Compile collection criteria into a Plex smart-collection media query.

Plex documents the language in its API reference ("Media Queries"): a field
and operator form the parameter name, ``push``/``pop`` open and close a group,
and ``and``/``or`` join its terms. Tag fields take the keys Plex lists for the
section's values, so names are looked up first; a name Plex does not list
matches nothing, as it would in Plex itself.
"""

lazy import urllib.parse
lazy from collections.abc import Mapping
lazy from datetime import UTC, date, datetime, timedelta

lazy from ...domain import CollectionOrder, FilterField, FilterOperator
lazy from ...schemas.collections import FieldCondition, FilterGroup, SourceCondition
lazy from .fields import FIELDS, PlexField, order_field

#: A key no Plex tag has, for names the section does not list.
_MISSING_TAG = "-1"

_STRING_OPERATORS: frozendict[FilterOperator, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        FilterOperator.IS: "=",
        FilterOperator.IS_NOT: "!=",
        FilterOperator.CONTAINS: "",
        FilterOperator.DOES_NOT_CONTAIN: "!",
        FilterOperator.STARTS_WITH: "<",
        FilterOperator.ENDS_WITH: ">",
    }
)

#: Plex's documented comparisons are strict; inclusive bounds move by a step.
_NUMBER_OPERATORS: frozendict[FilterOperator, tuple[str, int]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        FilterOperator.IS: ("", 0),
        FilterOperator.IS_NOT: ("!", 0),
        FilterOperator.GT: (">>", 0),
        FilterOperator.GTE: (">>", -1),
        FilterOperator.LT: ("<<", 0),
        FilterOperator.LTE: ("<<", 1),
    }
)

#: Plex stores ratings to one decimal, so half a step separates neighbours.
_RATING_STEP = 0.05

type PlexChoices = Mapping[str, Mapping[str, str]]
type Pair = tuple[str, str]


def plex_field(field: FilterField) -> PlexField:
    """The Plex definition of a field smart collections can test."""
    plex = FIELDS[field].plex
    if plex is None:
        raise ValueError(f"Plex smart collections cannot test {field}")
    return plex


def tag_keys(criteria: FilterGroup) -> set[str]:
    """The Plex tag fields whose keys the criteria need looked up."""
    keys = {
        plex.key
        for condition in criteria.field_conditions()
        if (plex := plex_field(condition.field)).type == "tag"
    }
    if criteria.source_conditions():
        keys.add(plex_field(FilterField.LABEL).key)
    return keys


def choice_keys(choices: list[tuple[str, str]]) -> dict[str, str]:
    """Index a field's listed values by key and by name, ignoring case."""
    return {
        **{title.casefold(): key for key, title in choices},
        **{key.casefold(): key for key, _ in choices},
    }


def _number(value: float, plex: PlexField, step: int) -> str:
    scaled = value * plex.scale
    if plex.type == "integer":
        return str(int(scaled) + step)
    return f"{scaled + step * _RATING_STEP:g}"


def _epoch(day: date) -> str:
    return str(int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()))


def _field_pair(condition: FieldCondition, choices: PlexChoices) -> Pair:
    plex = plex_field(condition.field)
    operator, value = condition.operator, condition.value
    match plex.type:
        case "string":
            return f"{plex.key}{_STRING_OPERATORS[operator]}", str(value)
        case "tag":
            key = choices.get(plex.key, {}).get(str(value).casefold(), _MISSING_TAG)
            negate = "!" if operator is FilterOperator.IS_NOT else ""
            return f"{plex.key}{negate}", key
        case "boolean":
            flag = bool(value) is (operator is FilterOperator.IS)
            return plex.key, "1" if flag else "0"
        case "integer" | "float":
            suffix, step = _NUMBER_OPERATORS[operator]
            return f"{plex.key}{suffix}", _number(float(value), plex, step)
        case "date":
            match operator:
                case FilterOperator.IN_LAST:
                    return f"{plex.key}>>", f"-{value}d"
                case FilterOperator.NOT_IN_LAST:
                    return f"{plex.key}<<", f"-{value}d"
                case FilterOperator.BEFORE:
                    return f"{plex.key}<<", _epoch(date.fromisoformat(str(value)))
                case _:
                    after = date.fromisoformat(str(value)) + timedelta(days=1)
                    return f"{plex.key}>>", str(int(_epoch(after)) - 1)


def _source_pair(
    condition: SourceCondition, choices: PlexChoices, labels: Mapping[str, str]
) -> Pair:
    key = plex_field(FilterField.LABEL).key
    tag = choices.get(key, {}).get(labels[condition.key].casefold(), _MISSING_TAG)
    return f"{key}!" if condition.operator is FilterOperator.IS_NOT else key, tag


def _group_pairs(
    group: FilterGroup, choices: PlexChoices, labels: Mapping[str, str]
) -> list[Pair]:
    terms: list[list[Pair]] = [
        [
            _source_pair(condition, choices, labels)
            if isinstance(condition, SourceCondition)
            else _field_pair(condition, choices)
        ]
        for condition in group.conditions
    ]
    terms.extend(
        [("push", "1"), *_group_pairs(nested, choices, labels), ("pop", "1")]
        for nested in group.groups
        if not nested.is_empty()
    )
    pairs: list[Pair] = []
    for index, term in enumerate(terms):
        if index:
            pairs.append(("and" if group.mode == "all" else "or", "1"))
        pairs.extend(term)
    return pairs


def plex_sort(order: CollectionOrder) -> str:
    """Name a collection order as a Plex sort parameter."""
    if order is CollectionOrder.RANDOM:
        return "random"
    field = order_field(order)
    if field is None:
        raise ValueError("Smart collections are ordered by Plex; choose a sort")
    key = "titleSort" if field is FilterField.TITLE else plex_field(field).key
    return f"{key}:desc" if order.value.endswith(".desc") else key


def compile_plex_query(
    criteria: FilterGroup,
    *,
    order: CollectionOrder,
    limit: int | None,
    choices: PlexChoices,
    labels: Mapping[str, str],
) -> str:
    """Compile criteria, sort and limit into a smart collection query string.

    *labels* names the label Overture keeps on each source condition's items.
    """
    pairs: list[Pair] = [("sort", plex_sort(order))]
    if limit is not None:
        pairs.append(("limit", str(limit)))
    pairs.extend(_group_pairs(criteria, choices, labels))
    return urllib.parse.urlencode(pairs, safe=":<>=!-")
