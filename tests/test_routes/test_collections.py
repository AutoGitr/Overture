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
    CollectionCapabilities,
    CollectionCreate,
    CollectionDefaults,
    CollectionDetail,
    CollectionGenerator,
    CollectionGroupDelete,
    CollectionGroupPolicy,
    CollectionGroupRename,
    CollectionLibraryCriteria,
    CollectionMembersUpdate,
    CollectionOptions,
    CollectionRead,
    CollectionRuleRead,
    CollectionSetPreview,
    CollectionThemeStatusResponse,
    DeleteCollectionThemeResponse,
    FilterGroup,
    SetCollectionThemeRequest,
    SetCollectionThemeResponse,
    SourceCondition,
    TmdbCollectionSource,
)
lazy from overture.schemas.common import (
    BulkMonitorResponse,
    MonitoredResponse,
    MonitorUpdate,
    Status,
    StatusResponse,
)
lazy from overture.schemas.removal import AssetRemoval
lazy from tests.collection_helpers import library_rule


async def test_collection_routes_delegate_to_service() -> None:
    read_item = CollectionRead(
        id=1,
        library_ids=["lib1"],
        media_types=[MediaType.MOVIE],
        title="Star Wars",
    )
    detail_item = CollectionDetail(
        id=1,
        library_ids=["lib1"],
        media_types=[MediaType.MOVIE],
        title="Star Wars",
        member_ids=[],
        youtube_id_overturedb="yt1",
        youtube_id_themerrdb="yt2",
    )
    service = MagicMock()
    service.reader.listed = AsyncMock(return_value=[read_item])
    service.groups.names = AsyncMock(return_value=["Franchises"])
    service.groups.policy = AsyncMock(return_value=CollectionGroupPolicy())
    service.groups.save_policy = AsyncMock(return_value=CollectionGroupPolicy())
    capabilities = CollectionCapabilities(
        server_type=ServerType.PLEX,
        spans_libraries=False,
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
    service.arr.radarr_tags = AsyncMock(return_value=[ArrTagRead(id=1, label="tag1")])
    service.arr.sonarr_tags = AsyncMock(return_value=[ArrTagRead(id=2, label="tag2")])
    service.bulk.run = AsyncMock(
        return_value=BulkCollectionOperationResult(collection_ids=[1], errors={})
    )
    service.reader.get = AsyncMock(return_value=detail_item)
    service.themes.status = AsyncMock(
        return_value=CollectionThemeStatusResponse(has_theme=True)
    )
    service.themes.queue = AsyncMock(
        return_value=SetCollectionThemeResponse(
            job_id="job1", theme_status=AssetStatus.PARTIAL
        )
    )
    service.themes.remove = AsyncMock(
        return_value=DeleteCollectionThemeResponse(
            status=Status.OK,
            has_theme=False,
            theme_status=AssetStatus.MISSING,
        )
    )
    service.editor.set_monitored = AsyncMock(
        return_value=MonitoredResponse(monitored=True)
    )
    service.editor.bulk_set_monitored = AsyncMock(
        return_value=BulkMonitorResponse(updated=1)
    )
    service.reader.image = AsyncMock(return_value=Response(content=b"img"))
    service.editor.create = AsyncMock(return_value=detail_item)
    service.editor.update = AsyncMock(return_value=detail_item)
    service.editor.delete = AsyncMock(return_value=StatusResponse(status=Status.OK))
    service.editor.set_members = AsyncMock(return_value=detail_item)
    service.editor.save_rule = AsyncMock(
        return_value=CollectionRuleRead(
            libraries=[
                CollectionLibraryCriteria(
                    library_id="lib1",
                    criteria=FilterGroup(
                        conditions=[
                            SourceCondition(
                                source=TmdbCollectionSource(collection_id=10)
                            )
                        ]
                    ),
                )
            ]
        )
    )

    art_service = MagicMock()
    art_service.remove = AsyncMock(return_value=StatusResponse(status=Status.OK))
    art_service.sources = AsyncMock(return_value=ArtSourcesResponse(sources={}))
    art_service.save = AsyncMock(return_value=StatusResponse(status=Status.OK))
    art_service.match = AsyncMock(return_value=ArtMatchResponse(matches=[]))

    # Collections listing & groups
    assert len(await collections_router.list_collections(service.reader)) == 1
    assert await collections_router.list_collection_groups(service.groups) == [
        "Franchises"
    ]

    defaults = CollectionDefaults(minimum_items=2)
    service.reader.inherited_policy = AsyncMock(return_value=defaults)
    assert (
        await collections_router.get_collection_defaults(service.reader, "Franchises")
        == defaults
    )
    service.groups.rename = AsyncMock(return_value=StatusResponse(status=Status.OK))
    await collections_router.rename_collection_group(
        CollectionGroupRename(name="Saga"),
        service.groups,
        "Franchises",
    )
    service.groups.rename.assert_awaited_once_with("Franchises", "Saga")
    service.groups.delete = AsyncMock(return_value=BulkCollectionOperationResult())
    removal = CollectionGroupDelete(collections="both")
    await collections_router.delete_collection_group(removal, service.groups, "Saga")
    service.groups.delete.assert_awaited_once_with("Saga", removal)
    service.sets.preview = AsyncMock(return_value=[])
    preview = CollectionSetPreview(
        generator=CollectionGenerator(
            dimension=SetDimension.DECADE, library_ids=["movies"]
        ),
    )
    assert await collections_router.preview_collection_set(preview, service.sets) == []
    service.sets.preview.assert_awaited_once_with(preview)
    service.discovery.capabilities = MagicMock(return_value=capabilities)
    assert (
        await collections_router.get_collection_capabilities(
            service.discovery, MediaType.MOVIE
        )
        == capabilities
    )
    service.discovery.field_values = AsyncMock(return_value=[])
    assert (
        await collections_router.list_collection_field_values(
            service.discovery, MediaType.MOVIE, "movies", FilterField.GENRE
        )
        == []
    )
    service.discovery.field_values.assert_awaited_once_with(
        MediaType.MOVIE, "movies", FilterField.GENRE, None
    )

    # Group policy
    policy = CollectionGroupPolicy(minimum_items=3)
    assert (
        await collections_router.get_collection_group_policy(
            service.groups, "Franchises"
        )
        == CollectionGroupPolicy()
    )
    assert (
        await collections_router.save_collection_group_policy(
            service.groups, "Franchises", policy
        )
        == CollectionGroupPolicy()
    )

    # Arr tags
    assert len(await collections_router.list_radarr_tags(service.arr)) == 1
    assert len(await collections_router.list_sonarr_tags(service.arr)) == 1

    # Bulk operation
    bulk = BulkCollectionOperation(
        collection_ids=[1],
        operation="remove_artwork",
    )
    result = await collections_router.bulk_operate_collections(service.bulk, bulk)
    assert result.collection_ids == [1]

    # The collection carries its catalog theme candidates
    item = await collections_router.get_collection(1, service.reader)
    assert item.id == 1
    assert item.youtube_id_overturedb == "yt1"
    assert item.youtube_id_themerrdb == "yt2"

    # Theme ops
    theme = await collections_router.get_collection_theme(1, service.themes)
    assert theme.has_theme is True
    set_theme = SetCollectionThemeRequest(youtube_id="dQw4w9WgXcQ")
    assert (
        await collections_router.set_collection_theme(1, set_theme, service.themes)
    ).job_id == "job1"
    assert (
        await collections_router.remove_collection_theme(
            1, AssetRemoval(), service.themes
        )
    ).status == Status.OK

    # Monitored ops
    mon = await collections_router.set_collection_monitored(
        1, MonitorUpdate(monitored=True), service.editor
    )
    assert mon.monitored is True
    bulk_mon = BulkCollectionMonitorUpdate(collection_ids=[1], monitored=True)
    bulk_res = await collections_router.bulk_set_collection_monitored(
        bulk_mon, service.editor
    )
    assert bulk_res.updated == 1

    # Proxy image
    img_resp = await collections_router.proxy_collection_image(
        1, ArtType.POSTER, service.reader
    )
    assert img_resp.body == b"img"

    rule_write = library_rule(
        criteria=FilterGroup(
            conditions=[SourceCondition(source=TmdbCollectionSource(collection_id=10))]
        )
    )
    # Create, update, delete
    create = CollectionCreate(
        title="Star Wars",
        rule=rule_write,
    )
    assert (await collections_router.create_collection(create, service.editor)).id == 1
    options = CollectionOptions(title="Star Wars Updated")
    updated = await collections_router.update_collection(1, options, service.editor)
    assert updated.id == 1
    deleted = await collections_router.delete_collection(1, service.editor)
    assert deleted.status == Status.OK
    service.editor.delete.assert_awaited_with(1, target="both")
    await collections_router.delete_collection(1, service.editor, "server")
    service.editor.delete.assert_awaited_with(1, target="server")

    # Members
    members = CollectionMembersUpdate(
        member_ids=[10, 20], order_type=CollectionOrder.RELEASE_ASC
    )
    set_mem = await collections_router.set_collection_members(
        1, members, service.editor
    )
    assert set_mem.id == 1

    # Rules
    saved_rule = await collections_router.save_collection_rule(
        1, rule_write, service.editor
    )
    assert (
        saved_rule.libraries[0].criteria.source_conditions()[0].source.type
        == "tmdb_collection"
    )

    # Art endpoints
    removal = AssetRemoval(delete_from_server=True)
    all_art = await collections_router.remove_all_collection_art(
        1, removal, art_service
    )
    assert all_art.status is Status.OK
    await collections_router.remove_collection_art(
        1, ArtType.POSTER, removal, art_service
    )
    assert art_service.remove.await_args_list[-1].args == (1, ArtType.POSTER, removal)
    art_sources = await collections_router.get_collection_art_sources(
        1, ArtType.POSTER, art_service
    )
    assert art_sources.current_url is None
    save_art = SaveArtRequest(url="https://example.com/poster.jpg")
    saved_art = await collections_router.save_collection_art(
        1, ArtType.POSTER, save_art, art_service
    )
    assert saved_art.status == Status.OK
    matched = await collections_router.match_collection_art(
        1, ArtType.POSTER, art_service
    )
    assert len(matched.matches) == 0
