"""Rows and rules that make a stored collection, in one library unless a test says."""

lazy from typing import Any

lazy from overture.db.ledger import Destination, Evidence, observe, place
lazy from overture.db.models.collection_group import CollectionGroup
lazy from overture.db.models.collection_rule import CollectionRule
lazy from overture.db.models.media_collection import CollectionLibrary, MediaCollection
lazy from overture.domain import DeliveryChannel, MediaType, ServerAsset
lazy from overture.schemas.collections import (
    CollectionLibraryCriteria,
    CollectionRuleWrite,
    FilterGroup,
    SourceCondition,
    TmdbItemSource,
)
lazy from tests.factories import build

_CRITERIA = FilterGroup(
    conditions=[SourceCondition(source=TmdbItemSource(tmdb_ids=[1]))]
)


def copy_id(row: MediaCollection) -> str | None:
    """The server's ID of a collection held on one server."""
    return next((part.server_item_id for part in row.copies), None)


def managing_rule(collection_id: int) -> CollectionRule:
    """A rule for *collection_id*; without one, a collection only accepts adoption."""
    return CollectionRule(collection_id=collection_id)


def stored_collection(
    *,
    server_item_id: str | None = None,
    media_type: MediaType = MediaType.MOVIE,
    library_id: str | None = None,
    group: str | None = None,
    **fields: Any,
) -> MediaCollection:
    """A collection held by one library, as a sync or a save stores it."""
    server_path = fields.pop("server_path", None)
    row = build(MediaCollection, **fields)
    if group is not None:
        row.group = CollectionGroup(name=group)
    row.libraries = [
        CollectionLibrary(
            server_id=1,
            collection_id=0,
            library_id=library_id or "1:library",
            media_type=media_type,
            server_item_id=server_item_id,
            server_path=server_path,
            criteria=_CRITERIA.model_dump(mode="json"),
        )
    ]
    return row


def library_rule(
    *, criteria: FilterGroup, library_id: str = "1:movies", **fields: object
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


def shown_on_server(
    row: MediaCollection,
    *,
    poster: str | None = None,
    background: str | None = None,
    theme: str | None = None,
) -> MediaCollection:
    """Place the row's assets on its first copy and record what that copy shows.

    Each value is what the server names its current image or theme by.
    """
    part = row.libraries[0]
    copy = Destination(part.server_id, part.server_item_id, DeliveryChannel.UPLOAD)
    for kind, ref in (
        (ServerAsset.POSTER, poster),
        (ServerAsset.BACKGROUND, background),
        (ServerAsset.THEME, theme),
    ):
        place(row, kind, (copy,))
        if ref is not None:
            observe(row, kind, copy, Evidence.DIFFERENT, ref=ref)
    return row
