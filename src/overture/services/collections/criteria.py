"""Criteria evaluation and member ordering against synced library metadata."""

lazy import random
lazy import re
lazy import unicodedata
lazy from collections.abc import Callable, Mapping, Sequence
lazy from dataclasses import dataclass
lazy from datetime import date, datetime, timedelta

lazy from ...db.models.media_item import MediaItem
lazy from ...domain import (
    CollectionOrder,
    FieldKind,
    FilterField,
    FilterOperator,
    TermKind,
)
lazy from ...schemas.collections import FieldCondition, FilterGroup, SourceCondition
lazy from .fields import FIELDS, order_field

type FieldValue = str | float | date | bool | Sequence[str] | None


@dataclass(slots=True, frozen=True)
class CriteriaContext:
    """What conditions need besides an item's own metadata."""

    #: The items each source holds, keyed by ``SourceCondition.key``.
    sources: Mapping[str, frozenset[int]]
    #: The titles of the other collections each item belongs to; never the
    #: collection being evaluated, so a catch-all keeps what it caught.
    collections: Mapping[int, Sequence[str]]
    now: datetime


def _iso_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value[:10]) if value else None
    except ValueError:
        return None


def _day(value: datetime | None) -> date | None:
    return value.date() if value else None


def _last_played(item: MediaItem) -> date:
    """A title never played was last played before any date."""
    return item.last_played_at.date() if item.last_played_at else date.min


def _minutes(item: MediaItem) -> int | None:
    seconds = item.duration_seconds
    return seconds // 60 if seconds is not None else None


def _one(value: str | None) -> list[str]:
    return [value] if value else []


type _Getter = Callable[[MediaItem], FieldValue]

#: Each field's synced value; fields missing here only Plex evaluates.
_GETTERS: dict[FilterField, _Getter] = {
    FilterField.TITLE: lambda item: item.title,
    FilterField.TMDB_ID: lambda item: _one(
        str(item.tmdb_id) if item.tmdb_id is not None else None
    ),
    FilterField.TVDB_ID: lambda item: _one(
        str(item.tvdb_id) if item.tvdb_id is not None else None
    ),
    FilterField.IMDB_ID: lambda item: _one(item.imdb_id),
    FilterField.STUDIO: lambda item: item.studio,
    FilterField.EDITION: lambda item: item.edition,
    FilterField.GENRE: lambda item: item.values(TermKind.GENRE),
    FilterField.ACTOR: lambda item: item.values(TermKind.ACTOR),
    FilterField.DIRECTOR: lambda item: item.values(TermKind.DIRECTOR),
    FilterField.WRITER: lambda item: item.values(TermKind.WRITER),
    FilterField.PRODUCER: lambda item: item.values(TermKind.PRODUCER),
    FilterField.COUNTRY: lambda item: item.values(TermKind.COUNTRY),
    FilterField.LABEL: lambda item: item.values(TermKind.LABEL),
    FilterField.CONTENT_RATING: lambda item: _one(item.content_rating),
    FilterField.RESOLUTION: lambda item: _one(item.resolution),
    FilterField.YEAR: lambda item: item.year,
    FilterField.DECADE: lambda item: item.year // 10 * 10 if item.year else None,
    FilterField.CRITIC_RATING: lambda item: item.critic_rating,
    FilterField.AUDIENCE_RATING: lambda item: item.audience_rating,
    FilterField.USER_RATING: lambda item: item.user_rating,
    FilterField.DURATION: _minutes,
    FilterField.PLAYS: lambda item: item.plays,
    FilterField.ADDED: lambda item: _day(item.server_added_at),
    FilterField.RELEASED: lambda item: _iso_day(item.release_date),
    FilterField.LAST_PLAYED: _last_played,
    FilterField.UNPLAYED: lambda item: item.unplayed,
    FilterField.IN_PROGRESS: lambda item: item.in_progress,
    FilterField.VERSIONS: lambda item: item.versions,
    FilterField.FOLDER: lambda item: item.folder_path,
    FilterField.NETWORK: lambda item: item.values(TermKind.NETWORK),
    FilterField.ORIGINAL_LANGUAGE: lambda item: _one(item.original_language),
    FilterField.ORIGIN_COUNTRY: lambda item: item.values(TermKind.ORIGIN_COUNTRY),
    FilterField.TMDB_RATING: lambda item: item.tmdb_rating,
    FilterField.TMDB_VOTES: lambda item: item.tmdb_votes,
    FilterField.TMDB_KEYWORD: lambda item: item.values(TermKind.TMDB_KEYWORD),
    FilterField.COMPANY: lambda item: item.values(TermKind.COMPANY),
    FilterField.STREAMING: lambda item: item.values(TermKind.STREAMING),
    FilterField.SHOW_STATUS: lambda item: _one(item.show_status),
    FilterField.LAST_AIRED: lambda item: _iso_day(item.last_aired),
}
_VALUES: frozendict[FilterField, _Getter] = frozendict(_GETTERS)  # pyright: ignore[reportCallIssue] -- stale frozendict stub


def field_value(
    item: MediaItem, field: FilterField, collections: Sequence[str] = ()
) -> FieldValue:
    """The item's synced value of a field; lists for tag fields."""
    if field is FilterField.COLLECTION:
        return collections
    if field is FilterField.IN_COLLECTION:
        return bool(collections)
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
        return False
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


_DIGITS = re.compile(r"(\d+)", re.ASCII)
_LEADING_PUNCTUATION = re.compile(r"^\W+")


def title_key(item: MediaItem) -> tuple[str | int, ...]:
    """Order titles by sort title, numbers by their value.

    Case, accents and leading punctuation are ignored, so ``'71`` sorts
    among the numbers and ``À Nous la Liberté`` among the A's.
    """
    text = unicodedata.normalize("NFKD", item.sort_title or item.title)
    folded = "".join(char for char in text if not unicodedata.combining(char))
    parts = _DIGITS.split(_LEADING_PUNCTUATION.sub("", folded.casefold()))
    return tuple(int(part) if index % 2 else part for index, part in enumerate(parts))


type _SortKey = tuple[str | int, ...] | float | date


def _sort_key(item: MediaItem, field: FilterField) -> _SortKey | None:
    if field is FilterField.TITLE:
        return title_key(item)
    if field is FilterField.DURATION:
        return item.duration_seconds
    value = field_value(item, field)
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
    a value sort lowest (first ascending, last descending) and titles break ties
    in ascending order.
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
        by_title = sorted(items, key=lambda item: (title_key(item), item.id or 0))
        keyed = [(_sort_key(item, field), item) for item in by_title]
        known = [(key, item) for key, item in keyed if key is not None]
        unknown = [item for key, item in keyed if key is None]
        # A stable sort keeps the title order among equal values either way.
        known.sort(key=lambda pair: pair[0], reverse=descending)
        ranked = [item for _, item in known]
        ordered = ranked + unknown if descending else unknown + ranked
    return ordered[:limit] if limit is not None else ordered
