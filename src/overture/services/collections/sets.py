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


def count_values(
    generator: CollectionGeneratorBase,
    items: Sequence[MediaItem],
    context: CriteriaContext,
) -> Counter[str]:
    """Count the items holding each value, among those the set's criteria match."""
    if not generator.criteria.is_empty():
        items = evaluate(items, generator.criteria, context)
    field = DIMENSIONS[generator.dimension].field
    counts: Counter[str] = Counter()
    for item in items:
        if field is None:
            if item.tmdb_collection_id is not None:
                counts[str(item.tmdb_collection_id)] += 1
            continue
        value = field_value(item, field, context.collections.get(item.id or 0, ()))
        if isinstance(value, str):
            counts[value] += 1
        elif isinstance(value, int | float) and not isinstance(value, bool):
            counts[str(int(value))] += 1
        elif isinstance(value, Sequence):
            counts.update({str(entry) for entry in value})
    return counts


def _condition(dimension: SetDimension, value: str) -> FieldCondition | SourceCondition:
    field = DIMENSIONS[dimension].field
    if field is None:
        return SourceCondition(source=TmdbCollectionSource(collection_id=int(value)))
    return FieldCondition(field=field, operator=FilterOperator.IS, value=value)


def set_values(
    generator: CollectionGeneratorBase,
    counts: Counter[str],
    names: Mapping[str, str],
) -> list[SetValue]:
    """The set's collections, in the dimension's order.

    *names* names values that are identifiers, such as TMDB franchises.
    Include and exclude lists match a value, its name or its collection's
    title, ignoring case.
    """
    spec = DIMENSIONS[generator.dimension]
    titles = {
        value: format_set_title(
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
    values.sort(
        key=lambda value: (
            (int(value), "") if spec.numeric else (0, titles[value].casefold())
        )
    )
    return [
        SetValue(
            value=value,
            title=titles[value],
            count=counts[value],
            criteria=FilterGroup(
                conditions=[_condition(generator.dimension, value)],
                groups=[] if generator.criteria.is_empty() else [generator.criteria],
            ),
        )
        for value in values
    ]
