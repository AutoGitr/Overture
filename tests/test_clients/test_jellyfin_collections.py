"""Adapting Jellyfin BoxSets to the shared collection contract."""

lazy from typing import override

lazy from overture.config import Settings
lazy from overture.media_servers.jellyfin.client import JellyfinClient
lazy from overture.media_servers.jellyfin.provider import JellyfinProvider
lazy from overture.media_servers.wire import MediaBrowserItem


class Client(JellyfinClient):
    @override
    async def get_boxsets(self) -> list[MediaBrowserItem]:
        return [
            {
                "Id": "box",
                "Name": "Saga",
                "Overview": "Every part",
                "ProviderIds": {"Tmdb": "10"},
                "Path": "/config/data/collections/Saga [boxset]",
                "ImageTags": {"Primary": "tag"},
                "DateCreated": "2026-01-01T00:00:00Z",
            },
            {"Id": "custom", "Name": "Favourites", "ProviderIds": {"Tmdb": "x"}},
        ]

    @override
    async def get_boxset_member_ids(self, boxset_id: str) -> list[str]:
        return ["m1", "m2"] if boxset_id == "box" else []


async def test_boxsets_carry_their_folder_tmdb_collection_and_members(
    app_config: Settings,
) -> None:
    app_config.MEDIA_SERVER_URL = "https://jellyfin.test"
    provider = JellyfinProvider(
        client=Client(app_config=app_config), app_config=app_config
    )

    saga, custom = await provider.list_collections()

    assert (saga.id, saga.title, saga.summary) == ("box", "Saga", "Every part")
    assert saga.member_ids == ("m1", "m2")
    assert (saga.tmdb_id, saga.path) == (10, "/config/data/collections/Saga [boxset]")
    # Jellyfin keeps BoxSets outside the libraries: the sync asks the members.
    assert (saga.media_type, saga.library_id) == (None, None)
    assert saga.thumb_url == "https://jellyfin.test/Items/box/Images/Primary?tag=tag"
    assert saga.art_url is None
    assert saga.added_at is not None
    assert (custom.tmdb_id, custom.member_ids) == (None, ())
    assert custom.server_link.endswith("details?id=custom")
