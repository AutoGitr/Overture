"""Library router - items and seasons."""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Query
lazy from fastapi.responses import Response

lazy from ..dependencies import LibraryDep, SessionDep
lazy from ..domain import ArtType, MediaType
lazy from ..schemas.common import (
    MonitoredResponse,
    MonitorUpdate,
    Status,
    StatusResponse,
)
lazy from ..schemas.library import (
    BulkItemOperation,
    BulkItemOperationResult,
    FolderRootsResponse,
    LibrarySectionRead,
    MediaItemListResponse,
    MediaItemRead,
    SeasonRead,
)
lazy from .auth import require_auth
lazy from .parameters import (
    ArtTypePath,
    ImageCacheKeyQuery,
    ImageSizeQuery,
    ImageVersionQuery,
    ItemIdPath,
    SeasonIdPath,
)

MediaTypeFilter = Annotated[
    MediaType | None, Query(description="Only items of this media type")
]

router = APIRouter(
    prefix="/library", tags=["library"], dependencies=[Depends(require_auth)]
)


@router.get("/items/{item_id}/provider-art", response_class=Response)
async def proxy_item_provider_art(
    item_id: ItemIdPath,
    library: LibraryDep,
    art_type: Annotated[
        ArtType, Query(alias="type", description="An item slot")
    ] = ArtType.POSTER,
    size: ImageSizeQuery = None,
    _cache_key: ImageCacheKeyQuery = None,
) -> Response:
    """Proxy the current poster or background from the media server for an item."""
    return await library.proxy_item_provider_art(item_id, art_type, size)


@router.get("/seasons/{season_id}/provider-art", response_class=Response)
async def proxy_season_provider_art(
    season_id: SeasonIdPath,
    library: LibraryDep,
    size: ImageSizeQuery = None,
    _cache_key: ImageCacheKeyQuery = None,
) -> Response:
    """Proxy the current poster from the media server for a season."""
    return await library.proxy_season_provider_art(season_id, size)


@router.get("/libraries")
async def get_libraries(
    library: LibraryDep, media_type: MediaTypeFilter = None
) -> list[LibrarySectionRead]:
    """Return all distinct libraries for a media type, with counts and titles."""
    return await library.get_libraries(media_type)


@router.get("/folder-roots")
async def get_folder_roots(db: SessionDep, library: LibraryDep) -> FolderRootsResponse:
    """Return unique root folder paths derived from media item folder values."""
    return await library.get_folder_roots(db)


@router.get("/items")
async def list_items(
    db: SessionDep, library: LibraryDep, media_type: MediaTypeFilter = None
) -> MediaItemListResponse:
    """List all visible media items; the client filters, searches and sorts."""
    return await library.list_items(db, media_type=media_type)


@router.get("/items/{item_id}")
async def get_item(
    item_id: ItemIdPath, db: SessionDep, library: LibraryDep
) -> MediaItemRead:
    """Get a single media item."""
    return await library.get_item(db, item_id)


@router.patch("/items/{item_id}/monitored")
async def set_monitored(
    item_id: ItemIdPath, body: MonitorUpdate, library: LibraryDep
) -> MonitoredResponse:
    """Set whether an item is monitored."""
    return await library.set_monitored(item_id, body.monitored)


@router.delete("/items/{item_id}")
async def delete_item(item_id: ItemIdPath, library: LibraryDep) -> StatusResponse:
    """Delete an item completely from the database."""
    await library.delete_item(item_id)
    return StatusResponse(status=Status.DELETED)


@router.post("/items/bulk-operation")
async def bulk_operate_items(
    body: BulkItemOperation, library: LibraryDep
) -> BulkItemOperationResult:
    """Change item records in bulk without changing local or media server files."""
    return await library.bulk_operate_items(body)


@router.get("/items/{item_id}/seasons")
async def get_seasons(
    item_id: ItemIdPath, db: SessionDep, library: LibraryDep
) -> list[SeasonRead]:
    """Get season list for a show."""
    return await library.get_seasons(db, item_id)


@router.get("/seasons/{season_id}/local-image", response_class=Response)
async def serve_local_season_image(
    season_id: SeasonIdPath,
    db: SessionDep,
    library: LibraryDep,
    size: ImageSizeQuery = None,
    version: ImageVersionQuery = None,
) -> Response:
    """Serve a show season poster from disk."""
    return await library.serve_local_season_image(
        db, season_id=season_id, size=size, version=version
    )


@router.get("/items/{item_id}/local-image/{art_type}", response_class=Response)
async def serve_local_image(
    item_id: ItemIdPath,
    art_type: ArtTypePath,
    db: SessionDep,
    library: LibraryDep,
    size: ImageSizeQuery = None,
    version: ImageVersionQuery = None,
) -> Response:
    """Serve a locally stored poster or background for a movie or show."""
    return await library.serve_local_image(
        db, item_id=item_id, art_type=art_type, size=size, version=version
    )
