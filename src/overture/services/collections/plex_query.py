"""Compile collection criteria into a Plex smart-collection media query.

Plex documents the language in its API reference ("Media Queries"): a field
and operator form the parameter name, ``push``/``pop`` open and close a group,
and ``and``/``or`` join its terms. Operators end in ``=``, which also separates
a parameter from its value, so the name is percent-encoded: Plex reads a bare
``title==Alien`` as "title contains =Alien". Tag fields take the keys Plex
lists for the section's values, so names are looked up first; a name Plex does
not list matches nothing, as it would in Plex itself.
"""

lazy import urllib.parse
lazy from collections.abc import Mapping
lazy from dataclasses import dataclass
lazy from datetime import UTC, date, datetime, timedelta

lazy from ...domain import (
    SMART_CUSTOM_ORDER,
    CollectionOrder,
    FilterField,
    FilterOperator,
    MediaType,
)
lazy from ...schemas.collections import FieldCondition, FilterGroup, SourceCondition
lazy from .fields import FIELDS, PlexField, order_field

#: A key no Plex tag has, for names the section does not list.
_MISSING_TAG = "-1"

_STRING_OPERATORS: frozendict[FilterOperator, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        FilterOperator.IS: "==",
        FilterOperator.IS_NOT: "!==",
        FilterOperator.CONTAINS: "=",
        FilterOperator.DOES_NOT_CONTAIN: "!=",
        FilterOperator.STARTS_WITH: "<=",
        FilterOperator.ENDS_WITH: ">=",
    }
)

#: Plex lists ``>>=`` and ``<<=``; its ``>=`` and ``<=`` are the inclusive bounds.
_NUMBER_OPERATORS: frozendict[FilterOperator, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        FilterOperator.IS: "=",
        FilterOperator.IS_NOT: "!=",
        FilterOperator.GT: ">>=",
        FilterOperator.GTE: ">=",
        FilterOperator.LT: "<<=",
        FilterOperator.LTE: "<=",
    }
)

#: Keys by folded name and key, per Plex field; a name can stand for several keys.
type PlexChoices = Mapping[str, Mapping[str, tuple[str, ...]]]
type Pair = tuple[str, str]


def plex_field(field: FilterField) -> PlexField:
    """The Plex definition of a field smart collections can test."""
    plex = FIELDS[field].plex
    if plex is None or not plex.filterable:
        raise ValueError(f"Plex smart collections cannot test {field}")
    return plex


def tag_keys(criteria: FilterGroup, media_type: MediaType) -> set[str]:
    """The Plex tag fields whose keys the criteria need looked up."""
    keys = {
        plex.key_for(media_type)
        for condition in criteria.field_conditions()
        if (plex := plex_field(condition.field)).type == "tag"
    }
    if criteria.source_conditions():
        keys.add(plex_field(FilterField.LABEL).key)
    return keys


def choice_keys(choices: list[tuple[str, str]]) -> dict[str, tuple[str, ...]]:
    """Index a field's listed values by key and by name, ignoring case.

    Plex lists one name under several keys (English as ``en`` and ``en-US``),
    so a name stands for all of them.
    """
    index: dict[str, tuple[str, ...]] = {}
    for key, title in choices:
        index[title.casefold()] = (*index.get(title.casefold(), ()), key)
    for key, _ in choices:
        index[key.casefold()] = (key,)
    return index


def _op(key: str, operator: str, value: object) -> Pair:
    """Split an operator ending in ``=`` into Plex's parameter name and value."""
    return f"{key}{operator[:-1]}", str(value)


def _group(terms: list[list[Pair]], joiner: str) -> list[Pair]:
    pairs: list[Pair] = []
    for index, term in enumerate(terms):
        if index:
            pairs.append((joiner, "1"))
        pairs.extend(term)
    return pairs


def _nested(terms: list[list[Pair]], joiner: str) -> list[Pair]:
    if len(terms) == 1:
        return terms[0]
    return [("push", "1"), *_group(terms, joiner), ("pop", "1")]


def _number(value: float, plex: PlexField) -> str:
    scaled = value * plex.scale
    return str(int(scaled)) if plex.type == "integer" else f"{scaled:g}"


def _epoch(day: date) -> str:
    return str(int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp()))


def _decade(operator: FilterOperator, value: float) -> list[Pair]:
    """Test a decade as a year range; Plex ignores ``decade!=``."""
    start = int(value) // 10 * 10
    end = start + 9
    match operator:
        case FilterOperator.IS:
            return _nested(
                [[_op("year", ">=", start)], [_op("year", "<=", end)]], "and"
            )
        case FilterOperator.IS_NOT:
            return _nested(
                [[_op("year", "<<=", start)], [_op("year", ">>=", end)]], "or"
            )
        case FilterOperator.GT:
            return [_op("year", ">>=", end)]
        case FilterOperator.GTE:
            return [_op("year", ">=", start)]
        case FilterOperator.LT:
            return [_op("year", "<<=", start)]
        case _:
            return [_op("year", "<=", end)]


def _tag(key: str, operator: FilterOperator, keys: tuple[str, ...]) -> list[Pair]:
    """A comma joins keys Plex tests together; a negation tests each one."""
    if operator is FilterOperator.IS:
        return [_op(key, "=", ",".join(keys))]
    return _nested([[_op(key, "!=", tag)] for tag in keys], "and")


def _field_pairs(
    condition: FieldCondition, media_type: MediaType, choices: PlexChoices
) -> list[Pair]:
    if condition.field is FilterField.DECADE:
        return _decade(condition.operator, float(condition.value))
    plex = plex_field(condition.field)
    key = plex.key_for(media_type)
    operator, value = condition.operator, condition.value
    match plex.type:
        case "string":
            return [_op(key, _STRING_OPERATORS[operator], value)]
        case "tag":
            keys = choices.get(key, {}).get(str(value).casefold(), (_MISSING_TAG,))
            return _tag(key, operator, keys)
        case "boolean":
            flag = bool(value) is (operator is FilterOperator.IS)
            return [(key, "1" if flag else "0")]
        case "integer" | "float":
            return [_op(key, _NUMBER_OPERATORS[operator], _number(float(value), plex))]
        case "date":
            match operator:
                case FilterOperator.IN_LAST:
                    return [_op(key, ">>=", f"-{value}d")]
                case FilterOperator.NOT_IN_LAST:
                    return [_op(key, "<<=", f"-{value}d")]
                case FilterOperator.BEFORE:
                    return [_op(key, "<<=", _epoch(date.fromisoformat(str(value))))]
                case _:
                    after = date.fromisoformat(str(value)) + timedelta(days=1)
                    return [_op(key, ">>=", str(int(_epoch(after)) - 1))]


def _source_pairs(
    condition: SourceCondition, choices: PlexChoices, labels: Mapping[str, str]
) -> list[Pair]:
    key = plex_field(FilterField.LABEL).key
    keys = choices.get(key, {}).get(labels[condition.key].casefold(), (_MISSING_TAG,))
    return _tag(key, condition.operator, keys)


def _group_pairs(
    group: FilterGroup,
    media_type: MediaType,
    choices: PlexChoices,
    labels: Mapping[str, str],
) -> list[Pair]:
    terms: list[list[Pair]] = [
        _source_pairs(condition, choices, labels)
        if isinstance(condition, SourceCondition)
        else _field_pairs(condition, media_type, choices)
        for condition in group.conditions
    ]
    terms.extend(
        [
            ("push", "1"),
            *_group_pairs(nested, media_type, choices, labels),
            ("pop", "1"),
        ]
        for nested in group.groups
        if not nested.is_empty()
    )
    return _group(terms, "and" if group.mode == "all" else "or")


def plex_sort(order: CollectionOrder) -> str:
    """Name a collection order as a Plex sort parameter."""
    if order is CollectionOrder.RANDOM:
        return "random"
    field = order_field(order)
    plex = FIELDS[field].plex if field is not None else None
    if plex is None:
        raise ValueError(SMART_CUSTOM_ORDER)
    key = "titleSort" if field is FilterField.TITLE else plex.key
    return f"{key}:desc" if order.value.endswith(".desc") else key


def compile_plex_query(
    criteria: FilterGroup,
    *,
    media_type: MediaType,
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
    pairs.extend(_group_pairs(criteria, media_type, choices, labels))
    return urllib.parse.urlencode(pairs, quote_via=urllib.parse.quote)


class UnmappableFilterError(ValueError):
    """A Plex filter with terms Overture's criteria cannot express."""

    def __init__(self, terms: list[str]) -> None:
        self.terms = terms
        super().__init__(
            "Overture cannot express these Plex filters: " + ", ".join(terms)
        )


@dataclass(slots=True, frozen=True)
class DecompiledQuery:
    """The criteria, sort and limit a Plex smart filter stands for."""

    criteria: FilterGroup
    order: CollectionOrder
    limit: int | None


#: Tag names by Plex field and tag key, as the section lists them.
type PlexNames = Mapping[str, Mapping[str, str]]
type _Term = FieldCondition | FilterGroup

_STRING_FROM_PLEX = {plex: ours for ours, plex in _STRING_OPERATORS.items()}
_NUMBER_FROM_PLEX = {plex: ours for ours, plex in _NUMBER_OPERATORS.items()}


def plex_field_keys(media_type: MediaType) -> dict[str, FilterField]:
    """The field each Plex key in a section of *media_type* names."""
    keys: dict[str, FilterField] = {}
    for field, spec in FIELDS.items():
        if spec.plex is not None and spec.plex.filterable:
            keys.setdefault(spec.plex.key_for(media_type), field)
    return keys


def _order(sort: str) -> CollectionOrder | None:
    for order in CollectionOrder:
        try:
            if plex_sort(order) == sort:
                return order
        except ValueError:
            continue
    return None


def _from_epoch(value: str, offset: int = 0) -> str:
    moment = datetime.fromtimestamp(int(value) + offset, tz=UTC)
    return moment.date().isoformat()


class _Decompiler:
    def __init__(self, media_type: MediaType, names: PlexNames) -> None:
        self._fields = plex_field_keys(media_type)
        self._names = names
        self.unmappable: list[str] = []

    def condition(self, name: str, value: str) -> FieldCondition | None:
        key = name.rstrip("!<>=")
        operator = f"{name[len(key) :]}="
        field = self._fields.get(key)
        plex = FIELDS[field].plex if field is not None else None
        try:
            if field is None or plex is None:
                raise ValueError
            operator_, operand = self._operand(plex, key, operator, value)
            return FieldCondition(field=field, operator=operator_, value=operand)
        except ValueError, KeyError:
            self.unmappable.append(f"{name}={value}")
            return None

    def _operand(
        self, plex: PlexField, key: str, operator: str, value: str
    ) -> tuple[FilterOperator, str | int | float | bool]:
        match plex.type:
            case "string":
                return _STRING_FROM_PLEX[operator], value
            case "tag":
                names = {self._names.get(key, {})[tag] for tag in value.split(",")}
                if len(names) != 1 or operator not in {"=", "!="}:
                    raise ValueError
                negated = operator == "!="
                return (
                    FilterOperator.IS_NOT if negated else FilterOperator.IS,
                    names.pop(),
                )
            case "boolean":
                return FilterOperator.IS, value == "1"
            case "integer" | "float":
                number = float(value) / plex.scale
                return _NUMBER_FROM_PLEX[operator], int(
                    number
                ) if number.is_integer() else number
            case "date":
                if value.startswith("-") and value.endswith("d"):
                    days = int(value[1:-1])
                    if operator == ">>=":
                        return FilterOperator.IN_LAST, days
                    return FilterOperator.NOT_IN_LAST, days
                if operator == "<<=":
                    return FilterOperator.BEFORE, _from_epoch(value)
                after = date.fromisoformat(_from_epoch(value, 1)) - timedelta(days=1)
                return FilterOperator.AFTER, after.isoformat()

    def group(self, pairs: list[Pair], start: int) -> tuple[FilterGroup, int]:
        """Read terms up to the matching ``pop``, returning the index after it."""
        terms: list[_Term] = []
        joiners: set[str] = set()
        index = start
        while index < len(pairs):
            name, value = pairs[index]
            index += 1
            if name == "pop":
                break
            if name in {"and", "or"}:
                joiners.add(name)
            elif name == "push":
                nested, index = self.group(pairs, index)
                terms.append(_collapse(nested))
            elif (condition := self.condition(name, value)) is not None:
                terms.append(condition)
        if len(joiners) > 1:
            self.unmappable.append("a group mixing and with or")
        return (
            FilterGroup(
                mode="any" if joiners == {"or"} else "all",
                conditions=[term for term in terms if isinstance(term, FieldCondition)],
                groups=[term for term in terms if isinstance(term, FilterGroup)],
            ),
            index,
        )


#: The year ranges a decade compiles to, by group mode and their operators.
_DECADES: frozendict[tuple[str, FilterOperator, FilterOperator], FilterOperator] = (
    frozendict(
        {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
            ("all", FilterOperator.GTE, FilterOperator.LTE): FilterOperator.IS,
            ("any", FilterOperator.LT, FilterOperator.GT): FilterOperator.IS_NOT,
        }
    )
)


def _collapse(group: FilterGroup) -> _Term:
    """Read back the groups the compiler emits for one decade or negated tag."""
    conditions = [c for c in group.conditions if isinstance(c, FieldCondition)]
    if group.groups or len(conditions) < 2 or len(conditions) != len(group.conditions):
        return group
    fields = {condition.field for condition in conditions}
    operators = [condition.operator for condition in conditions]
    values = [condition.value for condition in conditions]
    if fields == {FilterField.YEAR} and len(conditions) == 2:
        low, high = values
        decade = _DECADES.get((group.mode, operators[0], operators[1]))
        decade_start = isinstance(low, int) and low % 10 == 0 and high == low + 9
        if decade is not None and decade_start:
            return FieldCondition(field=FilterField.DECADE, operator=decade, value=low)
    (field, *others) = fields
    if (
        not others
        and group.mode == "all"
        and set(operators) == {FilterOperator.IS_NOT}
        and len(set(values)) == 1
        and plex_field(field).type == "tag"
    ):
        return conditions[0]
    return group


def decompile_plex_query(
    query: str, *, media_type: MediaType, names: PlexNames
) -> DecompiledQuery:
    """Read a Plex smart filter back into criteria, as compiling would write it.

    Raises:
        UnmappableFilterError: When a term has no equivalent criterion.
    """
    pairs = urllib.parse.parse_qsl(query, keep_blank_values=True)
    decompiler = _Decompiler(media_type, names)
    order, limit = CollectionOrder.TITLE_ASC, None
    terms: list[Pair] = []
    for name, value in pairs:
        if name == "sort":
            found = _order(value)
            if found is None:
                decompiler.unmappable.append(f"sort={value}")
            else:
                order = found
        elif name == "limit" and value.isdigit():
            limit = int(value)
        else:
            terms.append((name, value))
    criteria, _ = decompiler.group(terms, 0)
    if decompiler.unmappable:
        raise UnmappableFilterError(decompiler.unmappable)
    return DecompiledQuery(criteria, order, limit)
