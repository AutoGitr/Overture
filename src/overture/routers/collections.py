"""Collections router - list collections and manage collection themes."""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Path, Query
lazy from fastapi.responses import Response

lazy from ..dependencies import ArtDep, CollectionsDep, require_media_server
lazy from ..domain import MATCH_THRESHOLD_DEFAULT, MATCH_THRESHOLD_MAX, FilterField
lazy from ..schemas.art import ArtMatchResponse, ArtSourcesResponse, SaveArtRequest
lazy from ..schemas.collections import (
    ArrTagRead,
    BulkCollectionMonitorUpdate,
    BulkCollectionOperation,
    BulkCollectionOperationResult,
    CollectionArrOptions,
    CollectionArtwork,
    CollectionCapabilities,
    CollectionCreate,
    CollectionDetail,
    CollectionFieldValue,
    CollectionGroupDelete,
    CollectionGroupPolicy,
    CollectionGroupRename,
    CollectionGroupSyncResult,
    CollectionMembersUpdate,
    CollectionMissing,
    CollectionOptions,
    CollectionPolicyBase,
    CollectionPresetRead,
    CollectionPresetSave,
    CollectionPreview,
    CollectionPreviewRequest,
    CollectionRead,
    CollectionRequest,
    CollectionRequestResult,
    CollectionRuleRead,
    CollectionRuleWrite,
    CollectionSetEntry,
    CollectionSetPreview,
    CollectionSyncResponse,
    CollectionTakeOver,
    CollectionThemeSources,
    CollectionThemeStatusResponse,
    DeleteCollectionThemeResponse,
    SetCollectionThemeRequest,
)
lazy from ..schemas.common import (
    BulkMonitorResponse,
    EnqueuedJobResponse,
    MonitoredResponse,
    MonitorUpdate,
    StatusResponse,
)
lazy from .auth import require_auth
lazy from .parameters import (
    ArtTypePath,
    CollectionIdPath,
    ImageSizeQuery,
    MediaTypeQuery,
)

ToServerQuery = Annotated[
    bool, Query(description="Also send the change to the media server")
]

router = APIRouter(
    prefix="/collections",
    tags=["collections"],
    dependencies=[Depends(require_auth), Depends(require_media_server)],
)


@router.get("")
async def list_collections(
    collections: CollectionsDep, media_type: MediaTypeQuery
) -> list[CollectionRead]:
    """Return the collections the last sync listed for the media type."""
    return await collections.list_collections(media_type)


@router.get("/groups")
async def list_collection_groups(
    collections: CollectionsDep, media_type: MediaTypeQuery
) -> list[str]:
    """Return default and custom collection groups for this media type."""
    return await collections.groups(media_type)


@router.get("/defaults")
async def get_collection_defaults(
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str | None, Query(max_length=200)] = None,
) -> CollectionPolicyBase:
    """Resolve inherited values for collection form placeholders."""
    return await collections.inherited_policy(media_type, name)


@router.get("/capabilities")
async def get_collection_capabilities(
    collections: CollectionsDep, media_type: MediaTypeQuery
) -> CollectionCapabilities:
    """Describe the fields, sources, orders and sets the media server supports."""
    return collections.capabilities(media_type)


@router.get("/presets")
async def list_collection_presets(
    collections: CollectionsDep, media_type: MediaTypeQuery
) -> list[CollectionPresetRead]:
    """Return saved presets, then the built-in ones the server can evaluate."""
    return await collections.presets(media_type)


@router.post("/presets")
async def save_collection_preset(
    body: CollectionPresetSave, collections: CollectionsDep
) -> CollectionPresetRead:
    """Keep a collection or set as a preset."""
    return await collections.save_preset(body)


@router.delete("/presets/{preset_id}")
async def delete_collection_preset(
    preset_id: Annotated[int, Path(gt=0)], collections: CollectionsDep
) -> StatusResponse:
    """Forget a saved preset."""
    return await collections.delete_preset(preset_id)


@router.post("/preview")
async def preview_collection(
    body: CollectionPreviewRequest, collections: CollectionsDep
) -> CollectionPreview:
    """Show what criteria select now, before the collection is saved."""
    return await collections.preview(body)


@router.get("/arr-options")
async def get_collection_arr_options(
    collections: CollectionsDep, media_type: MediaTypeQuery
) -> CollectionArrOptions:
    """List where Radarr or Sonarr can put requested titles."""
    return await collections.arr_options(media_type)


@router.get("/field-values")
async def list_collection_field_values(
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
    library_id: Annotated[str, Query(min_length=1, max_length=200)],
    field: FilterField,
) -> list[CollectionFieldValue]:
    """List a criteria field's values in a library, most common first."""
    return await collections.field_values(media_type, library_id, field)


@router.post("/sets/preview")
async def preview_collection_set(
    body: CollectionSetPreview, collections: CollectionsDep
) -> list[CollectionSetEntry]:
    """Preview the collections a set makes in its library."""
    return await collections.preview_set(body)


@router.patch("/groups")
async def rename_collection_group(
    body: CollectionGroupRename,
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> StatusResponse:
    """Rename a group and all its collection assignments."""
    return await collections.rename_group(media_type, name, body.name)


@router.delete("/groups")
async def delete_collection_group(
    body: CollectionGroupDelete,
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> BulkCollectionOperationResult:
    """Delete a group, optionally deleting its collections in either application."""
    return await collections.delete_group(media_type, name, body)


@router.get("/group-policy")
async def get_collection_group_policy(
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> CollectionGroupPolicy:
    """Read a group's nullable overrides for the active media server."""
    return await collections.group_policy(media_type, name)


@router.put("/group-policy")
async def save_collection_group_policy(
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
    body: CollectionGroupPolicy,
) -> CollectionGroupPolicy:
    """Save defaults inherited by collections assigned to this group."""
    return await collections.save_group_policy(media_type, name, body)


@router.post("/group-policy/apply")
async def apply_collection_group_policy(
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> BulkCollectionOperationResult:
    """Apply group defaults while preserving each collection's explicit overrides."""
    return await collections.apply_group_policy(media_type, name)


@router.post("/group-policy/sync")
async def sync_collection_group(
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> CollectionGroupSyncResult:
    """Run the group's collection set, then sync its collections' criteria."""
    return await collections.sync_group(media_type, name)


@router.get("/tags/radarr")
async def list_radarr_tags(collections: CollectionsDep) -> list[ArrTagRead]:
    """Return available Radarr tags when Radarr is configured."""
    return await collections.list_radarr_tags()


@router.get("/tags/sonarr")
async def list_sonarr_tags(collections: CollectionsDep) -> list[ArrTagRead]:
    """Return available Sonarr tags when Sonarr is configured."""
    return await collections.list_sonarr_tags()


@router.post("/bulk-operation")
async def bulk_operate_collections(
    collections: CollectionsDep,
    body: BulkCollectionOperation,
) -> BulkCollectionOperationResult:
    """Run one operation independently for every selected collection."""
    return await collections.bulk_operation(body)


@router.get("/{collection_id}")
async def get_collection(
    collection_id: CollectionIdPath,
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
) -> CollectionDetail:
    """Return one collection with its members and catalog themes."""
    return await collections.get_collection(collection_id, media_type)


@router.get("/{collection_id}/sources")
async def get_collection_sources(
    collection_id: CollectionIdPath,
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
) -> CollectionThemeSources:
    """Return the matched catalog's collection theme candidates."""
    detail = await collections.get_collection(collection_id, media_type)
    return CollectionThemeSources(
        youtube_id_overturedb=detail.youtube_id_overturedb,
        youtube_id_themerrdb=detail.youtube_id_themerrdb,
    )


@router.get("/{collection_id}/missing")
async def get_collection_missing(
    collection_id: CollectionIdPath,
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
) -> CollectionMissing:
    """List titles the collection's lists hold that the library lacks."""
    return await collections.missing(collection_id, media_type)


@router.post("/{collection_id}/missing/request")
async def request_collection_missing(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    body: CollectionRequest,
    collections: CollectionsDep,
) -> CollectionRequestResult:
    """Ask Radarr or Sonarr for the collection's missing titles."""
    return await collections.request_missing(collection_id, media_type, body)


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
    """Queue a YouTube track to become the theme of a collection."""
    return await collections.set_collection_theme(collection_id, body)


@router.delete("/{collection_id}/theme")
async def delete_collection_theme(
    collection_id: CollectionIdPath,
    collections: CollectionsDep,
    media_type: MediaTypeQuery,
) -> DeleteCollectionThemeResponse:
    """Remove the theme from a collection and clear its stored record."""
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


@router.post("")
async def create_collection(
    body: CollectionCreate, collections: CollectionsDep, to_server: ToServerQuery = True
) -> CollectionDetail:
    """Create a collection in a server library, or only in Overture."""
    return await collections.create(body, sync=to_server)


@router.put("/{collection_id}")
async def update_collection(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    body: CollectionOptions,
    collections: CollectionsDep,
    to_server: ToServerQuery = True,
) -> CollectionDetail:
    """Update collection metadata and display options."""
    return await collections.update(collection_id, media_type, body, sync=to_server)


@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    collections: CollectionsDep,
) -> StatusResponse:
    """Delete the collection while preserving its media."""
    return await collections.delete(collection_id, media_type)


@router.put("/{collection_id}/members")
async def set_collection_members(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    body: CollectionMembersUpdate,
    collections: CollectionsDep,
    to_server: ToServerQuery = True,
) -> CollectionDetail:
    """Replace collection membership and order."""
    return await collections.set_members(
        collection_id, media_type, body, sync=to_server
    )


@router.put("/{collection_id}/rule")
async def save_collection_rule(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    body: CollectionRuleWrite,
    collections: CollectionsDep,
) -> CollectionRuleRead:
    """Save a collection's criteria and inheritance overrides."""
    return await collections.save_rule(collection_id, media_type, body)


@router.delete("/{collection_id}/rule")
async def delete_collection_rule(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    collections: CollectionsDep,
) -> StatusResponse:
    """Remove a rule while keeping current membership."""
    return await collections.delete_rule(collection_id, media_type)


@router.post("/{collection_id}/take-over")
async def take_over_collection(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    body: CollectionTakeOver,
    collections: CollectionsDep,
) -> CollectionDetail:
    """Let Overture manage a collection made outside it, keeping what it holds."""
    return await collections.take_over(collection_id, media_type, body)


@router.post("/{collection_id}/sync")
async def sync_collection(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    collections: CollectionsDep,
) -> CollectionSyncResponse:
    """Make the media server match the collection saved in Overture."""
    return await collections.sync(collection_id, media_type)


@router.delete("/{collection_id}/art")
async def clear_all_collection_art(
    collection_id: CollectionIdPath, media_type: MediaTypeQuery, art: ArtDep
) -> CollectionArtwork:
    """Forget all selected collection artwork, preserving the server copies."""
    return await art.clear_collection(collection_id, media_type, None)


@router.delete("/{collection_id}/art/{art_type}")
async def clear_collection_art(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    art_type: ArtTypePath,
    art: ArtDep,
) -> CollectionArtwork:
    """Forget one selected collection artwork slot."""
    return await art.clear_collection(collection_id, media_type, art_type)


@router.get("/{collection_id}/art/{art_type}/sources")
async def get_collection_art_sources(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    art_type: ArtTypePath,
    art: ArtDep,
) -> ArtSourcesResponse:
    """Browse shared collection artwork sources."""
    return await art.get_collection_sources(collection_id, media_type, art_type)


@router.put("/{collection_id}/art/{art_type}")
async def save_collection_art(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    art_type: ArtTypePath,
    body: SaveArtRequest,
    art: ArtDep,
) -> StatusResponse:
    """Validate and upload artwork to a collection."""
    return await art.save_collection(collection_id, media_type, art_type, body)


@router.post("/{collection_id}/art/{art_type}/match")
async def match_collection_art(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    art_type: ArtTypePath,
    art: ArtDep,
    threshold: Annotated[
        int, Query(ge=0, le=MATCH_THRESHOLD_MAX)
    ] = MATCH_THRESHOLD_DEFAULT,
) -> ArtMatchResponse:
    """Rank collection art using the shared perceptual hash matcher."""
    return await art.match_collection(collection_id, media_type, art_type, threshold)
