"""Collection sets: one collection per value of a metadata dimension."""

lazy from collections import Counter
lazy from collections.abc import Mapping, Sequence
lazy from dataclasses import dataclass

lazy from ...db.models.media_item import MediaItem
lazy from ...domain import FilterOperator, SetDimension
lazy from ...schemas.collections import (
    CollectionGeneratorBase,
    FieldCondition,
    FilterGroup,
    SourceCondition,
    TmdbCollectionSource,
)
lazy from ...utils.collection_formats import format_set_title, strip_affixes
lazy from .criteria import CriteriaContext, evaluate, field_value
lazy from .fields import DIMENSIONS


@dataclass(slots=True, frozen=True)
class SetValue:
    """One value of a set, and the collection it makes."""

    value: str
    title: str
    count: int
    criteria: FilterGroup


def alias_keys(generator: CollectionGeneratorBase) -> dict[str, str]:
    """The key each aliased value counts under, by its folded name.

    A renamed value keeps its own key, so its collection is renamed rather
    than replaced; merged values share a key naming them all.
    """
    keys: dict[str, str] = {}
    for alias in generator.aliases:
        key = "|".join(sorted(alias.values, key=str.casefold))
        for value in alias.values:
            keys[value.casefold()] = key
    return keys


def alias_names(generator: CollectionGeneratorBase) -> dict[str, str]:
    """The name each aliased key's collection takes."""
    return {
        "|".join(sorted(alias.values, key=str.casefold)): alias.name
        for alias in generator.aliases
    }


def count_values(
    generator: CollectionGeneratorBase,
    items: Sequence[MediaItem],
    context: CriteriaContext,
) -> Counter[str]:
    """Count the items holding each value, among those the set's criteria match."""
    if not generator.criteria.is_empty():
        items = evaluate(items, generator.criteria, context)
    if generator.dimension is SetDimension.CUSTOM:
        return Counter(
            {
                value.name: len(evaluate(items, value.criteria, context))
                for value in generator.custom_values
            }
        )
    field = DIMENSIONS[generator.dimension].field
    aliases = alias_keys(generator)
    counts: Counter[str] = Counter()
    for item in items:
        if field is None:
            found = (
                {str(item.tmdb_collection_id)}
                if item.tmdb_collection_id is not None
                else set[str]()
            )
        else:
            value = field_value(item, field, context.collections.get(item.id or 0, ()))
            if isinstance(value, str):
                found = {value}
            elif isinstance(value, int | float) and not isinstance(value, bool):
                found = {str(int(value))}
            elif isinstance(value, Sequence):
                found = {str(entry) for entry in value}
            else:
                found = set[str]()
        counts.update({aliases.get(value.casefold(), value) for value in found})
    return counts


def _condition(dimension: SetDimension, value: str) -> FieldCondition | SourceCondition:
    field = DIMENSIONS[dimension].field
    if field is None:
        return SourceCondition(source=TmdbCollectionSource(collection_id=int(value)))
    return FieldCondition(field=field, operator=FilterOperator.IS, value=value)


def _value_criteria(generator: CollectionGeneratorBase, key: str) -> FilterGroup:
    """What one collection of the set tests, before the set's shared criteria."""
    if generator.dimension is SetDimension.CUSTOM:
        return next(
            value.criteria for value in generator.custom_values if value.name == key
        )
    values = key.split("|") if key in alias_names(generator) else [key]
    return FilterGroup(
        mode="any", conditions=[_condition(generator.dimension, v) for v in values]
    )


def set_values(
    generator: CollectionGeneratorBase,
    counts: Counter[str],
    names: Mapping[str, str],
) -> list[SetValue]:
    """The set's collections, in the dimension's order.

    *names* names values that are identifiers, such as TMDB franchises.
    Include and exclude lists match a value, its name or its collection's
    title, ignoring case. A custom set keeps the order it lists its values in.
    """
    spec = DIMENSIONS[generator.dimension]
    aliased = alias_names(generator)
    names = {**names, **aliased}
    # An alias names its collection exactly; other values fill the template.
    titles = {
        value: aliased.get(value)
        or format_set_title(
            generator.title_format,
            strip_affixes(
                names.get(value, value),
                prefix=generator.strip_prefix,
                suffix=generator.strip_suffix,
            ),
        )
        for value in counts
    }

    def labels(value: str) -> set[str]:
        return {
            value.casefold(),
            names.get(value, value).casefold(),
            titles[value].casefold(),
        }

    include = {entry.casefold() for entry in generator.include}
    exclude = {entry.casefold() for entry in generator.exclude}
    values = [
        value
        for value in counts
        if (not include or labels(value) & include) and not labels(value) & exclude
    ]
    if generator.top is not None:
        values = sorted(values, key=lambda value: (-counts[value], value))[
            : generator.top
        ]
    listed = {value.name: index for index, value in enumerate(generator.custom_values)}
    values.sort(
        key=lambda value: (
            (listed[value], "")
            if value in listed
            else (int(value.split("|")[0]), "")
            if spec.numeric
            else (0, titles[value].casefold())
        )
    )
    return [
        SetValue(
            value=value,
            title=titles[value],
            count=counts[value],
            criteria=_with_shared(generator, _value_criteria(generator, value)),
        )
        for value in values
    ]


def _with_shared(generator: CollectionGeneratorBase, own: FilterGroup) -> FilterGroup:
    """One collection's conditions, and those every collection of the set adds."""
    shared = [] if generator.criteria.is_empty() else [generator.criteria]
    if len(own.conditions) == 1 and not own.groups:
        return FilterGroup(conditions=own.conditions, groups=shared)
    return FilterGroup(groups=[own, *shared])
