"""Custom library filters: what they test, what they match, and saved ones."""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Path

lazy from ..dependencies import (
    LibraryFiltersDep,
    SavedFiltersDep,
    require_media_server,
)
lazy from ..schemas.common import StatusResponse
lazy from ..schemas.library_filters import (
    LibraryFilterCapabilities,
    LibraryFilterMatch,
    LibraryFilterMatchRequest,
    SavedFilterRead,
    SavedFilterWrite,
)
lazy from .auth import READS_ONLY, require_auth
lazy from .parameters import MediaTypeQuery

router = APIRouter(
    prefix="/library/filters",
    tags=["library-filters"],
    dependencies=[Depends(require_auth), Depends(require_media_server)],
)

SavedFilterIdPath = Annotated[int, Path(ge=1, description="Saved filter ID")]


@router.get("/capabilities")
async def get_library_filter_capabilities(
    filters: LibraryFiltersDep, media_type: MediaTypeQuery
) -> LibraryFilterCapabilities:
    """Describe the fields and sources custom filters of the media type test."""
    return filters.capabilities(media_type)


@router.post("/match", openapi_extra=READS_ONLY)
async def match_library_filter(
    body: LibraryFilterMatchRequest, filters: LibraryFiltersDep
) -> LibraryFilterMatch:
    """Return the titles each of a custom filter's conditions selects."""
    return await filters.match(body)


@router.get("/saved")
async def list_saved_filters(saved: SavedFiltersDep) -> list[SavedFilterRead]:
    """List every saved filter by name, with the media types it applies to."""
    return await saved.list()


@router.post("/saved")
async def create_saved_filter(
    body: SavedFilterWrite, saved: SavedFiltersDep
) -> SavedFilterRead:
    """Save a custom filter under a name."""
    return await saved.create(body)


@router.put("/saved/{filter_id}")
async def update_saved_filter(
    filter_id: SavedFilterIdPath, body: SavedFilterWrite, saved: SavedFiltersDep
) -> SavedFilterRead:
    """Rename a saved filter or change its conditions."""
    return await saved.update(filter_id, body)


@router.delete("/saved/{filter_id}")
async def delete_saved_filter(
    filter_id: SavedFilterIdPath, saved: SavedFiltersDep
) -> StatusResponse:
    """Forget a saved filter."""
    return await saved.delete(filter_id)
