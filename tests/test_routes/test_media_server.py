"""Media-server router conversion of provider sections to public library rows."""

lazy from overture.domain import MediaType
lazy from overture.media_servers.adapters import ServerSection
lazy from overture.routers import media_server
lazy from overture.schemas.media_server import ServerLibraryRead
lazy from tests.runtime_helpers import NoopProviderRegistry


async def test_libraries_route_lists_the_sections_in_their_public_form() -> None:
    class Provider:
        async def get_sections(self) -> list[ServerSection]:
            return [
                ServerSection("a", "A Movies", MediaType.MOVIE),
                ServerSection("z", "Z Movies", MediaType.MOVIE),
                ServerSection("shows", "A Shows", MediaType.SHOW),
            ]

    assert await media_server.list_server_libraries(
        NoopProviderRegistry(Provider())
    ) == [
        ServerLibraryRead(key="a", title="A Movies", media_type=MediaType.MOVIE),
        ServerLibraryRead(key="z", title="Z Movies", media_type=MediaType.MOVIE),
        ServerLibraryRead(key="shows", title="A Shows", media_type=MediaType.SHOW),
    ]
