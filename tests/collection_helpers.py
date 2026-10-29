"""Rows that make a stored collection one Overture manages."""

lazy from overture.db.models.collection_rule import CollectionRule
lazy from overture.schemas.collections import (
    FilterGroup,
    SourceCondition,
    TmdbItemSource,
)


def managing_rule(collection_id: int) -> CollectionRule:
    """A rule for *collection_id*; without one, a collection only accepts take-over."""
    criteria = FilterGroup(
        conditions=[SourceCondition(source=TmdbItemSource(tmdb_ids=[1]))]
    )
    return CollectionRule(
        collection_id=collection_id, criteria_json=criteria.model_dump_json()
    )
