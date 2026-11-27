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
lazy from overture.media_servers.adapters import CollectionDetails
lazy from overture.media_servers.emby.client import EmbyClient
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.jellyfin.client import JellyfinClient
lazy from overture.media_servers.plex.client import PlexClient, longest_ordered_run
lazy from tests.http_mock import keep_configured_plex_url, mock_client_factory
lazy from tests.media_servers import media_client, server_of

#: A server's users, of whom an administrator sees every library.
_USERS = [
    {"Id": "viewer", "Policy": {"IsAdministrator": False}},
    {"Id": "admin", "Policy": {"IsAdministrator": True}},
]


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
        "LockData": False,
        "LockedFields": ["Tags"],
    }

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        path = request.url.path.removeprefix("/emby")
        if path == "/Users":
            return httpx2.Response(200, json=_USERS)
        if request.method == "GET":
            # The metadata editor's read, as a user who sees every library.
            if path == ("/Users/admin/Items/box" if emby else "/Items/box"):
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
    client = media_client(client_type, app_config, client_factory=factory)
    try:
        assert await client.create_collection("New", ["keep"]) == ("box", ["keep"])
        await client.set_collection_members("box", ["keep", "add"])
        await client.update_collection_details(
            "box",
            CollectionDetails(
                title="After",
                summary="Summary",
                sort_title="!After",
                mode=CollectionMode.DEFAULT,
                order=CollectionOrder.TITLE_ASC,
                smart=False,
                visible_home=False,
            ),
        )
        await client.upload_collection_art("box", ArtType.POSTER, b"image", "image/png")
        await client.upload_collection_art(
            "box", ArtType.BACKGROUND, b"backdrop", "image/jpeg"
        )
        await client.delete_item("box")
    finally:
        await client.close()
    mutations = [request for request in requests if request.method != "GET"]
    # A BoxSet's items are listed to a user, and an API key has none.
    listings = [
        request
        for request in requests
        if request.url.params.get("ParentId" if emby else "parentId") == "box"
    ]
    assert listings
    # Jellyfin lists a BoxSet's items only to a user; Emby to the API key.
    assert {r.url.params.get("UserId" if emby else "userId") for r in listings} == {
        None if emby else "admin"
    }
    # Emby refuses a BoxSet made without items; a locked one keeps its name
    # when the server's refresh matches it to a TMDB collection.
    assert mutations[0].url.params.get("Name" if emby else "name") == "New"
    assert mutations[0].url.params.get("Ids" if emby else "ids") == "keep"
    assert mutations[0].url.params.get("IsLocked" if emby else "isLocked") == "true"
    assert mutations[1].url.params.get("Ids" if emby else "ids") == "add"
    assert mutations[2].method == "DELETE"
    assert mutations[2].url.params.get("Ids" if emby else "ids") == "remove"
    metadata = json.loads(mutations[3].content)
    assert metadata["Name"] == "After"
    # Changing the item's own lock would change every member's too.
    assert metadata["LockData"] is False
    assert metadata["ProviderIds"] == {"Tmdb": "10"}
    # The fields Overture writes are locked; Emby keeps a sort title through
    # refreshes only while SortName is locked as well.
    assert metadata["LockedFields"] == (
        ["Tags", "Name", "Overview", "SortName"]
        if emby
        else ["Tags", "Name", "Overview"]
    )
    assert metadata["DisplayOrder"] == "SortName"
    assert metadata["ForcedSortName"] == "!After"
    assert base64.b64decode(mutations[4].content) == b"image"
    assert mutations[4].headers["Content-Type"] == "image/png"
    assert mutations[4].url.path.endswith("/Items/box/Images/Primary")
    assert base64.b64decode(mutations[5].content) == b"backdrop"
    assert mutations[5].url.path.endswith("/Items/box/Images/Backdrop/0")
    assert mutations[-1].method == "DELETE"


async def test_emby_clearing_a_sort_title_releases_its_lock(
    app_config: Settings,
) -> None:
    item = {
        "Id": "box",
        "Name": "Box",
        "SortName": "!Box",
        "ForcedSortName": "!Box",
        "LockData": True,
        "LockedFields": ["Name", "SortName"],
    }
    updates: list[dict[str, object]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            updates.append(json.loads(request.content))
            return httpx2.Response(204)
        if request.url.path.endswith("/Users"):
            return httpx2.Response(200, json=_USERS)
        return httpx2.Response(200, json=item)

    factory, _transport = mock_client_factory(handle)
    client = media_client(EmbyClient, app_config, client_factory=factory)
    try:
        await client.update_collection_details(
            "box",
            CollectionDetails(
                title="Box",
                summary=None,
                sort_title="",
                mode=CollectionMode.DEFAULT,
                order=CollectionOrder.TITLE_ASC,
                smart=False,
                visible_home=False,
            ),
        )
    finally:
        await client.close()
    assert updates[0]["LockedFields"] == ["Name"]
    assert updates[0]["ForcedSortName"] is None
    assert updates[0]["LockData"] is True


async def test_emby_clearing_a_summary_hands_it_back_unlocked(
    app_config: Settings,
) -> None:
    item = {
        "Id": "box",
        "Name": "Box",
        "Overview": "Old",
        "LockData": True,
        "LockedFields": ["Tags", "Overview", "Name"],
    }
    updates: list[dict[str, object]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            updates.append(json.loads(request.content))
            return httpx2.Response(204)
        if request.url.path.endswith("/Users"):
            return httpx2.Response(200, json=_USERS)
        return httpx2.Response(200, json=item)

    factory, _transport = mock_client_factory(handle)
    client = media_client(EmbyClient, app_config, client_factory=factory)
    try:
        await client.update_collection_details(
            "box",
            CollectionDetails(
                title="Box",
                summary="",
                sort_title=None,
                mode=CollectionMode.DEFAULT,
                order=CollectionOrder.TITLE_ASC,
                smart=False,
                visible_home=False,
            ),
        )
    finally:
        await client.close()
    assert updates[0]["LockedFields"] == ["Tags", "Name"]
    assert updates[0]["Overview"] == ""


@pytest.mark.parametrize("client_type", [JellyfinClient, EmbyClient])
async def test_a_collection_the_server_does_not_return_whole_is_left_as_it_is(
    client_type: type[JellyfinClient], app_config: Settings
) -> None:
    posted: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.method == "POST":
            posted.append(request)
            return httpx2.Response(204)
        if request.url.path.endswith("/Users"):
            return httpx2.Response(200, json=_USERS)
        return httpx2.Response(200, json={"Id": "box", "Name": "Box"})

    factory, _transport = mock_client_factory(handle)
    client = media_client(client_type, app_config, client_factory=factory)
    try:
        with pytest.raises(MediaServerError, match="left as it is"):
            await client.update_collection_details(
                "box",
                CollectionDetails(
                    title="Box",
                    summary=None,
                    sort_title=None,
                    mode=CollectionMode.DEFAULT,
                    order=CollectionOrder.TITLE_ASC,
                    smart=False,
                    visible_home=False,
                ),
            )
    finally:
        await client.close()
    assert posted == []


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
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
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
            "1",
            CollectionDetails(
                title="Saga",
                summary=None,
                sort_title="!Saga",
                mode=CollectionMode.HIDE_ITEMS,
                order=CollectionOrder.CRITIC_RATING_DESC,
                smart=False,
                visible_home=True,
                filtering=CollectionFiltering.USER,
            ),
        )
        await client.update_collection_details(
            "box",
            "1",
            CollectionDetails(
                title="Saga",
                summary="",
                sort_title=None,
                mode=CollectionMode.DEFAULT,
                order=CollectionOrder.CRITIC_RATING_DESC,
                smart=True,
                visible_home=False,
                filtering=CollectionFiltering.USER,
            ),
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
    # Plex appends the new item after "keep", so only "keep" moves.
    assert moves == [
        ("PUT", "/library/collections/box/items/keep/move", {"after": "add"}),
    ]
    # The collection's library is known, so Plex is not asked for it.
    assert not any(
        r.method == "GET" and r.url.path == "/library/metadata/box" for r in requests
    )
    edits = [
        entry[2]
        for entry in mutations
        if entry[:2] == ("PUT", "/library/sections/1/all")
    ]
    # The section edits the collection, which renames its members' tag too.
    # An unset summary or sort title stays as it is; an empty one is cleared.
    edited = {"type": "18", "id": "box", "includeExternalMedia": "1"}
    assert edits == [
        {
            **edited,
            "title.value": "Saga",
            "title.locked": "1",
            "titleSort.value": "!Saga",
            "titleSort.locked": "1",
        },
        {
            **edited,
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
    upload = next(r for r in requests if r.url.path == "/library/metadata/box/arts")
    assert upload.content == b"image"
    assert mutations[-1] == ("DELETE", "/library/metadata/box", {})


@pytest.mark.parametrize("client_type", [JellyfinClient, EmbyClient])
async def test_large_boxset_writes_fit_the_servers_request_line(
    client_type: type[JellyfinClient], app_config: Settings
) -> None:
    members = [f"{index:032x}" for index in range(1500)]
    current = [f"{index:032x}" for index in range(5000, 6000)]

    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/Users"):
            return httpx2.Response(200, json=_USERS)
        if request.method == "GET":
            return httpx2.Response(
                200,
                json={
                    "Items": [{"Id": identity} for identity in current],
                    "TotalRecordCount": len(current),
                },
            )
        return httpx2.Response(200, json={"Id": "box"})

    factory, transport = mock_client_factory(handle)
    client = media_client(client_type, app_config, client_factory=factory)
    try:
        await client.create_collection("Large", members)
        await client.set_collection_members("box", members)
    finally:
        await client.close()
    writes = [request for request in transport.requests if request.method != "GET"]
    # Kestrel answers 414 to a request line over 8 KiB.
    assert max(len(request.url.raw_path) for request in writes) < 8192
    key = "Ids" if client_type is EmbyClient else "ids"
    sent: dict[str, set[str]] = {
        request.method: set()
        for request in writes
        if request.url.params.get(key) is not None
    }
    for request in writes:
        if ids := request.url.params.get(key):
            sent[request.method].update(ids.split(","))
    assert sent == {"POST": set(members), "DELETE": set(current)}


@pytest.mark.parametrize("client_type", [JellyfinClient, EmbyClient])
async def test_boxset_append_never_removes_new_remote_members(
    client_type: type[JellyfinClient], app_config: Settings
) -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        if request.url.path.endswith("/Users"):
            return httpx2.Response(200, json=_USERS)
        if request.method == "GET":
            return httpx2.Response(
                200, json={"Items": [{"Id": "manual"}], "TotalRecordCount": 1}
            )
        assert request.method == "POST"
        return httpx2.Response(200)

    factory, transport = mock_client_factory(handle)
    client = media_client(client_type, app_config, client_factory=factory)
    try:
        write = await client.set_collection_members("box", ["source"], append=True)
        assert (write.held, write.added, write.removed) == (
            ["source", "manual"],
            1,
            0,
        )
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
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    try:
        write = await client.set_collection_members(
            "box", ["source"], CollectionOrder.CUSTOM, append=True
        )
        assert (write.held, write.added, write.removed) == (
            ["source", "manual"],
            1,
            0,
        )
        assert all(request.method != "DELETE" for request in transport.requests)
    finally:
        await client.close()


async def test_plex_labels_keep_the_labels_items_already_have(
    monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200)

    factory, transport = mock_client_factory(handle)
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
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
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
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


async def test_plex_names_collections_by_their_rating_key_and_keys_them_by_index(
    monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/library/sections/1/collections"
        rows = [
            {"ratingKey": "c1", "title": "BFI Greats", "index": 7},
            {"ratingKey": "c2", "title": "Unwatched", "index": 8, "smart": "1"},
        ]
        return httpx2.Response(200, json={"MediaContainer": {"Metadata": rows}})

    factory, _transport = mock_client_factory(handle)
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    try:
        choices = await client.get_filter_choices("1", MediaType.MOVIE, "collection")
    finally:
        await client.close()
    assert choices == [("7", "c1")]


async def test_plex_names_the_filter_keys_of_the_values_an_item_holds(
    monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    def handle(request: httpx2.Request) -> httpx2.Response:
        assert request.url.path == "/library/metadata/7"
        row = {
            "ratingKey": "7",
            "Role": [
                {"id": 95049, "filter": "actor=95049", "tag": "Bess Flowers"},
                {"id": 1, "tag": "No filter"},
            ],
        }
        return httpx2.Response(200, json={"MediaContainer": {"Metadata": [row]}})

    factory, _transport = mock_client_factory(handle)
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    try:
        choices = await client.get_item_filter_choices("7", "actor")
    finally:
        await client.close()
    # Plex lists an item's actors as its roles, each with the filter selecting it.
    assert choices == [("95049", "Bess Flowers")]


@pytest.mark.parametrize(
    ("current", "wanted", "settled"),
    [
        (["a", "b", "c", "d"], ["a", "b", "c", "d"], {"a", "b", "c", "d"}),
        (["a", "b", "c", "new"], ["new", "a", "b", "c"], {"a", "b", "c"}),
        (["d", "a", "b", "c"], ["a", "b", "c", "d"], {"a", "b", "c"}),
        ([], ["a"], set[str]()),
    ],
)
def test_only_items_out_of_order_move(
    current: list[str], wanted: list[str], settled: set[str]
) -> None:
    assert longest_ordered_run(current, wanted) == settled


async def test_plex_leaves_a_collections_hub_alone_when_its_visibility_holds(
    monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    hub = {
        "identifier": "custom.collection.1.box",
        "promotedToOwnHome": True,
        "promotedToSharedHome": False,
        "promotedToRecommended": False,
    }
    requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        if request.url.path == "/hubs/sections/1/manage" and request.method == "GET":
            return httpx2.Response(200, json={"MediaContainer": {"Hub": [hub]}})
        return httpx2.Response(200, json={"MediaContainer": {}})

    factory, _transport = mock_client_factory(handle)
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    try:
        for visible_home in (True, False):
            await client.update_collection_details(
                "box",
                "1",
                CollectionDetails(
                    title="Saga",
                    summary=None,
                    sort_title=None,
                    mode=CollectionMode.DEFAULT,
                    order=CollectionOrder.TITLE_ASC,
                    smart=False,
                    visible_home=visible_home,
                ),
            )
    finally:
        await client.close()
    hub_writes = [
        dict(request.url.params)
        for request in requests
        if request.url.path == "/hubs/sections/1/manage/custom.collection.1.box"
    ]
    assert hub_writes == [{"promotedToOwnHome": "0"}]


async def test_plex_edits_an_empty_collection_as_its_metadata_item_without_a_hub(
    monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    calls: list[tuple[str, str]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        calls.append((request.method, request.url.path))
        if request.url.path.startswith("/hubs/") or request.url.path.startswith(
            "/library/sections/"
        ):
            return httpx2.Response(404)
        return httpx2.Response(200, json={"MediaContainer": {}})

    factory, _transport = mock_client_factory(handle)
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    try:
        await client.update_collection_details(
            "separator",
            "1",
            CollectionDetails(
                title="Charts",
                summary=None,
                sort_title="Charts",
                mode=CollectionMode.DEFAULT,
                order=CollectionOrder.TITLE_ASC,
                smart=False,
                visible_home=True,
                empty=True,
            ),
        )
    finally:
        await client.close()
    assert calls == [
        ("PUT", "/library/metadata/separator"),
        ("PUT", "/library/metadata/separator/prefs"),
    ]


async def test_plex_collection_rename_clears_orphaned_tag_when_no_collection_holds_it(
    monkeypatch: pytest.MonkeyPatch, app_config: Settings
) -> None:
    optimized = False
    collections = [{"ratingKey": "box", "title": "Old"}]
    calls: list[tuple[str, str]] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        nonlocal optimized
        calls.append((request.method, request.url.path))
        if request.url.path == "/library/sections/1/all" and not optimized:
            return httpx2.Response(409, text="Conflict")
        if request.url.path == "/library/sections/1/collections":
            return httpx2.Response(
                200, json={"MediaContainer": {"Metadata": collections}}
            )
        if request.url.path == "/library/optimize":
            optimized = True
            return httpx2.Response(200)
        if request.url.path == "/hubs/sections/1/manage":
            return httpx2.Response(200, json={"MediaContainer": {"Hub": []}})
        return httpx2.Response(200, json={"MediaContainer": {}})

    factory, _transport = mock_client_factory(handle)
    client = PlexClient(
        server=server_of(app_config), app_config=app_config, client_factory=factory
    )
    monkeypatch.setattr(PlexClient, "resolve_secure_url", keep_configured_plex_url)
    details = CollectionDetails(
        title="Renamed",
        summary=None,
        sort_title=None,
        mode=CollectionMode.DEFAULT,
        order=CollectionOrder.TITLE_ASC,
        smart=False,
        visible_home=False,
    )
    try:
        await client.update_collection_details("box", "1", details)
        assert ("PUT", "/library/optimize") in calls

        # Another live collection holding the title is a real conflict, not an orphan.
        optimized = False
        collections.append({"ratingKey": "other", "title": "Renamed"})
        with pytest.raises(MediaServerError, match="HTTP 409"):
            await client.update_collection_details("box", "1", details)
    finally:
        await client.close()
