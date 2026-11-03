"""Provider collection mutations use their documented wire contracts."""

lazy import base64
lazy import json

lazy import httpx2
lazy import pytest

lazy from overture.config import Settings
lazy from overture.domain import (
    ArtType,
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    MediaType,
)
lazy from overture.media_servers.emby.client import EmbyClient
lazy from overture.media_servers.jellyfin.client import JellyfinClient
lazy from overture.media_servers.plex.client import PlexClient
lazy from tests.http_mock import keep_configured_plex_url, mock_client_factory


@pytest.mark.parametrize("client_type", [JellyfinClient, EmbyClient])
async def test_boxsets_create_diff_edit_art_and_delete(
    client_type: type[JellyfinClient], app_config: Settings
) -> None:
    requests: list[httpx2.Request] = []
    emby = client_type is EmbyClient
    item = {
        "Id": "box",
        "Name": "Before",
        "ProviderIds": {"Tmdb": "10"},
        "LockedFields": ["Overview"],
    }

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        path = request.url.path.removeprefix("/emby")
        if request.method == "GET":
            if path == "/Items/box":
                return httpx2.Response(200, json=item)
            if request.url.params.get("Ids" if emby else "ids"):
                return httpx2.Response(
                    200, json={"Items": [item], "TotalRecordCount": 1}
                )
            return httpx2.Response(
                200,
                json={
                    "Items": [{"Id": "keep"}, {"Id": "remove"}],
                    "TotalRecordCount": 2,
                },
            )
        return httpx2.Response(200, json={"Id": "box"})

    factory, _transport = mock_client_factory(handle)
    client = client_type(app_config=app_config, client_factory=factory)
    try:
        assert await client.create_collection("New", ["keep"]) == "box"
        await client.set_collection_members("box", ["keep", "add"])
        await client.update_collection_details(
            "box", "After", "Summary", "!After", CollectionOrder.TITLE_ASC
        )
        await client.upload_collection_art("box", ArtType.POSTER, b"image", "image/png")
        await client.delete_item("box")
    finally:
        await client.close()
    mutations = [request for request in requests if request.method != "GET"]
    assert mutations[0].url.params.get("Name" if emby else "name") == "New"
    assert mutations[1].url.params.get("Ids" if emby else "ids") == "add"
    assert mutations[2].method == "DELETE"
    assert mutations[2].url.params.get("Ids" if emby else "ids") == "remove"
    metadata = json.loads(mutations[3].content)
    assert metadata["Name"] == "After"
    assert metadata["ProviderIds"] == {"Tmdb": "10"}
    assert metadata["LockedFields"] == ["Overview"]
    assert metadata["DisplayOrder"] == "SortName"
    # Jellyfin's editor sends ForcedSortName; Emby ignores it and reads SortName.
    assert metadata["SortName" if emby else "ForcedSortName"] == "!After"
    assert base64.b64decode(mutations[4].content) == b"image"
    assert mutations[4].headers["Content-Type"] == "image/png"
    assert mutations[-1].method == "DELETE"


async def test_plex_creates_then_diffs_moves_and_uploads_bytes(
    monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        path = request.url.path
        if path.endswith("/identity"):
            return httpx2.Response(
                200, json={"MediaContainer": {"machineIdentifier": "server"}}
            )
        if path.endswith("/children"):
            return httpx2.Response(
                200,
                json={
                    "MediaContainer": {
                        "Metadata": [{"ratingKey": "keep"}, {"ratingKey": "remove"}],
                        "totalSize": 2,
                    }
                },
            )
        if path == "/library/metadata/box" and request.method == "GET":
            return httpx2.Response(
                200,
                json={
                    "MediaContainer": {
                        "Metadata": [{"ratingKey": "box", "librarySectionID": "1"}]
                    }
                },
            )
        if path == "/hubs/sections/1/manage" and request.method == "GET":
            return httpx2.Response(200, json={"MediaContainer": {"Hub": []}})
        return httpx2.Response(
            200, json={"MediaContainer": {"Metadata": [{"ratingKey": "box"}]}}
        )

    factory, _transport = mock_client_factory(handle)
    client = PlexClient(app_config=app_config, client_factory=factory)
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    try:
        assert (await client.create_collection("1", "Saga", MediaType.MOVIE, ["keep"]))[
            "ratingKey"
        ] == "box"
        await client.set_collection_members(
            "box", ["add", "keep"], CollectionOrder.CRITIC_RATING_DESC
        )
        await client.update_collection_details(
            "box",
            title="Saga",
            summary=None,
            sort_title="!Saga",
            mode=CollectionMode.HIDE_ITEMS,
            order=CollectionOrder.CRITIC_RATING_DESC,
            smart=False,
            visible_home=True,
            filtering=CollectionFiltering.USER,
        )
        await client.update_collection_details(
            "box",
            title="Saga",
            summary="",
            sort_title=None,
            mode=CollectionMode.DEFAULT,
            order=CollectionOrder.CRITIC_RATING_DESC,
            smart=True,
            visible_home=False,
            filtering=CollectionFiltering.USER,
        )
        await client.upload_collection_art(
            "box", ArtType.BACKGROUND, b"image", "image/jpeg"
        )
        await client.delete_collection("box")
    finally:
        await client.close()
    mutations = [
        (r.method, r.url.path, dict(r.url.params))
        for r in requests
        if r.method != "GET"
    ]
    assert ("DELETE", "/library/collections/box/items/remove", {}) in mutations
    moves = [entry for entry in mutations if entry[1].endswith("/move")]
    assert moves == [
        ("PUT", "/library/collections/box/items/add/move", {}),
        ("PUT", "/library/collections/box/items/keep/move", {"after": "add"}),
    ]
    edits = [
        entry[2] for entry in mutations if entry[:2] == ("PUT", "/library/metadata/box")
    ]
    # An unset summary or sort title stays as it is; an empty one is cleared.
    assert edits == [
        {
            "title.value": "Saga",
            "title.locked": "1",
            "titleSort.value": "!Saga",
            "titleSort.locked": "1",
        },
        {
            "title.value": "Saga",
            "title.locked": "1",
            "summary.value": "",
            "summary.locked": "0",
        },
    ]
    prefs = [entry[2] for entry in mutations if entry[1].endswith("/prefs")]
    # Plex keeps an order it cannot sort by as its custom order. It refuses a
    # smart collection's sort and a regular collection's user filtering.
    assert prefs == [
        {"collectionMode": "1", "collectionSort": "2"},
        {"collectionMode": "-1", "collectionFilterBasedOnUser": "1"},
    ]
    upload = next(r for r in requests if r.url.path == "/library/metadata/box/art")
    assert upload.content == b"image"
    assert mutations[-1] == ("DELETE", "/library/metadata/box", {})


@pytest.mark.parametrize("client_type", [JellyfinClient, EmbyClient])
async def test_boxset_append_never_removes_new_remote_members(
    client_type: type[JellyfinClient], app_config: Settings
) -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.method == "GET":
            return httpx2.Response(
                200, json={"Items": [{"Id": "manual"}], "TotalRecordCount": 1}
            )
        assert request.method == "POST"
        return httpx2.Response(200)

    factory, transport = mock_client_factory(handle)
    client = client_type(app_config=app_config, client_factory=factory)
    try:
        assert await client.set_collection_members("box", ["source"], append=True) == [
            "source",
            "manual",
        ]
        assert all(request.method != "DELETE" for request in transport.requests)
    finally:
        await client.close()


async def test_plex_append_preserves_manual_remote_members(
    monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/identity"):
            return httpx2.Response(
                200, json={"MediaContainer": {"machineIdentifier": "server"}}
            )
        if request.url.path.endswith("/children"):
            return httpx2.Response(
                200,
                json={
                    "MediaContainer": {
                        "Metadata": [{"ratingKey": "manual"}],
                        "totalSize": 1,
                    }
                },
            )
        assert request.method == "PUT"
        return httpx2.Response(200)

    factory, transport = mock_client_factory(handle)
    client = PlexClient(app_config=app_config, client_factory=factory)
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    try:
        assert await client.set_collection_members(
            "box", ["source"], CollectionOrder.CUSTOM, append=True
        ) == ["source", "manual"]
        assert all(request.method != "DELETE" for request in transport.requests)
    finally:
        await client.close()


async def test_plex_labels_keep_the_labels_items_already_have(
    monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200)

    factory, transport = mock_client_factory(handle)
    client = PlexClient(app_config=app_config, client_factory=factory)
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    try:
        await client.sync_item_labels(
            "1",
            MediaType.MOVIE,
            "overture:mdblist:a/b",
            add={
                "m1": [],
                "m2": ["Kids"],
                "m3": [],
                "m4": ["kids", "Overture:mdblist:a/b"],
            },
            remove_ids=["m9"],
        )
    finally:
        await client.close()
    edits = [dict(request.url.params) for request in transport.requests]
    # Plex replaces an item's labels with those it is sent.
    assert [
        {key: value for key, value in edit.items() if key.startswith("label")}
        for edit in edits
    ] == [
        {"label[0].tag.tag": "overture:mdblist:a/b", "label.locked": "1"},
        {
            "label[0].tag.tag": "Kids",
            "label[1].tag.tag": "overture:mdblist:a/b",
            "label.locked": "1",
        },
        {
            "label[0].tag.tag": "kids",
            "label[1].tag.tag": "overture:mdblist:a/b",
            "label.locked": "1",
        },
        {"label[].tag.tag-": "overture:mdblist:a/b"},
    ]
    assert [edit["id"] for edit in edits] == ["m1,m3", "m2", "m4", "m9"]


async def test_plex_filter_choices_decode_the_keys_plex_encodes(
    monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        directory = [
            {"key": "01%2520Start%2520Films", "title": "01 Start Films"},
            {"key": "16%2B", "title": "16+"},
            {"key": "42", "title": "Action"},
        ]
        return httpx2.Response(200, json={"MediaContainer": {"Directory": directory}})

    factory, transport = mock_client_factory(handle)
    client = PlexClient(app_config=app_config, client_factory=factory)
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    try:
        choices = await client.get_filter_choices("1", MediaType.MOVIE, "studio")
        await client.get_filter_choices("2", MediaType.SHOW, "episode.resolution")
    finally:
        await client.close()
    # Plex matches only decoded values; studios arrive encoded twice.
    assert choices == [
        ("01 Start Films", "01 Start Films"),
        ("16+", "16+"),
        ("42", "Action"),
    ]
    # Show sections list an episode field's values among their episodes.
    assert [
        (request.url.path, request.url.params["type"]) for request in transport.requests
    ] == [("/library/sections/1/studio", "1"), ("/library/sections/2/resolution", "4")]
