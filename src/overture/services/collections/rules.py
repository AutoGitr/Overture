"""Conversions between stored collection rules and the criteria they hold."""

lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import MediaCollection
lazy from ...db.models.media_item import MediaItem
lazy from ...domain import FilterField, FilterOperator, SourceType
lazy from ...schemas.collections import (
    CollectionGenerator,
    CollectionRuleRead,
    CollectionRuleWrite,
    Condition,
    FieldCondition,
    FilterGroup,
    SourceCondition,
    TmdbCollectionSource,
    TmdbItemSource,
)
lazy from ...schemas.validators import check_group_name
lazy from ...utils.errors import PublicServiceError

TITLE_TAKEN = "A collection with this title already exists in this library"

#: Sources whose order is meaningful, which a new rule keeps by default.
ORDERED_SOURCES = frozenset(
    {SourceType.MDBLIST, SourceType.TMDB_LIST, SourceType.TMDB_ITEM}
)


def criteria(rule: CollectionRule) -> FilterGroup:
    return FilterGroup.model_validate_json(rule.criteria_json)


def rule_read(rule: CollectionRule | None) -> CollectionRuleRead | None:
    if rule is None:
        return None
    return CollectionRuleRead(
        **rule.model_dump(
            exclude={"id", "collection_id", "criteria_json", "smart", "item_limit"}
        ),
        criteria=criteria(rule),
        smart=rule.smart,
        limit=rule.item_limit,
    )


def rule_row(collection_id: int, body: CollectionRuleWrite) -> CollectionRule:
    return CollectionRule(
        collection_id=collection_id,
        criteria_json=body.criteria.model_dump_json(),
        item_limit=body.limit,
        **body.model_dump(exclude={"criteria", "limit"}),
    )


def outdates_server(row: MediaCollection) -> bool:
    """A local save outdates a server copy; a seasonally withheld one has none."""
    return row.unsynced or row.server_item_id is not None


def never_created(row: MediaCollection) -> bool:
    """Saved in Overture only, so the scheduler leaves it until it is synced."""
    return row.unsynced and row.server_item_id is None


def member_criteria(
    row: MediaCollection, members: list[MediaItem], *, franchise: int | None
) -> FilterGroup:
    """Criteria that select a collection's current members.

    Members that all belong to *franchise* are kept as that TMDB collection,
    so later films join it; otherwise they are named by TMDB ID where they
    have one, else by title.
    """
    if franchise is not None:
        return FilterGroup(
            mode="all",
            conditions=[
                SourceCondition(source=TmdbCollectionSource(collection_id=franchise))
            ],
        )
    tmdb_ids = [item.tmdb_id for item in members if item.tmdb_id is not None]
    conditions: list[Condition] = [
        FieldCondition(field=FilterField.TITLE, value=item.title)
        for item in members
        if item.tmdb_id is None
    ]
    if tmdb_ids:
        conditions.insert(0, SourceCondition(source=TmdbItemSource(tmdb_ids=tmdb_ids)))
    if not conditions:
        raise PublicServiceError(422, f"{row.title} has no members to keep")
    return FilterGroup(mode="any", conditions=conditions)


def shared_franchise(members: list[MediaItem]) -> int | None:
    """The TMDB collection every member belongs to, when they share one."""
    franchises = {item.tmdb_collection_id for item in members}
    return next(iter(franchises)) if len(franchises) == 1 else None


def group_name(name: str) -> str:
    """Return a stored group's name, stripped, refusing empty or reserved ones.

    Raises:
        PublicServiceError: 422 for an empty or reserved name.
    """
    name = name.strip()
    if not name:
        raise PublicServiceError(422, "A group needs a name")
    try:
        return check_group_name(name)
    except ValueError as exc:
        raise PublicServiceError(422, str(exc)) from exc


def generator(group: CollectionGroup | None) -> CollectionGenerator | None:
    if group is None or not group.generator_json:
        return None
    return CollectionGenerator.model_validate_json(group.generator_json)


def franchise_ids(criteria: FilterGroup) -> set[int]:
    return {
        condition.source.collection_id
        for condition in criteria.source_conditions()
        if isinstance(condition.source, TmdbCollectionSource)
        and condition.operator is FilterOperator.IS
    }
