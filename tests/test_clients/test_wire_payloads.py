"""Provider metadata is validated before it reaches synchronization."""

lazy import pytest

lazy from overture.config import Settings
lazy from overture.media_servers.emby.client import EmbyClient
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.jellyfin.client import JellyfinClient
lazy from overture.media_servers.plex.client import PlexClient
lazy from overture.media_servers.wire import media_browser_items


async def _list_items(client: PlexClient | JellyfinClient) -> None:
    """Read every page of a movie section."""
    pages = (
        client.iter_section_items("1")
        if isinstance(client, PlexClient)
        else client.iter_section_items("1", "Movie")
    )
    async for _page in pages:
        pass


@pytest.mark.parametrize("metadata", [{"TotalRecordCount": 2}, {"StartIndex": 1}])
def test_unpaginated_listing_must_contain_the_complete_result(
    metadata: dict[str, int],
) -> None:
    with pytest.raises(MediaServerError):
        media_browser_items({"Items": [{"Id": "1"}], **metadata})


@pytest.mark.parametrize("client_type", [PlexClient, JellyfinClient, EmbyClient])
@pytest.mark.parametrize("malformed", [[], {}, {"unexpected": "payload"}])
async def test_item_listing_rejects_malformed_envelopes(
    client_type: type[PlexClient | JellyfinClient],
    malformed: object,
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    async def response(*_args: object, **_kwargs: object) -> object:
        return malformed

    client = client_type(app_config=app_config)
    monkeypatch.setattr(client, "_get", response)
    with pytest.raises(MediaServerError):
        await _list_items(client)


@pytest.mark.parametrize("client_type", [PlexClient, JellyfinClient, EmbyClient])
async def test_item_listing_rejects_invalid_field_types(
    client_type: type[PlexClient | JellyfinClient],
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    client = client_type(app_config=app_config)
    payload = (
        {"MediaContainer": {"Metadata": [{"ratingKey": "1", "year": "invalid"}]}}
        if isinstance(client, PlexClient)
        else {"Items": [{"Id": "1", "ProductionYear": "invalid"}]}
    )

    async def response(*_args: object, **_kwargs: object) -> object:
        return payload

    monkeypatch.setattr(client, "_get", response)
    with pytest.raises(MediaServerError):
        await _list_items(client)


@pytest.mark.parametrize("client_type", [JellyfinClient, EmbyClient])
async def test_media_browser_listing_accepts_nullable_optional_metadata(
    client_type: type[JellyfinClient],
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    metadata = {"Id": "1", "Name": None, "ImageTags": None, "ProviderIds": None}

    async def response(*_args: object, **_kwargs: object) -> object:
        return {"Items": [metadata], "TotalRecordCount": 1}

    client = client_type(app_config=app_config)
    monkeypatch.setattr(client, "_get", response)
    pages = client.iter_section_items("1", "Movie")
    assert [item async for page in pages for item in page] == [metadata]


async def test_plex_empty_container_is_an_empty_listing(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    async def response(*_args: object, **_kwargs: object) -> object:
        return {"MediaContainer": {"size": 0, "totalSize": 0}}

    client = PlexClient(app_config=app_config)
    monkeypatch.setattr(client, "_get", response)
    pages = client.iter_section_items("1")
    assert [item async for page in pages for item in page] == []


@pytest.mark.parametrize("client_type", [PlexClient, JellyfinClient, EmbyClient])
async def test_section_listing_without_total_is_not_a_complete_snapshot(
    client_type: type[PlexClient | JellyfinClient],
    monkeypatch: pytest.MonkeyPatch,
    *,
    app_config: Settings,
) -> None:
    client = client_type(app_config=app_config)
    payload = (
        {"MediaContainer": {"Metadata": [{"ratingKey": "1"}]}}
        if isinstance(client, PlexClient)
        else {"Items": [{"Id": "1"}]}
    )

    async def response(*_args: object, **_kwargs: object) -> object:
        return payload

    monkeypatch.setattr(client, "_get", response)
    pages = (
        client.iter_section_items("1")
        if isinstance(client, PlexClient)
        else client.iter_section_items("1", "Movie")
    )
    with pytest.raises(MediaServerError, match="listing total"):
        async for _page in pages:
            pass


async def test_plex_metadata_page_ignores_non_section_directory_elements(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    payload = {
        "MediaContainer": {
            "size": 1,
            "totalSize": 1,
            "Directory": [
                {"leafCount": 84, "thumb": "/thumb", "title": "All episodes"}
            ],
            "Metadata": [{"ratingKey": "10", "title": "Season 1"}],
        }
    }

    async def response(*_args: object, **_kwargs: object) -> object:
        return payload

    client = PlexClient(app_config=app_config)
    monkeypatch.setattr(client, "_get", response)
    items = await client.get_children("1")
    assert len(items) == 1
    assert items[0]["ratingKey"] == "10"


async def test_plex_sections_rejects_items_without_type(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    payload = {
        "MediaContainer": {
            "size": 1,
            "totalSize": 1,
            "Directory": [
                {"leafCount": 84, "thumb": "/thumb", "title": "All episodes"}
            ],
        }
    }

    async def response(*_args: object, **_kwargs: object) -> object:
        return payload

    client = PlexClient(app_config=app_config)
    monkeypatch.setattr(client, "_get", response)
    with pytest.raises(MediaServerError):
        await client.get_sections()
