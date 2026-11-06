"""Rows and rules that make a stored collection, in one library unless a test says."""

lazy from typing import Any

lazy from overture.db.models.collection_rule import CollectionRule
lazy from overture.db.models.media_collection import CollectionLibrary, MediaCollection
lazy from overture.domain import MediaType
lazy from overture.schemas.collections import (
    CollectionLibraryCriteria,
    CollectionRuleWrite,
    FilterGroup,
    SourceCondition,
    TmdbItemSource,
)

_CRITERIA = FilterGroup(
    conditions=[SourceCondition(source=TmdbItemSource(tmdb_ids=[1]))]
)


def managing_rule(collection_id: int) -> CollectionRule:
    """A rule for *collection_id*; without one, a collection only accepts adoption."""
    return CollectionRule(collection_id=collection_id)


def stored_collection(
    *,
    server_item_id: str | None = None,
    media_type: MediaType = MediaType.MOVIE,
    library_id: str | None = None,
    **fields: Any,
) -> MediaCollection:
    """A collection held by one library, as a sync or a save stores it."""
    row = MediaCollection(**fields)
    row.libraries = [
        CollectionLibrary(
            collection_id=0,
            library_id=library_id or "library",
            media_type=media_type,
            server_item_id=server_item_id,
            criteria_json=_CRITERIA.model_dump_json(),
        )
    ]
    return row


def library_rule(
    *, criteria: FilterGroup, library_id: str = "movies", **fields: object
) -> CollectionRuleWrite:
    """A rule selecting *criteria* from one library."""
    return CollectionRuleWrite.model_validate(
        {
            "libraries": [
                CollectionLibraryCriteria(library_id=library_id, criteria=criteria)
            ],
            **fields,
        }
    )
