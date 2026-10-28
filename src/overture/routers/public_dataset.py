"""Public dataset router - opt-in curated art/theme sources."""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Path, Query
lazy from fastapi.responses import Response

lazy from ..dependencies import DatabaseDep, PublicDatasetDep, RuntimeDep
lazy from ..domain import CatalogMediaType
lazy from ..schemas.common import StatusResponse
lazy from ..schemas.public_dataset import (
    CatalogCounts,
    CatalogDraftsDiscard,
    CatalogDraftsDiscarded,
    CatalogDraftUpdate,
    CatalogEntryDetail,
    CatalogEntryRow,
    PublicDatasetEnabledRequest,
    PublicDatasetRecord,
    PublicDatasetSources,
    PublicDatasetStatus,
)
lazy from ..services.public_dataset.export import export_archive
lazy from .auth import require_auth
lazy from .parameters import CollectionIdPath, ItemIdPath

CatalogMediaTypePath = Annotated[CatalogMediaType, Path(description="Entry kind")]
EntryKeyPath = Annotated[
    str, Path(description="Entry name, as its file is named: tmdb-603")
]

router = APIRouter(
    prefix="/public-dataset",
    tags=["public-dataset"],
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
async def export_public_dataset_selections(
    database: DatabaseDep, runtime: RuntimeDep
) -> Response:
    """Download saved selections as an archive for an OvertureDB contribution."""
    return await export_archive(database, runtime.config_dir)


@router.get("/status")
async def get_public_dataset_status(dataset: PublicDatasetDep) -> PublicDatasetStatus:
    """Return public dataset status."""
    return await dataset.get_status()


@router.put("/enabled")
async def set_public_dataset_enabled(
    body: PublicDatasetEnabledRequest, dataset: PublicDatasetDep
) -> PublicDatasetStatus:
    """Turn the public dataset on or off."""
    return await dataset.set_enabled(body.enabled)


@router.post("/sync")
async def sync_public_dataset_now(dataset: PublicDatasetDep) -> StatusResponse:
    """Sync public dataset now."""
    return await dataset.sync_now()


@router.get("/items/{item_id}/sources")
async def get_public_dataset_sources(
    item_id: ItemIdPath, dataset: PublicDatasetDep
) -> PublicDatasetSources:
    """Return public dataset sources, including a normal not-found result."""
    return await dataset.get_sources_for_item(item_id)


@router.get("/items/{item_id}/record")
async def get_public_dataset_record(
    item_id: ItemIdPath, dataset: PublicDatasetDep
) -> PublicDatasetRecord:
    """Return public dataset record."""
    return await dataset.get_record_for_item(item_id)


@router.get("/collections/{collection_id}/record")
async def get_public_dataset_collection_record(
    collection_id: CollectionIdPath, dataset: PublicDatasetDep
) -> PublicDatasetRecord:
    """Return the catalog record of a library collection."""
    return await dataset.get_record_for_collection(collection_id)


@router.get("/catalog/{media_type}/{entry_key}/record")
async def get_catalog_entry_record(
    media_type: CatalogMediaTypePath, entry_key: EntryKeyPath, dataset: PublicDatasetDep
) -> PublicDatasetRecord:
    """Return the catalog record an entry name identifies."""
    return await dataset.get_record_for_entry(media_type, entry_key)


@router.get("/catalog/counts")
async def get_catalog_counts(dataset: PublicDatasetDep) -> CatalogCounts:
    """Return catalog and draft counts without reading every entry."""
    return await dataset.catalog.counts()


@router.get("/catalog")
async def list_catalog_entries(
    dataset: PublicDatasetDep,
    media_type: Annotated[CatalogMediaType, Query(description="Entry kind")],
) -> list[CatalogEntryRow]:
    """Return every catalog entry of a kind, with what the library holds of it."""
    return await dataset.catalog.list_entries(media_type)


@router.get("/catalog/{media_type}/{entry_key}")
async def get_catalog_entry(
    media_type: CatalogMediaTypePath, entry_key: EntryKeyPath, dataset: PublicDatasetDep
) -> CatalogEntryDetail:
    """Return one catalog entry with its local draft."""
    return await dataset.catalog.get_entry(media_type, entry_key)


@router.delete("/catalog/{media_type}/drafts")
async def discard_catalog_drafts(
    media_type: CatalogMediaTypePath,
    body: CatalogDraftsDiscard,
    dataset: PublicDatasetDep,
) -> CatalogDraftsDiscarded:
    """Discard the local drafts of the named entries."""
    return await dataset.catalog.discard_drafts(media_type, body)


@router.put("/catalog/{media_type}/{entry_key}/draft")
async def save_catalog_draft(
    media_type: CatalogMediaTypePath,
    entry_key: EntryKeyPath,
    body: CatalogDraftUpdate,
    dataset: PublicDatasetDep,
) -> CatalogEntryDetail:
    """Change an entry's local draft, to contribute later."""
    return await dataset.catalog.save_draft(media_type, entry_key, body)


@router.delete("/catalog/{media_type}/{entry_key}/draft")
async def discard_catalog_draft(
    media_type: CatalogMediaTypePath, entry_key: EntryKeyPath, dataset: PublicDatasetDep
) -> CatalogEntryDetail:
    """Discard an entry's local draft."""
    return await dataset.catalog.discard_draft(media_type, entry_key)
