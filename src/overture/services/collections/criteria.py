"""Criteria evaluation and member ordering against synced library metadata."""

lazy import random
lazy from collections.abc import Callable, Mapping, Sequence
lazy from dataclasses import dataclass
lazy from datetime import date, datetime, timedelta

lazy from ...db.models.media_item import MediaItem
lazy from ...domain import CollectionOrder, FieldKind, FilterField, FilterOperator
lazy from ...schemas.collections import FieldCondition, FilterGroup, SourceCondition
lazy from .fields import FIELDS, order_field

type FieldValue = str | float | date | bool | Sequence[str] | None


@dataclass(slots=True, frozen=True)
class CriteriaContext:
    """What conditions need besides an item's own metadata."""

    #: The items each source holds, keyed by ``SourceCondition.key``.
    sources: Mapping[str, frozenset[int]]
    #: The titles of the collections each item belongs to.
    collections: Mapping[int, Sequence[str]]
    now: datetime


def _release(item: MediaItem) -> date | None:
    if item.release_date:
        try:
            return date.fromisoformat(item.release_date[:10])
        except ValueError:
            pass
    return date(item.year, 1, 1) if item.year else None


def _day(value: datetime | None) -> date | None:
    return value.date() if value else None


def _one(value: str | None) -> list[str]:
    return [value] if value else []


type _Getter = Callable[[MediaItem], FieldValue]

#: Each field's synced value; fields missing here only Plex evaluates.
_GETTERS: dict[FilterField, _Getter] = {
    FilterField.TITLE: lambda item: item.title,
    FilterField.STUDIO: lambda item: item.studio,
    FilterField.EDITION: lambda item: item.edition,
    FilterField.GENRE: lambda item: item.genres,
    FilterField.ACTOR: lambda item: item.actors,
    FilterField.DIRECTOR: lambda item: _one(item.director),
    FilterField.WRITER: lambda item: item.writers,
    FilterField.PRODUCER: lambda item: item.producers,
    FilterField.COUNTRY: lambda item: item.countries,
    FilterField.LABEL: lambda item: item.labels,
    FilterField.CONTENT_RATING: lambda item: _one(item.content_rating),
    FilterField.RESOLUTION: lambda item: _one(item.resolution),
    FilterField.YEAR: lambda item: item.year,
    FilterField.DECADE: lambda item: item.year // 10 * 10 if item.year else None,
    FilterField.CRITIC_RATING: lambda item: item.critic_rating,
    FilterField.AUDIENCE_RATING: lambda item: item.audience_rating,
    FilterField.USER_RATING: lambda item: item.user_rating,
    FilterField.DURATION: lambda item: item.duration_minutes,
    FilterField.PLAYS: lambda item: item.plays,
    FilterField.ADDED: lambda item: _day(item.server_added_at),
    FilterField.RELEASED: _release,
    FilterField.LAST_PLAYED: lambda item: _day(item.last_played_at),
    FilterField.UNPLAYED: lambda item: item.unplayed,
    FilterField.IN_PROGRESS: lambda item: item.in_progress,
}
_VALUES: frozendict[FilterField, _Getter] = frozendict(_GETTERS)  # pyright: ignore[reportCallIssue] -- stale frozendict stub


def field_value(
    item: MediaItem, field: FilterField, collections: Sequence[str] = ()
) -> FieldValue:
    """The item's synced value of a field; lists for tag fields."""
    if field is FilterField.COLLECTION:
        return collections
    getter = _VALUES.get(field)
    return getter(item) if getter else None


def _text(candidate: str, operator: FilterOperator, target: str) -> bool:
    left, right = candidate.casefold(), target.casefold()
    match operator:
        case FilterOperator.IS:
            return left == right
        case FilterOperator.IS_NOT:
            return left != right
        case FilterOperator.CONTAINS:
            return right in left
        case FilterOperator.DOES_NOT_CONTAIN:
            return right not in left
        case FilterOperator.STARTS_WITH:
            return left.startswith(right)
        case FilterOperator.ENDS_WITH:
            return left.endswith(right)
        case _:
            return False


def _number(candidate: float | None, operator: FilterOperator, target: float) -> bool:
    if candidate is None:
        return operator is FilterOperator.IS_NOT
    match operator:
        case FilterOperator.IS:
            return candidate == target
        case FilterOperator.IS_NOT:
            return candidate != target
        case FilterOperator.GT:
            return candidate > target
        case FilterOperator.GTE:
            return candidate >= target
        case FilterOperator.LT:
            return candidate < target
        case FilterOperator.LTE:
            return candidate <= target
        case _:
            return False


def _date(
    candidate: date | None, operator: FilterOperator, target: str | float, today: date
) -> bool:
    # Like Plex, an unknown date matches no date condition.
    if candidate is None:
        return False
    match operator:
        case FilterOperator.IN_LAST:
            return candidate >= today - timedelta(days=float(target))
        case FilterOperator.NOT_IN_LAST:
            return candidate < today - timedelta(days=float(target))
        case FilterOperator.BEFORE:
            return candidate < date.fromisoformat(str(target))
        case FilterOperator.AFTER:
            return candidate > date.fromisoformat(str(target))
        case _:
            return False


def _matches_field(
    item: MediaItem, condition: FieldCondition, context: CriteriaContext
) -> bool:
    value = field_value(
        item, condition.field, context.collections.get(item.id or 0, ())
    )
    operator, target = condition.operator, condition.value
    match FIELDS[condition.field].kind:
        case FieldKind.TEXT:
            return _text(str(value or ""), operator, str(target))
        case FieldKind.TAG:
            values = value if isinstance(value, Sequence) else ()
            found = any(
                _text(str(entry), FilterOperator.IS, str(target)) for entry in values
            )
            return found if operator is FilterOperator.IS else not found
        case FieldKind.NUMBER:
            number = value if isinstance(value, int | float) else None
            return _number(number, operator, float(target))
        case FieldKind.DATE:
            day = value if isinstance(value, date) else None
            if isinstance(target, bool):
                return False
            return _date(day, operator, target, context.now.date())
        case FieldKind.BOOLEAN:
            return (bool(value) == target) is (operator is FilterOperator.IS)


def _matches_source(
    item: MediaItem, condition: SourceCondition, context: CriteriaContext
) -> bool:
    found = (item.id or 0) in context.sources.get(condition.key, ())
    return found if condition.operator is FilterOperator.IS else not found


def _matches(item: MediaItem, group: FilterGroup, context: CriteriaContext) -> bool:
    results = (
        *(
            _matches_source(item, condition, context)
            if isinstance(condition, SourceCondition)
            else _matches_field(item, condition, context)
            for condition in group.conditions
        ),
        *(
            _matches(item, nested, context)
            for nested in group.groups
            if not nested.is_empty()
        ),
    )
    return all(results) if group.mode == "all" else any(results)


def evaluate(
    items: Sequence[MediaItem], criteria: FilterGroup, context: CriteriaContext
) -> list[MediaItem]:
    """Return the items matching the criteria, keeping their order."""
    if criteria.is_empty():
        return []
    return [item for item in items if _matches(item, criteria, context)]


def _sort_key(value: FieldValue) -> str | float | date | None:
    if isinstance(value, str):
        return value.casefold()
    if isinstance(value, bool) or not isinstance(value, float | int | date):
        return None
    return value


def order_items(
    items: Sequence[MediaItem],
    order: CollectionOrder,
    *,
    source_order: Sequence[int] = (),
    limit: int | None = None,
) -> list[MediaItem]:
    """Order members, then keep the first *limit* of them.

    ``custom`` keeps the source's order and then the given order. Items without
    a value for the sort field come last in either direction, and titles break
    ties, as in the sidebar.
    """
    if order is CollectionOrder.RANDOM:
        ordered = random.sample(list(items), len(items))
    elif order is CollectionOrder.CUSTOM:
        rank = {item_id: index for index, item_id in enumerate(source_order)}
        ordered = sorted(items, key=lambda item: rank.get(item.id or 0, len(rank)))
    else:
        field = order_field(order)
        if field is None:
            raise ValueError(f"No sort field for {order}")
        descending = order.value.endswith(".desc")
        by_title = sorted(items, key=lambda item: (item.title.casefold(), item.id or 0))
        known = [
            (key, item)
            for item in by_title
            if (key := _sort_key(field_value(item, field))) is not None
        ]
        unknown = [
            item for item in by_title if _sort_key(field_value(item, field)) is None
        ]
        known.sort(key=lambda pair: pair[0], reverse=descending)
        ordered = [item for _, item in known] + unknown
    return ordered[:limit] if limit is not None else ordered
