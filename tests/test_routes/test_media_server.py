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
                ServerSection("a", "A Movies", MediaType.MOVIE, library_id="1:a"),
                ServerSection("z", "Z Movies", MediaType.MOVIE, library_id="1:z"),
                ServerSection("shows", "A Shows", MediaType.SHOW, library_id="1:shows"),
            ]

    assert await media_server.list_server_libraries(
        NoopProviderRegistry(Provider())
    ) == [
        ServerLibraryRead(
            key="1:a", title="A Movies", media_type=MediaType.MOVIE, server_id=1
        ),
        ServerLibraryRead(
            key="1:z", title="Z Movies", media_type=MediaType.MOVIE, server_id=1
        ),
        ServerLibraryRead(
            key="1:shows", title="A Shows", media_type=MediaType.SHOW, server_id=1
        ),
    ]
