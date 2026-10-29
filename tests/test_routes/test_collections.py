"""Tests for collection router endpoints and service delegation."""

lazy from unittest.mock import AsyncMock, MagicMock

lazy from starlette.responses import Response

lazy from overture.domain import (
    ArtType,
    AssetStatus,
    CollectionOrder,
    FilterField,
    MediaType,
    ServerType,
    SetDimension,
)
lazy from overture.routers import collections as collections_router
lazy from overture.schemas.art import (
    ArtMatchResponse,
    ArtSourcesResponse,
    SaveArtRequest,
)
lazy from overture.schemas.collections import (
    ArrTagRead,
    BulkCollectionMonitorUpdate,
    BulkCollectionOperation,
    BulkCollectionOperationResult,
    CollectionArtwork,
    CollectionCapabilities,
    CollectionCreate,
    CollectionDetail,
    CollectionGenerator,
    CollectionGroupDelete,
    CollectionGroupPolicy,
    CollectionGroupRename,
    CollectionGroupSyncResult,
    CollectionMembersUpdate,
    CollectionOptions,
    CollectionPolicyBase,
    CollectionRead,
    CollectionRuleRead,
    CollectionRuleWrite,
    CollectionSetPreview,
    CollectionSyncResponse,
    CollectionThemeStatusResponse,
    DeleteCollectionThemeResponse,
    FilterGroup,
    SetCollectionThemeRequest,
    SourceCondition,
    TmdbCollectionSource,
)
lazy from overture.schemas.common import (
    BulkMonitorResponse,
    EnqueuedJobResponse,
    MonitoredResponse,
    MonitorUpdate,
    Status,
    StatusResponse,
)


async def test_collection_routes_delegate_to_service() -> None:
    read_item = CollectionRead(
        id=1,
        library_id="lib1",
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        title="Star Wars",
    )
    detail_item = CollectionDetail(
        id=1,
        library_id="lib1",
        media_type=MediaType.MOVIE,
        server_type=ServerType.PLEX,
        title="Star Wars",
        members=[],
        youtube_id_overturedb="yt1",
        youtube_id_themerrdb="yt2",
    )
    artwork = CollectionArtwork(
        poster_status=AssetStatus.COMPLETE,
        background_status=AssetStatus.COMPLETE,
        art_status=AssetStatus.COMPLETE,
    )

    service = MagicMock()
    service.list_collections = AsyncMock(return_value=[read_item])
    service.groups = AsyncMock(return_value=["Franchises"])
    service.group_policy = AsyncMock(return_value=CollectionGroupPolicy())
    service.save_group_policy = AsyncMock(return_value=CollectionGroupPolicy())
    service.sync_group = AsyncMock(
        return_value=CollectionGroupSyncResult(created=[2], synced=1)
    )
    capabilities = CollectionCapabilities(
        server_type=ServerType.PLEX,
        smart=True,
        visibility=True,
        orders=[CollectionOrder.CUSTOM],
        smart_orders=[CollectionOrder.TITLE_ASC],
        fields=[],
        sources=[],
        dimensions=[],
        member_labels=True,
        arr=False,
        charts=[],
    )
    service.list_radarr_tags = AsyncMock(return_value=[ArrTagRead(id=1, label="tag1")])
    service.list_sonarr_tags = AsyncMock(return_value=[ArrTagRead(id=2, label="tag2")])
    service.bulk_operation = AsyncMock(
        return_value=BulkCollectionOperationResult(collection_ids=[1], errors={})
    )
    service.get_collection = AsyncMock(return_value=detail_item)
    service.get_collection_theme = AsyncMock(
        return_value=CollectionThemeStatusResponse(has_theme=True)
    )
    service.set_collection_theme = AsyncMock(
        return_value=EnqueuedJobResponse(job_id="job1")
    )
    service.delete_collection_theme = AsyncMock(
        return_value=DeleteCollectionThemeResponse(
            status=Status.OK,
            has_theme=False,
            theme_status=AssetStatus.MISSING,
        )
    )
    service.set_collection_monitored = AsyncMock(
        return_value=MonitoredResponse(monitored=True)
    )
    service.bulk_set_collection_monitored = AsyncMock(
        return_value=BulkMonitorResponse(updated=1)
    )
    service.proxy_collection_image = AsyncMock(return_value=Response(content=b"img"))
    service.create = AsyncMock(return_value=detail_item)
    service.update = AsyncMock(return_value=detail_item)
    service.delete = AsyncMock(return_value=StatusResponse(status=Status.OK))
    service.set_members = AsyncMock(return_value=detail_item)
    service.save_rule = AsyncMock(
        return_value=CollectionRuleRead(
            criteria=FilterGroup(
                conditions=[
                    SourceCondition(source=TmdbCollectionSource(collection_id=10))
                ]
            )
        )
    )
    service.sync_rule = AsyncMock(return_value=CollectionSyncResponse(added=2))

    art_service = MagicMock()
    art_service.clear_collection = AsyncMock(return_value=artwork)
    art_service.get_collection_sources = AsyncMock(
        return_value=ArtSourcesResponse(sources={})
    )
    art_service.save_collection = AsyncMock(
        return_value=StatusResponse(status=Status.OK)
    )
    art_service.match_collection = AsyncMock(return_value=ArtMatchResponse(matches=[]))

    # Collections listing & groups
    assert len(await collections_router.list_collections(service, MediaType.MOVIE)) == 1
    assert await collections_router.list_collection_groups(
        service, MediaType.MOVIE
    ) == ["Franchises"]

    service.inherited_policy = AsyncMock(return_value=CollectionPolicyBase())
    assert (
        await collections_router.get_collection_defaults(
            service, MediaType.MOVIE, "Franchises"
        )
        == CollectionPolicyBase()
    )
    service.rename_group = AsyncMock(return_value=StatusResponse(status=Status.OK))
    await collections_router.rename_collection_group(
        CollectionGroupRename(name="Saga"), service, MediaType.MOVIE, "Franchises"
    )
    service.rename_group.assert_awaited_once_with(MediaType.MOVIE, "Franchises", "Saga")
    service.delete_group = AsyncMock(return_value=BulkCollectionOperationResult())
    removal = CollectionGroupDelete(collections="both")
    await collections_router.delete_collection_group(
        removal, service, MediaType.MOVIE, "Saga"
    )
    service.delete_group.assert_awaited_once_with(MediaType.MOVIE, "Saga", removal)
    service.preview_set = AsyncMock(return_value=[])
    preview = CollectionSetPreview(
        media_type=MediaType.MOVIE,
        generator=CollectionGenerator(
            dimension=SetDimension.DECADE, library_ids=["movies"]
        ),
    )
    assert await collections_router.preview_collection_set(preview, service) == []
    service.preview_set.assert_awaited_once_with(preview)
    service.capabilities = MagicMock(return_value=capabilities)
    assert (
        await collections_router.get_collection_capabilities(service, MediaType.MOVIE)
        == capabilities
    )
    service.presets = AsyncMock(return_value=[])
    assert (
        await collections_router.list_collection_presets(service, MediaType.MOVIE) == []
    )
    service.field_values = AsyncMock(return_value=[])
    assert (
        await collections_router.list_collection_field_values(
            service, MediaType.MOVIE, "movies", FilterField.GENRE
        )
        == []
    )
    service.field_values.assert_awaited_once_with(
        MediaType.MOVIE, "movies", FilterField.GENRE
    )

    # Group policy
    policy = CollectionGroupPolicy(minimum_items=3)
    assert (
        await collections_router.get_collection_group_policy(
            service, MediaType.MOVIE, "Franchises"
        )
        == CollectionGroupPolicy()
    )
    assert (
        await collections_router.save_collection_group_policy(
            service, MediaType.MOVIE, "Franchises", policy
        )
        == CollectionGroupPolicy()
    )
    assert (
        await collections_router.sync_collection_group(
            service, MediaType.MOVIE, "Franchises"
        )
    ).created == [2]

    # Arr tags
    assert len(await collections_router.list_radarr_tags(service)) == 1
    assert len(await collections_router.list_sonarr_tags(service)) == 1

    # Bulk operation
    bulk = BulkCollectionOperation(
        collection_ids=[1],
        media_type=MediaType.MOVIE,
        operation="trigger_sync",
    )
    result = await collections_router.bulk_operate_collections(service, bulk)
    assert result.collection_ids == [1]

    # Get collection & theme sources
    item = await collections_router.get_collection(1, service, MediaType.MOVIE)
    assert item.id == 1
    sources = await collections_router.get_collection_sources(
        1, service, MediaType.MOVIE
    )
    assert sources.youtube_id_overturedb == "yt1"
    assert sources.youtube_id_themerrdb == "yt2"

    # Theme ops
    theme = await collections_router.get_collection_theme(1, service, MediaType.MOVIE)
    assert theme.has_theme is True
    set_theme = SetCollectionThemeRequest(
        youtube_id="dQw4w9WgXcQ", media_type=MediaType.MOVIE
    )
    assert (
        await collections_router.set_collection_theme(1, set_theme, service)
    ).job_id == "job1"
    assert (
        await collections_router.delete_collection_theme(1, service, MediaType.MOVIE)
    ).status == Status.OK

    # Monitored ops
    mon = await collections_router.set_collection_monitored(
        1, MonitorUpdate(monitored=True), service, MediaType.MOVIE
    )
    assert mon.monitored is True
    bulk_mon = BulkCollectionMonitorUpdate(
        collection_ids=[1], media_type=MediaType.MOVIE, monitored=True
    )
    bulk_res = await collections_router.bulk_set_collection_monitored(bulk_mon, service)
    assert bulk_res.updated == 1

    # Proxy image
    img_resp = await collections_router.proxy_collection_image(
        1, ArtType.POSTER, service
    )
    assert img_resp.body == b"img"

    rule_write = CollectionRuleWrite(
        criteria=FilterGroup(
            conditions=[SourceCondition(source=TmdbCollectionSource(collection_id=10))]
        )
    )
    # Create, update, delete
    create = CollectionCreate(
        media_type=MediaType.MOVIE,
        library_id="lib1",
        title="Star Wars",
        rule=rule_write,
    )
    assert (await collections_router.create_collection(create, service)).id == 1
    options = CollectionOptions(title="Star Wars Updated")
    updated = await collections_router.update_collection(
        1, MediaType.MOVIE, options, service
    )
    assert updated.id == 1
    deleted = await collections_router.delete_collection(1, MediaType.MOVIE, service)
    assert deleted.status == Status.OK

    # Members
    members = CollectionMembersUpdate(
        member_ids=[10, 20], order_type=CollectionOrder.RELEASE_ASC
    )
    set_mem = await collections_router.set_collection_members(
        1, MediaType.MOVIE, members, service
    )
    assert set_mem.id == 1

    # Rules
    saved_rule = await collections_router.save_collection_rule(
        1, MediaType.MOVIE, rule_write, service
    )
    assert saved_rule.criteria.source_conditions()[0].source.type == "tmdb_collection"
    sync_res = await collections_router.sync_collection(1, MediaType.MOVIE, service)
    assert sync_res.added == 2

    # Art endpoints
    all_art = await collections_router.clear_all_collection_art(
        1, MediaType.MOVIE, art_service
    )
    assert all_art.poster_status is AssetStatus.COMPLETE
    slot_art = await collections_router.clear_collection_art(
        1, MediaType.MOVIE, ArtType.POSTER, art_service
    )
    assert slot_art.poster_status is AssetStatus.COMPLETE
    art_sources = await collections_router.get_collection_art_sources(
        1, MediaType.MOVIE, ArtType.POSTER, art_service
    )
    assert art_sources.current_url is None
    save_art = SaveArtRequest(url="https://example.com/poster.jpg")
    saved_art = await collections_router.save_collection_art(
        1, MediaType.MOVIE, ArtType.POSTER, save_art, art_service
    )
    assert saved_art.status == Status.OK
    matched = await collections_router.match_collection_art(
        1, MediaType.MOVIE, ArtType.POSTER, art_service
    )
    assert len(matched.matches) == 0
