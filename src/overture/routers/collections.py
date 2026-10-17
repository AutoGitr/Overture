"""Collections router - list collections and manage collection themes."""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Path
lazy from fastapi.responses import Response

lazy from ..dependencies import CollectionsDep
lazy from ..schemas.collections import (
    BulkCollectionMonitorUpdate,
    CollectionRead,
    CollectionThemeStatusResponse,
    DeleteCollectionThemeResponse,
    SetCollectionThemeRequest,
)
lazy from ..schemas.common import (
    BulkMonitorResponse,
    EnqueuedJobResponse,
    MonitoredResponse,
    MonitorUpdate,
)
lazy from .auth import require_auth
lazy from .parameters import ArtTypePath, ImageSizeQuery, MediaTypeQuery

CollectionIdPath = Annotated[str, Path(description="Collection rating key or ID")]

router = APIRouter(
    prefix="/collections",
    tags=["collections"],
    dependencies=[Depends(require_auth)],
)


@router.get("")
async def list_collections(
    collections: CollectionsDep, media_type: MediaTypeQuery
) -> list[CollectionRead]:
    """Return all collections for the given media type from the active server."""
    return await collections.list_collections(media_type)


@router.get("/{collection_id}/theme")
async def get_collection_theme(
    collection_id: CollectionIdPath,
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
) -> CollectionThemeStatusResponse:
    """Return the current theme status for a collection."""
    return await collections.get_collection_theme(collection_id, media_type)


@router.put("/{collection_id}/theme")
async def set_collection_theme(
    collection_id: CollectionIdPath,
    body: SetCollectionThemeRequest,
    collections: CollectionsDep,
) -> EnqueuedJobResponse:
    """Queue a YouTube track for upload as the theme for a collection."""
    return await collections.set_collection_theme(collection_id, body)


@router.delete("/{collection_id}/theme")
async def delete_collection_theme(
    collection_id: CollectionIdPath,
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
) -> DeleteCollectionThemeResponse:
    """Remove the theme from a collection and clear the local DB record."""
    return await collections.delete_collection_theme(collection_id, media_type)


@router.patch("/{collection_id}/monitored")
async def set_collection_monitored(
    collection_id: CollectionIdPath,
    body: MonitorUpdate,
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
) -> MonitoredResponse:
    """Set whether a collection is monitored."""
    return await collections.set_collection_monitored(
        collection_id, media_type, body.monitored
    )


@router.patch("/bulk-monitored")
async def bulk_set_collection_monitored(
    body: BulkCollectionMonitorUpdate, collections: CollectionsDep
) -> BulkMonitorResponse:
    """Set the monitored flag for multiple collections at once."""
    return await collections.bulk_set_collection_monitored(
        body.collection_ids, body.media_type, body.monitored
    )


@router.get("/{collection_id}/image/{art_type}", response_class=Response)
async def proxy_collection_image(
    collection_id: CollectionIdPath,
    art_type: ArtTypePath,
    collections: CollectionsDep,
    size: ImageSizeQuery = None,
) -> Response:
    """Proxy a collection's poster or background from the media server."""
    return await collections.proxy_collection_image(collection_id, art_type, size)
