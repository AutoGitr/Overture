"""Catalog router - opt-in curated art/theme sources."""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Path, Query
lazy from fastapi.responses import Response

lazy from ..dependencies import CatalogDep
lazy from ..domain import CatalogMediaType
lazy from ..schemas.catalog import (
    CatalogCounts,
    CatalogDraftsDiscard,
    CatalogDraftsDiscarded,
    CatalogDraftUpdate,
    CatalogEnabledRequest,
    CatalogEntryDetail,
    CatalogEntryRow,
    CatalogRecord,
    CatalogSources,
    CatalogStatus,
    ContributionIssue,
)
lazy from ..schemas.common import StatusResponse
lazy from .auth import require_auth
lazy from .parameters import CollectionIdPath, ItemIdPath

CatalogMediaTypePath = Annotated[CatalogMediaType, Path(description="Entry kind")]
EntryKeyPath = Annotated[
    str, Path(description="Entry name, as its file is named: tmdb-603")
]

router = APIRouter(
    prefix="/catalog",
    tags=["catalog"],
    dependencies=[Depends(require_auth)],
)


@router.get(
    "/export",
    response_class=Response,
    responses={
        200: {
            "content": {
                "application/zip": {"schema": {"type": "string", "format": "binary"}}
            }
        }
    },
)
async def export_catalog_selections(catalog: CatalogDep) -> Response:
    """Download saved selections as an archive for an OvertureDB contribution."""
    return await catalog.export_selections()


@router.get("/status")
async def get_catalog_status(catalog: CatalogDep) -> CatalogStatus:
    """Return catalog status."""
    return await catalog.get_status()


@router.put("/enabled")
async def set_catalog_enabled(
    body: CatalogEnabledRequest, catalog: CatalogDep
) -> CatalogStatus:
    """Turn the catalog on or off."""
    return await catalog.set_enabled(body.enabled)


@router.post("/sync")
async def sync_catalog_now(catalog: CatalogDep) -> StatusResponse:
    """Sync catalog now."""
    return await catalog.sync_now()


@router.get("/items/{item_id}/sources")
async def get_catalog_sources(
    item_id: ItemIdPath, catalog: CatalogDep
) -> CatalogSources:
    """Return catalog sources, including a normal not-found result."""
    return await catalog.get_sources_for_item(item_id)


@router.get("/items/{item_id}/record")
async def get_catalog_record(item_id: ItemIdPath, catalog: CatalogDep) -> CatalogRecord:
    """Return catalog record."""
    return await catalog.get_record_for_item(item_id)


@router.get("/collections/{collection_id}/record")
async def get_catalog_collection_record(
    collection_id: CollectionIdPath, catalog: CatalogDep
) -> CatalogRecord:
    """Return the catalog record of a library collection."""
    return await catalog.get_record_for_collection(collection_id)


@router.get("/items/{item_id}/issue")
async def get_catalog_item_issue(
    item_id: ItemIdPath, catalog: CatalogDep
) -> ContributionIssue:
    """Return a prefilled issue contributing an item's saved selections."""
    return await catalog.get_issue_for_item(item_id)


@router.get("/collections/{collection_id}/issue")
async def get_catalog_collection_issue(
    collection_id: CollectionIdPath, catalog: CatalogDep
) -> ContributionIssue:
    """Return a prefilled issue contributing a collection's art and theme."""
    return await catalog.get_issue_for_collection(collection_id)


@router.get("/catalog/{media_type}/{entry_key}/record")
async def get_catalog_entry_record(
    media_type: CatalogMediaTypePath, entry_key: EntryKeyPath, catalog: CatalogDep
) -> CatalogRecord:
    """Return the catalog record an entry name identifies."""
    return await catalog.get_record_for_entry(media_type, entry_key)


@router.get("/catalog/counts")
async def get_catalog_counts(catalog: CatalogDep) -> CatalogCounts:
    """Return catalog and draft counts without reading every entry."""
    return await catalog.browser.counts()


@router.get("/catalog")
async def list_catalog_entries(
    catalog: CatalogDep,
    media_type: Annotated[CatalogMediaType, Query(description="Entry kind")],
) -> list[CatalogEntryRow]:
    """Return every catalog entry of a kind, with what the library holds of it."""
    return await catalog.browser.list_entries(media_type)


@router.get("/catalog/{media_type}/{entry_key}")
async def get_catalog_entry(
    media_type: CatalogMediaTypePath, entry_key: EntryKeyPath, catalog: CatalogDep
) -> CatalogEntryDetail:
    """Return one catalog entry with its local draft."""
    return await catalog.browser.get_entry(media_type, entry_key)


@router.delete("/catalog/{media_type}/drafts")
async def discard_catalog_drafts(
    media_type: CatalogMediaTypePath,
    body: CatalogDraftsDiscard,
    catalog: CatalogDep,
) -> CatalogDraftsDiscarded:
    """Discard the local drafts of the named entries."""
    return await catalog.browser.discard_drafts(media_type, body)


@router.put("/catalog/{media_type}/{entry_key}/draft")
async def save_catalog_draft(
    media_type: CatalogMediaTypePath,
    entry_key: EntryKeyPath,
    body: CatalogDraftUpdate,
    catalog: CatalogDep,
) -> CatalogEntryDetail:
    """Change an entry's local draft, to contribute later."""
    return await catalog.browser.save_draft(media_type, entry_key, body)


@router.delete("/catalog/{media_type}/{entry_key}/draft")
async def discard_catalog_draft(
    media_type: CatalogMediaTypePath, entry_key: EntryKeyPath, catalog: CatalogDep
) -> CatalogEntryDetail:
    """Discard an entry's local draft."""
    return await catalog.browser.discard_draft(media_type, entry_key)
