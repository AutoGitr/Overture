"""Public dataset router - opt-in curated art/theme sources."""

lazy from fastapi import APIRouter, Depends
lazy from fastapi.responses import Response

lazy from ..dependencies import DatabaseDep, PublicDatasetDep, RuntimeDep
lazy from ..schemas.common import StatusResponse
lazy from ..schemas.public_dataset import (
    PublicDatasetEnabledRequest,
    PublicDatasetRecord,
    PublicDatasetSources,
    PublicDatasetStatus,
)
lazy from ..services.public_dataset.export import export_archive
lazy from .auth import require_auth
lazy from .parameters import ItemIdPath

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
