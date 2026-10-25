"""Local library filter evaluation and Plex smart-collection filter compilation."""

lazy import urllib.parse
lazy from collections.abc import Sequence
lazy from datetime import date, datetime

lazy from ...db.models.media_item import MediaItem
lazy from ...domain import FilterField, FilterOperator, SmartSortOrder
lazy from ...schemas.collections import (
    FilterCondition,
    FilterGroup,
    SmartCollectionConfig,
)
lazy from ...utils.time import utc_now

_PLEX_SORT_MAP: frozendict[SmartSortOrder, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        SmartSortOrder.RELEASE_DESC: "originallyAvailableAt:desc",
        SmartSortOrder.RELEASE_ASC: "originallyAvailableAt:asc",
        SmartSortOrder.TITLE_ASC: "titleSort:asc",
        SmartSortOrder.TITLE_DESC: "titleSort:desc",
        SmartSortOrder.ADDED_DESC: "addedAt:desc",
        SmartSortOrder.ADDED_ASC: "addedAt:asc",
        SmartSortOrder.RATING_DESC: "rating:desc",
        SmartSortOrder.CRITIC_RATING_DESC: "rating:desc",
        SmartSortOrder.AUDIENCE_RATING_DESC: "audienceRating:desc",
        SmartSortOrder.PLAYS_DESC: "viewCount:desc",
        SmartSortOrder.DURATION_DESC: "duration:desc",
        SmartSortOrder.DURATION_ASC: "duration:asc",
        SmartSortOrder.RANDOM: "random",
    }
)

_PLEX_FIELD_MAP: frozendict[FilterField, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        FilterField.TITLE: "title",
        FilterField.GENRE: "genre",
        FilterField.STUDIO: "studio",
        FilterField.ACTOR: "actor",
        FilterField.DIRECTOR: "director",
        FilterField.WRITER: "writer",
        FilterField.PRODUCER: "producer",
        FilterField.COUNTRY: "country",
        FilterField.LABEL: "label",
        FilterField.TAG: "label",
        FilterField.CONTENT_RATING: "contentRating",
        FilterField.RESOLUTION: "resolution",
        FilterField.AUDIO_LANGUAGE: "audioLanguage",
        FilterField.YEAR: "year",
        FilterField.DECADE: "decade",
        FilterField.RATING: "rating",
        FilterField.DURATION_MINUTES: "duration",
        FilterField.UNPLAYED: "unwatched",
        FilterField.IN_PROGRESS: "inProgress",
        FilterField.ADDED_WITHIN_DAYS: "addedAt",
        FilterField.RELEASED_WITHIN_DAYS: "originallyAvailableAt",
    }
)


def _match_text(candidate: str, operator: FilterOperator, target: str) -> bool:
    left = candidate.casefold()
    right = target.casefold()
    if operator is FilterOperator.IS:
        return left == right
    if operator is FilterOperator.IS_NOT:
        return left != right
    if operator is FilterOperator.CONTAINS:
        return right in left
    if operator is FilterOperator.DOES_NOT_CONTAIN:
        return right not in left
    if operator is FilterOperator.STARTS_WITH:
        return left.startswith(right)
    return False


def _match_text_list(
    candidates: Sequence[str], operator: FilterOperator, target: str
) -> bool:
    if operator in {FilterOperator.IS_NOT, FilterOperator.DOES_NOT_CONTAIN}:
        positive = (
            FilterOperator.IS
            if operator is FilterOperator.IS_NOT
            else FilterOperator.CONTAINS
        )
        return not any(_match_text(item, positive, target) for item in candidates)
    return any(_match_text(item, operator, target) for item in candidates)


def _match_number(
    candidate: int | float | None, operator: FilterOperator, target: int | float
) -> bool:
    if candidate is None:
        return operator is FilterOperator.IS_NOT
    if operator is FilterOperator.IS:
        return candidate == target
    if operator is FilterOperator.IS_NOT:
        return candidate != target
    if operator is FilterOperator.GTE:
        return candidate >= target
    if operator is FilterOperator.LTE:
        return candidate <= target
    return False


def _to_float(value: str | int | float | bool) -> float:
    if isinstance(value, bool):
        return float(int(value))
    try:
        return float(value)
    except ValueError:
        return 0.0


def _to_bool(value: str | int | float | bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value != 0
    return value.strip().casefold() in {"1", "true", "yes"}


def _item_text_field(item: MediaItem, field: FilterField) -> str | None:
    if field is FilterField.TITLE:
        return item.title
    if field is FilterField.STUDIO:
        return item.studio or ""
    if field is FilterField.DIRECTOR:
        return item.director or ""
    if field is FilterField.CONTENT_RATING:
        return item.content_rating or ""
    if field is FilterField.RESOLUTION:
        return item.resolution or ""
    if field is FilterField.AUDIO_LANGUAGE:
        return item.audio_language or ""
    return None


def _item_list_field(item: MediaItem, field: FilterField) -> Sequence[str] | None:
    if field is FilterField.GENRE:
        return item.genres
    if field is FilterField.ACTOR:
        return item.actors
    if field is FilterField.WRITER:
        return item.writers
    if field is FilterField.PRODUCER:
        return item.producers
    if field is FilterField.COUNTRY:
        return item.countries
    if field is FilterField.LABEL:
        return item.labels
    if field is FilterField.TAG:
        return [*item.tags, *item.labels]
    return None


def _evaluate_numeric_or_date(
    item: MediaItem, condition: FilterCondition, now: datetime
) -> bool:
    field = condition.field
    op = condition.operator
    val = condition.value
    if field is FilterField.YEAR:
        return _match_number(item.year, op, int(_to_float(val)))
    if field is FilterField.DECADE:
        decade = (item.year // 10 * 10) if item.year is not None else None
        return _match_number(decade, op, int(_to_float(val)) // 10 * 10)
    if field is FilterField.RATING:
        return _match_number(item.rating, op, _to_float(val))
    if field is FilterField.DURATION_MINUTES:
        return _match_number(item.duration_minutes, op, _to_float(val))
    if field in {FilterField.UNPLAYED, FilterField.IN_PROGRESS}:
        raw = item.unplayed if field is FilterField.UNPLAYED else item.in_progress
        actual = bool(raw) if raw is not None else False
        expected = _to_bool(val)
        return (
            (actual != expected)
            if op is FilterOperator.IS_NOT
            else (actual == expected)
        )
    if field is FilterField.ADDED_WITHIN_DAYS and item.server_added_at is not None:
        age_days = (now - item.server_added_at).total_seconds() / 86400.0
        return age_days <= _to_float(val)
    if field is FilterField.RELEASED_WITHIN_DAYS and item.release_date:
        try:
            released = date.fromisoformat(item.release_date[:10])
        except ValueError:
            return False
        return 0 <= (now.date() - released).days <= _to_float(val)
    return False


def _evaluate_condition(
    item: MediaItem, condition: FilterCondition, now: datetime
) -> bool:
    text_val = str(condition.value).strip()
    text_candidate = _item_text_field(item, condition.field)
    if text_candidate is not None:
        return _match_text(text_candidate, condition.operator, text_val)
    list_candidate = _item_list_field(item, condition.field)
    if list_candidate is not None:
        return _match_text_list(list_candidate, condition.operator, text_val)
    return _evaluate_numeric_or_date(item, condition, now)


def _evaluate_group(item: MediaItem, group: FilterGroup, now: datetime) -> bool:
    results = [
        *(_evaluate_condition(item, cond, now) for cond in group.conditions),
        *(
            _evaluate_group(item, sub, now)
            for sub in group.groups
            if not sub.is_empty()
        ),
    ]
    if not results:
        return True
    return all(results) if group.mode == "all" else any(results)


def evaluate_filter_group(
    items: Sequence[MediaItem],
    group: FilterGroup,
    *,
    now: datetime | None = None,
) -> list[MediaItem]:
    """Return the items in *items* matching *group*, preserving input order."""
    if group.is_empty():
        return []
    reference = now or utc_now()
    return [item for item in items if _evaluate_group(item, group, reference)]


_PLEX_OPERATOR_SUFFIX: frozendict[FilterOperator, str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        FilterOperator.IS: "=",
        FilterOperator.IS_NOT: "!=",
        FilterOperator.CONTAINS: "",
        FilterOperator.DOES_NOT_CONTAIN: "!",
        FilterOperator.STARTS_WITH: "<",
        FilterOperator.GTE: ">>",
        FilterOperator.LTE: "<<",
    }
)


def _compile_plex_condition(condition: FilterCondition) -> tuple[str, str]:
    plex_field = _PLEX_FIELD_MAP[condition.field]
    op = condition.operator
    val = condition.value

    if condition.field in {FilterField.UNPLAYED, FilterField.IN_PROGRESS}:
        flag = _to_bool(val)
        if op is FilterOperator.IS_NOT:
            flag = not flag
        return (plex_field, "1" if flag else "0")

    if condition.field in {
        FilterField.ADDED_WITHIN_DAYS,
        FilterField.RELEASED_WITHIN_DAYS,
    }:
        days = max(1, int(_to_float(val)))
        return (f"{plex_field}>>", f"-{days}d")

    if condition.field is FilterField.DECADE:
        decade = int(_to_float(val)) // 10 * 10
        key = f"{plex_field}!" if op is FilterOperator.IS_NOT else plex_field
        return (key, str(decade))

    if condition.field is FilterField.DURATION_MINUTES:
        ms = int(_to_float(val) * 60000)
        suffix = (
            ">>"
            if op is FilterOperator.GTE
            else "<<"
            if op is FilterOperator.LTE
            else ""
        )
        return (f"{plex_field}{suffix}", str(ms))

    suffix = _PLEX_OPERATOR_SUFFIX.get(op, "")
    return (f"{plex_field}{suffix}", str(val))


def _compile_plex_group_pairs(group: FilterGroup) -> list[tuple[str, str]]:
    items: list[list[tuple[str, str]]] = [
        [_compile_plex_condition(cond)] for cond in group.conditions
    ]
    for sub in group.groups:
        if sub.is_empty():
            continue
        sub_pairs = _compile_plex_group_pairs(sub)
        if sub_pairs:
            items.append([("push", "1"), *sub_pairs, ("pop", "1")])
    if not items:
        return []
    joined: list[tuple[str, str]] = []
    for index, segment in enumerate(items):
        if index > 0 and group.mode == "any":
            joined.append(("or", "1"))
        joined.extend(segment)
    return joined


def compile_plex_smart_filter(
    config: SmartCollectionConfig,
    *,
    managed_label: str | None = None,
) -> str:
    """Compile a SmartCollectionConfig into a Plex smart collection query string."""
    pairs: list[tuple[str, str]] = [("sort", _PLEX_SORT_MAP[config.sort_by])]
    if config.limit is not None:
        pairs.append(("limit", str(config.limit)))
    group = config.filter_group
    if managed_label:
        label_cond = FilterCondition(
            field=FilterField.LABEL,
            operator=FilterOperator.IS,
            value=managed_label,
        )
        if group.is_empty():
            group = FilterGroup(mode="all", conditions=[label_cond])
        elif group.mode == "all":
            if label_cond not in group.conditions:
                group = FilterGroup(
                    mode="all",
                    conditions=[label_cond, *group.conditions],
                    groups=group.groups,
                )
        else:
            group = FilterGroup(mode="all", conditions=[label_cond], groups=[group])
    group_pairs = _compile_plex_group_pairs(group)
    if group_pairs:
        pairs.extend([("push", "1"), *group_pairs, ("pop", "1")])
    return urllib.parse.urlencode(pairs, safe=":<>=!-")
