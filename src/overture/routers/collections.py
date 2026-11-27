"""Collections router - list collections and manage collection themes."""

lazy from typing import Annotated

lazy from fastapi import Path, Query
lazy from fastapi.responses import Response

lazy from ..dependencies import (
    CollectionAdoptionDep,
    CollectionArrDep,
    CollectionArtDep,
    CollectionBulkDep,
    CollectionDiscoveryDep,
    CollectionEditorDep,
    CollectionGroupsDep,
    CollectionPresetsDep,
    CollectionReaderDep,
    CollectionSetsDep,
    CollectionThemesDep,
    PresetUsesDep,
)
lazy from ..domain import (
    MATCH_THRESHOLD_DEFAULT,
    MATCH_THRESHOLD_MAX,
    ArtGeneration,
    ArtStyle,
    FilterField,
)
lazy from ..schemas.art import (
    ArtMatchResponse,
    ArtSourcesResponse,
    SaveCollectionArtRequest,
)
lazy from ..schemas.assets import AssetRead
lazy from ..schemas.collection_presets import (
    CollectionPresetFile,
    PresetExport,
    PresetExportRequest,
    PresetGallery,
    PresetListing,
    PresetUseCreate,
    PresetUseRead,
    PresetUseReview,
    PresetUses,
)
lazy from ..schemas.collections import (
    COLLECTION_LIBRARIES_MAX,
    ArrTagRead,
    BulkCollectionMonitorUpdate,
    BulkCollectionOperation,
    BulkCollectionOperationResult,
    CollectionAdoption,
    CollectionAdoptionPlan,
    CollectionArrOptions,
    CollectionCapabilities,
    CollectionCreate,
    CollectionDefaults,
    CollectionDeleteTarget,
    CollectionDetail,
    CollectionFieldValue,
    CollectionGroupDelete,
    CollectionGroupPolicy,
    CollectionGroupRead,
    CollectionGroupRename,
    CollectionKindRequest,
    CollectionMembersUpdate,
    CollectionMissing,
    CollectionOptions,
    CollectionPreview,
    CollectionPreviewRequest,
    CollectionRead,
    CollectionRequest,
    CollectionRequestResult,
    CollectionRuleRead,
    CollectionRuleWrite,
    CollectionSetEntry,
    CollectionSetPreview,
    DeleteCollectionThemeResponse,
    KindRecommendation,
    LibraryId,
    MdblistListRead,
    SetCollectionThemeRequest,
    SetCollectionThemeResponse,
)
lazy from ..schemas.common import (
    BulkMonitorResponse,
    MonitoredResponse,
    MonitorUpdate,
    StatusResponse,
)
lazy from ..schemas.records import DatabaseRecord
lazy from ..schemas.removal import AssetRemoval
lazy from .auth import READS_ONLY, media_server_router
lazy from .parameters import (
    ArtTypePath,
    CollectionIdPath,
    ImageCacheKeyQuery,
    ImageSizeQuery,
    ImageVersionQuery,
    MediaTypeQuery,
)
lazy from .responses import NOT_CONFIGURED, UPLOAD_GONE, errors

router = media_server_router(prefix="/collections", tags=["collections"])
#: Groups are a resource of their own: under /collections a group's name and a
#: collection's ID would share a path segment.
groups_router = media_server_router(prefix="/collection-groups", tags=["collections"])
_NO_GROUP = errors({404: "No collection group has that name"})
_PRESET_USE = errors(
    {
        404: "No such collection, group or preset item",
        502: "OvertureDB's presets could not be read",
    }
)
#: A group's name in a path; a name may hold slashes.
type GroupPath = Annotated[str, Path(min_length=1, max_length=200)]


@router.get("")
async def list_collections(reader: CollectionReaderDep) -> list[CollectionRead]:
    """Return the collections the last sync listed."""
    return await reader.listed()


@groups_router.get("")
async def list_collection_groups(
    groups: CollectionGroupsDep,
) -> list[CollectionGroupRead]:
    """Return the collection groups, each with its set."""
    return await groups.list()


@router.get("/defaults")
async def get_collection_defaults(
    reader: CollectionReaderDep,
    name: Annotated[str | None, Query(max_length=200)] = None,
) -> CollectionDefaults:
    """Resolve inherited values for collection form placeholders."""
    return await reader.inherited_policy(name)


@router.get("/capabilities")
async def get_collection_capabilities(
    discovery: CollectionDiscoveryDep,
    media_type: MediaTypeQuery,
    library_ids: Annotated[
        list[LibraryId] | None,
        Query(
            max_length=COLLECTION_LIBRARIES_MAX,
            description="The collection's libraries; every server without them.",
        ),
    ] = None,
) -> CollectionCapabilities:
    """Describe the fields, sources, orders and sets the servers support."""
    return discovery.capabilities(media_type, library_ids)


@router.post("/recommend-kind", openapi_extra=READS_ONLY)
async def recommend_collection_kind(
    body: CollectionKindRequest, discovery: CollectionDiscoveryDep
) -> KindRecommendation | None:
    """Recommend a smart or regular collection for a rule, changing nothing."""
    return await discovery.recommend(body)


@router.post("/preview", openapi_extra=READS_ONLY)
async def preview_collection(
    body: CollectionPreviewRequest, discovery: CollectionDiscoveryDep
) -> CollectionPreview:
    """Show what criteria select now, before the collection is saved."""
    return await discovery.preview(body)


@router.get("/arr-options", responses=NOT_CONFIGURED)
async def get_collection_arr_options(
    arr: CollectionArrDep, media_type: MediaTypeQuery
) -> CollectionArrOptions:
    """List where Radarr or Sonarr can put requested titles."""
    return await arr.options(media_type)


@router.get("/field-values")
async def list_collection_field_values(
    discovery: CollectionDiscoveryDep,
    media_type: MediaTypeQuery,
    field: FilterField,
    library_id: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    query: Annotated[str | None, Query(max_length=200)] = None,
) -> list[CollectionFieldValue]:
    """List a criteria field's values in a library, or in every library of the
    media type, most common first."""
    return await discovery.field_values(media_type, library_id, field, query)


@router.get("/mdblist-lists", responses=NOT_CONFIGURED)
async def search_mdblist_lists(
    discovery: CollectionDiscoveryDep,
    query: Annotated[str, Query(min_length=1, max_length=200)],
) -> list[MdblistListRead]:
    """Search MDBList's public lists, for an MDBList source condition."""
    return await discovery.mdblist_lists(query)


@router.post("/sets/preview", openapi_extra=READS_ONLY)
async def preview_collection_set(
    body: CollectionSetPreview, sets: CollectionSetsDep
) -> list[CollectionSetEntry]:
    """Preview the collections a set makes in its library."""
    return await sets.preview(body)


@groups_router.patch("/{name:path}", responses=_NO_GROUP)
async def rename_collection_group(
    body: CollectionGroupRename, groups: CollectionGroupsDep, name: GroupPath
) -> StatusResponse:
    """Rename a group and all its collection assignments."""
    return await groups.rename(name, body.name)


@groups_router.delete("/{name:path}", responses=_NO_GROUP)
async def delete_collection_group(
    body: CollectionGroupDelete, groups: CollectionGroupsDep, name: GroupPath
) -> BulkCollectionOperationResult:
    """Delete a group, optionally deleting its collections in either application."""
    return await groups.delete(name, body)


@groups_router.get("/{name:path}")
async def get_collection_group_policy(
    groups: CollectionGroupsDep, name: GroupPath
) -> CollectionGroupPolicy:
    """Read a group's nullable overrides for the active media server."""
    return await groups.policy(name)


@groups_router.put("/{name:path}")
async def save_collection_group_policy(
    groups: CollectionGroupsDep,
    name: GroupPath,
    body: CollectionGroupPolicy,
    new_set: Annotated[
        bool, Query(description="Create a set; refuse a group that already is one")
    ] = False,
) -> CollectionGroupPolicy:
    """Save defaults inherited by collections assigned to this group."""
    return await groups.save_policy(name, body, new_set=new_set)


@router.get("/tags/radarr", responses=NOT_CONFIGURED)
async def list_radarr_tags(arr: CollectionArrDep) -> list[ArrTagRead]:
    """Return available Radarr tags when Radarr is configured."""
    return await arr.radarr_tags()


@router.get("/tags/sonarr", responses=NOT_CONFIGURED)
async def list_sonarr_tags(arr: CollectionArrDep) -> list[ArrTagRead]:
    """Return available Sonarr tags when Sonarr is configured."""
    return await arr.sonarr_tags()


@router.get("/presets")
async def list_collection_presets(presets: CollectionPresetsDep) -> PresetGallery:
    """Return the presets OvertureDB publishes, and what each needs here."""
    return await presets.gallery()


@router.post("/presets/file", openapi_extra=READS_ONLY)
async def read_collection_preset_file(
    presets: CollectionPresetsDep, body: CollectionPresetFile
) -> PresetListing:
    """Return a collections file, checked, as the gallery lists a preset."""
    return presets.read_file(body)


@router.post("/presets/export", openapi_extra=READS_ONLY)
async def export_collection_preset(
    presets: CollectionPresetsDep, body: PresetExportRequest
) -> PresetExport:
    """Return collections and groups as a file any install can add."""
    return await presets.export(body)


@router.get("/presets/uses")
async def list_preset_uses(uses: PresetUsesDep) -> PresetUses:
    """Return the collections and sets saved from presets, and OvertureDB's changes."""
    return await uses.list()


@router.post("/presets/uses", responses=_PRESET_USE)
async def record_preset_use(
    uses: PresetUsesDep, body: PresetUseCreate
) -> PresetUseRead:
    """Keep track of the preset item a collection or set was just saved from."""
    return await uses.record(body)


@router.post("/presets/uses/review", responses=_PRESET_USE)
async def review_preset_use(
    uses: PresetUsesDep, body: PresetUseReview
) -> PresetUseRead | None:
    """Take OvertureDB's changes to a preset item, or keep the saved one.

    Returns null once OvertureDB no longer publishes the item, which then
    stops being tracked.
    """
    return await uses.review(body)


@router.post("/bulk-operation")
async def bulk_operate_collections(
    bulk: CollectionBulkDep,
    body: BulkCollectionOperation,
) -> BulkCollectionOperationResult:
    """Run one operation independently for every selected collection."""
    return await bulk.run(body)


@router.get("/{collection_id}/record")
async def get_collection_record(
    collection_id: CollectionIdPath,
    reader: CollectionReaderDep,
) -> DatabaseRecord:
    """Return the collection's stored rows and what the API derives from them."""
    return await reader.record(collection_id)


@router.get("/{collection_id}")
async def get_collection(
    collection_id: CollectionIdPath,
    reader: CollectionReaderDep,
) -> CollectionDetail:
    """Return one collection with its members and catalog themes."""
    return await reader.get(collection_id)


@router.get("/{collection_id}/missing")
async def get_collection_missing(
    collection_id: CollectionIdPath,
    arr: CollectionArrDep,
) -> CollectionMissing:
    """List titles the collection's lists hold that the library lacks."""
    return await arr.missing(collection_id)


@router.post("/{collection_id}/missing/request")
async def request_collection_missing(
    collection_id: CollectionIdPath,
    body: CollectionRequest,
    arr: CollectionArrDep,
) -> CollectionRequestResult:
    """Ask Radarr or Sonarr for the collection's missing titles."""
    return await arr.request_missing(collection_id, body)


@router.get("/{collection_id}/theme")
async def get_collection_theme(
    collection_id: CollectionIdPath,
    themes: CollectionThemesDep,
) -> AssetRead:
    """Return the current theme status for a collection."""
    return await themes.status(collection_id)


@router.put("/{collection_id}/theme")
async def set_collection_theme(
    collection_id: CollectionIdPath,
    body: SetCollectionThemeRequest,
    themes: CollectionThemesDep,
) -> SetCollectionThemeResponse:
    """Queue a YouTube track to become the theme of a collection."""
    return await themes.queue(collection_id, body)


@router.delete("/{collection_id}/theme")
async def remove_collection_theme(
    collection_id: CollectionIdPath,
    removal: Annotated[AssetRemoval, Query()],
    themes: CollectionThemesDep,
) -> DeleteCollectionThemeResponse:
    """Forget a collection's theme, delete the server's copy or its file."""
    return await themes.remove(collection_id, removal)


@router.patch("/{collection_id}/monitored")
async def set_collection_monitored(
    collection_id: CollectionIdPath,
    body: MonitorUpdate,
    editor: CollectionEditorDep,
) -> MonitoredResponse:
    """Set whether a collection is monitored."""
    return await editor.set_monitored(collection_id, body.monitored)


@router.patch("/bulk-monitored")
async def bulk_set_collection_monitored(
    body: BulkCollectionMonitorUpdate, editor: CollectionEditorDep
) -> BulkMonitorResponse:
    """Set the monitored flag for multiple collections at once."""
    return await editor.bulk_set_monitored(body.collection_ids, body.monitored)


@router.get("/{collection_id}/local-image/{art_type}", response_class=Response)
async def serve_collection_local_image(
    collection_id: CollectionIdPath,
    art_type: ArtTypePath,
    art: CollectionArtDep,
    size: ImageSizeQuery = None,
    version: ImageVersionQuery = None,
) -> Response:
    """Serve the image Overture last uploaded to a collection, or its thumbnail."""
    return await art.local_image(collection_id, art_type, size, version)


@router.get("/{collection_id}/image/{art_type}", response_class=Response)
async def proxy_collection_image(
    collection_id: CollectionIdPath,
    art_type: ArtTypePath,
    reader: CollectionReaderDep,
    size: ImageSizeQuery = None,
    _cache_key: ImageCacheKeyQuery = None,
) -> Response:
    """Proxy a collection's poster or background from the media server."""
    return await reader.image(collection_id, art_type, size)


@router.post("")
async def create_collection(
    body: CollectionCreate, editor: CollectionEditorDep
) -> CollectionDetail:
    """Save a new collection; a sync puts it on the media server."""
    return await editor.create(body)


@router.put("/{collection_id}")
async def update_collection(
    collection_id: CollectionIdPath,
    body: CollectionOptions,
    editor: CollectionEditorDep,
) -> CollectionDetail:
    """Save collection metadata and display options; a sync sends them."""
    return await editor.update(collection_id, body)


@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: CollectionIdPath,
    editor: CollectionEditorDep,
    target: CollectionDeleteTarget = "both",
) -> StatusResponse:
    """Delete the collection while preserving its media."""
    return await editor.delete(collection_id, target=target)


@router.put("/{collection_id}/members")
async def set_collection_members(
    collection_id: CollectionIdPath,
    body: CollectionMembersUpdate,
    editor: CollectionEditorDep,
) -> CollectionDetail:
    """Save collection membership and order; a sync sends them."""
    return await editor.set_members(collection_id, body)


@router.put("/{collection_id}/rule")
async def save_collection_rule(
    collection_id: CollectionIdPath,
    body: CollectionRuleWrite,
    editor: CollectionEditorDep,
) -> CollectionRuleRead:
    """Save a collection's criteria and inheritance overrides."""
    return await editor.save_rule(collection_id, body)


@router.get("/{collection_id}/adopt")
async def plan_collection_adoption(
    collection_id: CollectionIdPath,
    adoption: CollectionAdoptionDep,
) -> CollectionAdoptionPlan:
    """Show the rule adopting a collection would save, changing nothing."""
    return await adoption.adoption_plan(collection_id)


@router.post("/{collection_id}/adopt")
async def adopt_collection(
    collection_id: CollectionIdPath,
    body: CollectionAdoption,
    adoption: CollectionAdoptionDep,
) -> CollectionDetail:
    """Let Overture manage a collection made outside it, keeping what it holds."""
    return await adoption.adopt(collection_id, body)


@router.post("/{collection_id}/orphan")
async def orphan_collection(
    collection_id: CollectionIdPath,
    adoption: CollectionAdoptionDep,
) -> CollectionDetail:
    """Stop managing a collection; the server keeps it, listed as unmanaged."""
    return await adoption.orphan(collection_id)


@router.delete("/{collection_id}/art")
async def remove_all_collection_art(
    collection_id: CollectionIdPath,
    removal: Annotated[AssetRemoval, Query()],
    art: CollectionArtDep,
) -> StatusResponse:
    """Forget both of a collection's art slots, or delete the server's images."""
    return await art.remove(collection_id, None, removal)


@router.delete("/{collection_id}/art/{art_type}")
async def remove_collection_art(
    collection_id: CollectionIdPath,
    art_type: ArtTypePath,
    removal: Annotated[AssetRemoval, Query()],
    art: CollectionArtDep,
) -> StatusResponse:
    """Forget a collection's art slot, or delete the server's image."""
    return await art.remove(collection_id, art_type, removal)


@router.get("/{collection_id}/art/{art_type}/sources")
async def get_collection_art_sources(
    collection_id: CollectionIdPath,
    art_type: ArtTypePath,
    art: CollectionArtDep,
) -> ArtSourcesResponse:
    """Browse shared collection artwork sources."""
    return await art.sources(collection_id, art_type)


@router.get(
    "/{collection_id}/art/{art_type}/generated/{style}",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}},
)
async def get_generated_collection_art(
    collection_id: CollectionIdPath,
    art_type: ArtTypePath,
    style: ArtStyle,
    art: CollectionArtDep,
    title_only: bool = False,
) -> Response:
    """Return the art Overture would generate for the collection in *style*."""
    return Response(
        await art.preview(
            collection_id, art_type, ArtGeneration(style, title_only=title_only)
        ),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.put("/{collection_id}/art/{art_type}", responses=UPLOAD_GONE)
async def save_collection_art(
    collection_id: CollectionIdPath,
    art_type: ArtTypePath,
    body: SaveCollectionArtRequest,
    art: CollectionArtDep,
) -> StatusResponse:
    """Validate and upload artwork to a collection."""
    return await art.save(collection_id, art_type, body)


@router.post("/{collection_id}/art/{art_type}/match")
async def match_collection_art(
    collection_id: CollectionIdPath,
    art_type: ArtTypePath,
    art: CollectionArtDep,
    threshold: Annotated[
        int, Query(ge=0, le=MATCH_THRESHOLD_MAX)
    ] = MATCH_THRESHOLD_DEFAULT,
) -> ArtMatchResponse:
    """Rank collection art using the shared perceptual hash matcher."""
    return await art.match(collection_id, art_type, threshold)
