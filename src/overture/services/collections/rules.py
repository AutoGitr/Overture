"""Conversions between stored collection rules and the criteria they hold."""

lazy from collections.abc import Mapping, Sequence
lazy from itertools import batched

lazy from ...db.models.collection_group import CollectionGroup
lazy from ...db.models.collection_rule import CollectionRule
lazy from ...db.models.media_collection import CollectionLibrary, MediaCollection
lazy from ...domain import (
    FilterField,
    FilterOperator,
    MediaType,
    SourceType,
    library_server,
)
lazy from ...repositories.collection_items import CollectionItem
lazy from ...schemas.collections import (
    GROUP_CONDITIONS_MAX,
    GROUP_GROUPS_MAX,
    TMDB_ITEM_IDS_MAX,
    CollectionGenerator,
    CollectionLibraryCriteria,
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


def title_taken(title: str) -> str:
    """Why a collection cannot be titled *title*: a library of it has one so titled."""
    return f"One of its libraries already has a collection titled {title}"


#: Sources whose order is meaningful, which a new rule keeps by default.
ORDERED_SOURCES = frozenset(
    {SourceType.MDBLIST, SourceType.TMDB_LIST, SourceType.TMDB_ITEM}
)


def library_criteria(row: MediaCollection) -> list[CollectionLibraryCriteria]:
    """What each library selects; a library on its way out selects nothing."""
    return [
        CollectionLibraryCriteria(
            library_id=part.library_id,
            criteria=FilterGroup.model_validate(part.criteria),
        )
        for part in row.libraries
        if part.criteria is not None
    ]


def criteria_of(part: CollectionLibrary) -> FilterGroup:
    if part.criteria is None:
        raise RuntimeError("A library leaving its collection has no criteria")
    return FilterGroup.model_validate(part.criteria)


def apply_libraries(
    row: MediaCollection,
    libraries: Sequence[CollectionLibraryCriteria],
    types: Mapping[str, MediaType],
) -> None:
    """Make these the libraries the collection selects from.

    A library leaving with a server copy stays, without criteria, until the
    next sync removes the copy; saving never touches the server.
    """
    chosen = {entry.library_id: entry for entry in libraries}
    for part in list(row.libraries):
        entry = chosen.pop(part.library_id, None)
        if entry is not None:
            part.criteria = entry.criteria.model_dump(mode="json")
        elif part.server_item_id is None:
            row.libraries.remove(part)
        else:
            part.criteria = None
    row.libraries.extend(
        CollectionLibrary(
            collection_id=row.id or 0,
            library_id=library_id,
            media_type=types[library_id],
            server_id=library_server(library_id),
            criteria=entry.criteria.model_dump(mode="json"),
        )
        for library_id, entry in chosen.items()
    )


def rule_read(
    rule: CollectionRule | None, row: MediaCollection
) -> CollectionRuleRead | None:
    if rule is None:
        return None
    return CollectionRuleRead(
        **rule.model_dump(exclude={"id", "collection_id", "smart", "item_limit"}),
        libraries=library_criteria(row),
        smart=rule.smart,
        limit=rule.item_limit,
    )


def rule_row(collection_id: int, body: CollectionRuleWrite) -> CollectionRule:
    return CollectionRule(
        collection_id=collection_id,
        item_limit=body.limit,
        **body.model_dump(exclude={"libraries", "limit"}),
    )


def outdates_server(row: MediaCollection) -> bool:
    """A local save outdates a server copy; a seasonally withheld one has none."""
    return row.unsynced or bool(row.copies)


def member_criteria(
    row: MediaCollection, members: list[CollectionItem], *, franchise: int | None
) -> FilterGroup:
    """Criteria that select a collection's current members.

    Members that all belong to *franchise* are kept as that TMDB collection,
    so later films join it; otherwise each is named by the first ID it has of
    TMDB, TVDB and IMDb, else by title. TMDB IDs share sources as large as a
    source holds, and conditions past what one group holds go in nested
    groups of their own.

    Raises:
        PublicServiceError: 422 when it has no members, or more than criteria
            can name.
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
        *(
            SourceCondition(source=TmdbItemSource(tmdb_ids=list(ids)))
            for ids in batched(tmdb_ids, TMDB_ITEM_IDS_MAX, strict=False)
        ),
        *(_member_condition(item) for item in members if item.tmdb_id is None),
    ]
    if not conditions:
        raise PublicServiceError(422, f"{row.title} has no members to keep")
    if len(conditions) <= GROUP_CONDITIONS_MAX:
        return FilterGroup(mode="any", conditions=conditions)
    groups = [
        FilterGroup(mode="any", conditions=list(part))
        for part in batched(conditions, GROUP_CONDITIONS_MAX, strict=False)
    ]
    if len(groups) > GROUP_GROUPS_MAX:
        raise PublicServiceError(
            422,
            f"{row.title} holds more titles without a TMDB ID than criteria "
            "can name one by one",
        )
    return FilterGroup(mode="any", groups=groups)


def _member_condition(item: CollectionItem) -> FieldCondition:
    """Name a member without a TMDB ID by its TVDB or IMDb ID, else its title."""
    if item.tvdb_id is not None:
        return FieldCondition(field=FilterField.TVDB_ID, value=str(item.tvdb_id))
    if item.imdb_id:
        return FieldCondition(field=FilterField.IMDB_ID, value=item.imdb_id)
    return FieldCondition(field=FilterField.TITLE, value=item.title)


def shared_franchise(members: list[CollectionItem]) -> int | None:
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
    if group is None or group.generator is None:
        return None
    return CollectionGenerator.model_validate(group.generator)


def sole_franchise(libraries: Sequence[CollectionLibraryCriteria]) -> int | None:
    """The TMDB franchise a collection is: the one its criteria select, alone.

    Criteria naming several franchises, as a universe's do, make a collection
    of its own rather than any one of them.
    """
    franchises = {
        condition.source.collection_id
        for library in libraries
        for condition in library.criteria.source_conditions()
        if isinstance(condition.source, TmdbCollectionSource)
        and condition.operator is FilterOperator.IS
    }
    return next(iter(franchises)) if len(franchises) == 1 else None
