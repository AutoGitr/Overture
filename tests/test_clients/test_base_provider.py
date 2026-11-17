"""Shared provider section sorting and selection through a concrete adapter."""

lazy import pytest

lazy from overture.config import Settings
lazy from overture.domain import MediaType, ServerType
lazy from overture.media_servers.adapters import ServerSection
lazy from overture.media_servers.jellyfin import JellyfinProvider
lazy from tests.media_servers import TEST_SERVER_ID, server_of


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch, app_config: Settings) -> JellyfinProvider:
    provider = JellyfinProvider(
        server=server_of(app_config, ServerType.JELLYFIN),
        server_id=TEST_SERVER_ID,
        app_config=app_config,
    )

    async def list_sections() -> list[ServerSection]:
        return [
            ServerSection("shows", "A Shows", MediaType.SHOW, library_id="1:shows"),
            ServerSection("z", "Z Movies", MediaType.MOVIE, library_id="1:z"),
            ServerSection("a", "A Movies", MediaType.MOVIE, library_id="1:a"),
        ]

    monkeypatch.setattr(provider, "_list_sections", list_sections)
    return provider


async def test_sections_list_movies_first_then_by_title(
    provider: JellyfinProvider,
) -> None:
    assert [section.key for section in await provider.get_sections()] == [
        "a",
        "z",
        "shows",
    ]
    selected = await provider.select_sections(["1:shows", "1:z"])
    assert [section.key for section in selected] == ["z", "shows"]
