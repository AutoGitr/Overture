"""Shared provider section sorting and selection through a concrete adapter."""

lazy import pytest

lazy from overture.config import Settings
lazy from overture.domain import MediaType
lazy from overture.media_servers.adapters import ServerSection
lazy from overture.media_servers.jellyfin import JellyfinProvider


@pytest.fixture
def provider(monkeypatch: pytest.MonkeyPatch, app_config: Settings) -> JellyfinProvider:
    provider = JellyfinProvider(app_config=app_config)

    async def list_sections() -> list[ServerSection]:
        return [
            ServerSection("shows", "A Shows", MediaType.SHOW),
            ServerSection("z", "Z Movies", MediaType.MOVIE),
            ServerSection("a", "A Movies", MediaType.MOVIE),
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
    selected = await provider.select_sections(["shows", "z"])
    assert [section.key for section in selected] == ["z", "shows"]
