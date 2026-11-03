"""Collections router - list collections and manage collection themes."""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Path, Query
lazy from fastapi.responses import Response

lazy from ..dependencies import (
    CollectionArrDep,
    CollectionArtDep,
    CollectionBulkDep,
    CollectionDiscoveryDep,
    CollectionEditorDep,
    CollectionGroupsDep,
    CollectionPresetsDep,
    CollectionReaderDep,
    CollectionRulesDep,
    CollectionSetsDep,
    CollectionThemesDep,
    require_media_server,
)
lazy from ..domain import MATCH_THRESHOLD_DEFAULT, MATCH_THRESHOLD_MAX, FilterField
lazy from ..schemas.art import ArtMatchResponse, ArtSourcesResponse, SaveArtRequest
lazy from ..schemas.collections import (
    ArrTagRead,
    BulkCollectionMonitorUpdate,
    BulkCollectionOperation,
    BulkCollectionOperationResult,
    CollectionAdoption,
    CollectionAdoptionPlan,
    CollectionArrOptions,
    CollectionArtwork,
    CollectionCapabilities,
    CollectionCreate,
    CollectionDefaults,
    CollectionDeleteTarget,
    CollectionDetail,
    CollectionFieldValue,
    CollectionGroupDelete,
    CollectionGroupPolicy,
    CollectionGroupRename,
    CollectionGroupSyncResult,
    CollectionMembersUpdate,
    CollectionMissing,
    CollectionOptions,
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
lazy from .auth import READS_ONLY, require_auth
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
    reader: CollectionReaderDep, media_type: MediaTypeQuery
) -> list[CollectionRead]:
    """Return the collections the last sync listed for the media type."""
    return await reader.listed(media_type)


@router.get("/groups")
async def list_collection_groups(
    groups: CollectionGroupsDep, media_type: MediaTypeQuery
) -> list[str]:
    """Return default and custom collection groups for this media type."""
    return await groups.names(media_type)


@router.get("/defaults")
async def get_collection_defaults(
    reader: CollectionReaderDep,
    media_type: MediaTypeQuery,
    name: Annotated[str | None, Query(max_length=200)] = None,
) -> CollectionDefaults:
    """Resolve inherited values for collection form placeholders."""
    return await reader.inherited_policy(media_type, name)


@router.get("/capabilities")
async def get_collection_capabilities(
    discovery: CollectionDiscoveryDep, media_type: MediaTypeQuery
) -> CollectionCapabilities:
    """Describe the fields, sources, orders and sets the media server supports."""
    return discovery.capabilities(media_type)


@router.get("/presets")
async def list_collection_presets(
    presets: CollectionPresetsDep, media_type: MediaTypeQuery
) -> list[CollectionPresetRead]:
    """Return saved presets, then the built-in ones the server can evaluate."""
    return await presets.available(media_type)


@router.post("/presets")
async def save_collection_preset(
    body: CollectionPresetSave, presets: CollectionPresetsDep
) -> CollectionPresetRead:
    """Keep a collection or set as a preset."""
    return await presets.save(body)


@router.delete("/presets/{preset_id}")
async def delete_collection_preset(
    preset_id: Annotated[int, Path(gt=0)], presets: CollectionPresetsDep
) -> StatusResponse:
    """Forget a saved preset."""
    return await presets.delete(preset_id)


@router.post("/preview", openapi_extra=READS_ONLY)
async def preview_collection(
    body: CollectionPreviewRequest, discovery: CollectionDiscoveryDep
) -> CollectionPreview:
    """Show what criteria select now, before the collection is saved."""
    return await discovery.preview(body)


@router.get("/arr-options")
async def get_collection_arr_options(
    arr: CollectionArrDep, media_type: MediaTypeQuery
) -> CollectionArrOptions:
    """List where Radarr or Sonarr can put requested titles."""
    return await arr.options(media_type)


@router.get("/field-values")
async def list_collection_field_values(
    discovery: CollectionDiscoveryDep,
    media_type: MediaTypeQuery,
    library_id: Annotated[str, Query(min_length=1, max_length=200)],
    field: FilterField,
    query: Annotated[str | None, Query(max_length=200)] = None,
) -> list[CollectionFieldValue]:
    """List a criteria field's values in a library, most common first."""
    return await discovery.field_values(media_type, library_id, field, query)


@router.post("/sets/preview", openapi_extra=READS_ONLY)
async def preview_collection_set(
    body: CollectionSetPreview, sets: CollectionSetsDep
) -> list[CollectionSetEntry]:
    """Preview the collections a set makes in its library."""
    return await sets.preview(body)


@router.patch("/groups")
async def rename_collection_group(
    body: CollectionGroupRename,
    groups: CollectionGroupsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> StatusResponse:
    """Rename a group and all its collection assignments."""
    return await groups.rename(media_type, name, body.name)


@router.delete("/groups")
async def delete_collection_group(
    body: CollectionGroupDelete,
    groups: CollectionGroupsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> BulkCollectionOperationResult:
    """Delete a group, optionally deleting its collections in either application."""
    return await groups.delete(media_type, name, body)


@router.get("/group-policy")
async def get_collection_group_policy(
    groups: CollectionGroupsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> CollectionGroupPolicy:
    """Read a group's nullable overrides for the active media server."""
    return await groups.policy(media_type, name)


@router.put("/group-policy")
async def save_collection_group_policy(
    groups: CollectionGroupsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
    body: CollectionGroupPolicy,
) -> CollectionGroupPolicy:
    """Save defaults inherited by collections assigned to this group."""
    return await groups.save_policy(media_type, name, body)


@router.post("/group-policy/apply")
async def apply_collection_group_policy(
    groups: CollectionGroupsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> BulkCollectionOperationResult:
    """Apply group defaults while preserving each collection's explicit overrides."""
    return await groups.apply_policy(media_type, name)


@router.post("/group-policy/sync")
async def sync_collection_group(
    groups: CollectionGroupsDep,
    media_type: MediaTypeQuery,
    name: Annotated[str, Query(min_length=1, max_length=200)],
) -> CollectionGroupSyncResult:
    """Run the group's collection set, then sync its collections' criteria."""
    return await groups.sync(media_type, name)


@router.get("/tags/radarr")
async def list_radarr_tags(arr: CollectionArrDep) -> list[ArrTagRead]:
    """Return available Radarr tags when Radarr is configured."""
    return await arr.radarr_tags()


@router.get("/tags/sonarr")
async def list_sonarr_tags(arr: CollectionArrDep) -> list[ArrTagRead]:
    """Return available Sonarr tags when Sonarr is configured."""
    return await arr.sonarr_tags()


@router.post("/bulk-operation")
async def bulk_operate_collections(
    bulk: CollectionBulkDep,
    body: BulkCollectionOperation,
) -> BulkCollectionOperationResult:
    """Run one operation independently for every selected collection."""
    return await bulk.run(body)


@router.get("/{collection_id}")
async def get_collection(
    collection_id: CollectionIdPath,
    reader: CollectionReaderDep,
    media_type: MediaTypeQuery,
) -> CollectionDetail:
    """Return one collection with its members and catalog themes."""
    return await reader.get(collection_id, media_type)


@router.get("/{collection_id}/sources")
async def get_collection_sources(
    collection_id: CollectionIdPath,
    reader: CollectionReaderDep,
    media_type: MediaTypeQuery,
) -> CollectionThemeSources:
    """Return the matched catalog's collection theme candidates."""
    detail = await reader.get(collection_id, media_type)
    return CollectionThemeSources(
        youtube_id_overturedb=detail.youtube_id_overturedb,
        youtube_id_themerrdb=detail.youtube_id_themerrdb,
    )


@router.get("/{collection_id}/missing")
async def get_collection_missing(
    collection_id: CollectionIdPath,
    arr: CollectionArrDep,
    media_type: MediaTypeQuery,
) -> CollectionMissing:
    """List titles the collection's lists hold that the library lacks."""
    return await arr.missing(collection_id, media_type)


@router.post("/{collection_id}/missing/request")
async def request_collection_missing(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    body: CollectionRequest,
    arr: CollectionArrDep,
) -> CollectionRequestResult:
    """Ask Radarr or Sonarr for the collection's missing titles."""
    return await arr.request_missing(collection_id, media_type, body)


@router.get("/{collection_id}/theme")
async def get_collection_theme(
    collection_id: CollectionIdPath,
    themes: CollectionThemesDep,
    media_type: MediaTypeQuery,
) -> CollectionThemeStatusResponse:
    """Return the current theme status for a collection."""
    return await themes.status(collection_id, media_type)


@router.put("/{collection_id}/theme")
async def set_collection_theme(
    collection_id: CollectionIdPath,
    body: SetCollectionThemeRequest,
    themes: CollectionThemesDep,
) -> EnqueuedJobResponse:
    """Queue a YouTube track to become the theme of a collection."""
    return await themes.queue(collection_id, body)


@router.delete("/{collection_id}/theme")
async def delete_collection_theme(
    collection_id: CollectionIdPath,
    themes: CollectionThemesDep,
    media_type: MediaTypeQuery,
) -> DeleteCollectionThemeResponse:
    """Remove the theme from a collection and clear its stored record."""
    return await themes.delete(collection_id, media_type)


@router.patch("/{collection_id}/monitored")
async def set_collection_monitored(
    collection_id: CollectionIdPath,
    body: MonitorUpdate,
    editor: CollectionEditorDep,
    media_type: MediaTypeQuery,
) -> MonitoredResponse:
    """Set whether a collection is monitored."""
    return await editor.set_monitored(collection_id, media_type, body.monitored)


@router.patch("/bulk-monitored")
async def bulk_set_collection_monitored(
    body: BulkCollectionMonitorUpdate, editor: CollectionEditorDep
) -> BulkMonitorResponse:
    """Set the monitored flag for multiple collections at once."""
    return await editor.bulk_set_monitored(
        body.collection_ids, body.media_type, body.monitored
    )


@router.get("/{collection_id}/image/{art_type}", response_class=Response)
async def proxy_collection_image(
    collection_id: CollectionIdPath,
    art_type: ArtTypePath,
    reader: CollectionReaderDep,
    size: ImageSizeQuery = None,
) -> Response:
    """Proxy a collection's poster or background from the media server."""
    return await reader.image(collection_id, art_type, size)


@router.post("")
async def create_collection(
    body: CollectionCreate, editor: CollectionEditorDep, to_server: ToServerQuery = True
) -> CollectionDetail:
    """Create a collection in a server library, or only in Overture."""
    return await editor.create(body, sync=to_server)


@router.put("/{collection_id}")
async def update_collection(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    body: CollectionOptions,
    editor: CollectionEditorDep,
    to_server: ToServerQuery = True,
) -> CollectionDetail:
    """Update collection metadata and display options."""
    return await editor.update(collection_id, media_type, body, sync=to_server)


@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    editor: CollectionEditorDep,
    target: CollectionDeleteTarget = "both",
) -> StatusResponse:
    """Delete the collection while preserving its media."""
    return await editor.delete(collection_id, media_type, target=target)


@router.put("/{collection_id}/members")
async def set_collection_members(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    body: CollectionMembersUpdate,
    editor: CollectionEditorDep,
    to_server: ToServerQuery = True,
) -> CollectionDetail:
    """Replace collection membership and order."""
    return await editor.set_members(collection_id, media_type, body, sync=to_server)


@router.put("/{collection_id}/rule")
async def save_collection_rule(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    body: CollectionRuleWrite,
    editor: CollectionEditorDep,
) -> CollectionRuleRead:
    """Save a collection's criteria and inheritance overrides."""
    return await editor.save_rule(collection_id, media_type, body)


@router.get("/{collection_id}/adopt")
async def plan_collection_adoption(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    editor: CollectionEditorDep,
) -> CollectionAdoptionPlan:
    """Show the rule adopting a collection would save, changing nothing."""
    return await editor.adoption_plan(collection_id, media_type)


@router.post("/{collection_id}/adopt")
async def adopt_collection(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    body: CollectionAdoption,
    editor: CollectionEditorDep,
) -> CollectionDetail:
    """Let Overture manage a collection made outside it, keeping what it holds."""
    return await editor.adopt(collection_id, media_type, body)


@router.post("/{collection_id}/orphan")
async def orphan_collection(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    editor: CollectionEditorDep,
) -> CollectionDetail:
    """Stop managing a collection; the server keeps it, listed as unmanaged."""
    return await editor.orphan(collection_id, media_type)


@router.post("/{collection_id}/sync")
async def sync_collection(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    rules: CollectionRulesDep,
) -> CollectionSyncResponse:
    """Make the media server match the collection saved in Overture."""
    return await rules.sync(collection_id, media_type)


@router.delete("/{collection_id}/art")
async def clear_all_collection_art(
    collection_id: CollectionIdPath, media_type: MediaTypeQuery, art: CollectionArtDep
) -> CollectionArtwork:
    """Forget all selected collection artwork, preserving the server copies."""
    return await art.clear(collection_id, media_type, None)


@router.delete("/{collection_id}/art/{art_type}")
async def clear_collection_art(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    art_type: ArtTypePath,
    art: CollectionArtDep,
) -> CollectionArtwork:
    """Forget one selected collection artwork slot."""
    return await art.clear(collection_id, media_type, art_type)


@router.get("/{collection_id}/art/{art_type}/sources")
async def get_collection_art_sources(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    art_type: ArtTypePath,
    art: CollectionArtDep,
) -> ArtSourcesResponse:
    """Browse shared collection artwork sources."""
    return await art.sources(collection_id, media_type, art_type)


@router.put("/{collection_id}/art/{art_type}")
async def save_collection_art(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    art_type: ArtTypePath,
    body: SaveArtRequest,
    art: CollectionArtDep,
) -> StatusResponse:
    """Validate and upload artwork to a collection."""
    return await art.save(collection_id, media_type, art_type, body)


@router.post("/{collection_id}/art/{art_type}/match")
async def match_collection_art(
    collection_id: CollectionIdPath,
    media_type: MediaTypeQuery,
    art_type: ArtTypePath,
    art: CollectionArtDep,
    threshold: Annotated[
        int, Query(ge=0, le=MATCH_THRESHOLD_MAX)
    ] = MATCH_THRESHOLD_DEFAULT,
) -> ArtMatchResponse:
    """Rank collection art using the shared perceptual hash matcher."""
    return await art.match(collection_id, media_type, art_type, threshold)
