"""Media Server router - the configured servers' libraries and web links."""

lazy from ..dependencies import ProviderRegistryDep
lazy from ..schemas.media_server import (
    ServerLibraryRead,
    ServerWebLinksRead,
)
lazy from .auth import media_server_router

router = media_server_router(prefix="/media-server", tags=["media-server"])


@router.get(
    "/libraries",
)
async def list_server_libraries(
    providers: ProviderRegistryDep,
) -> list[ServerLibraryRead]:
    """List the servers' movie and show libraries, the lead server's first."""
    return [
        ServerLibraryRead.from_section(section, provider.server_id)
        for provider, section in await providers.libraries()
    ]


@router.get(
    "/links",
)
async def get_server_web_links(
    providers: ProviderRegistryDep,
) -> list[ServerWebLinksRead]:
    """Return where each server's web app opens items and collections."""
    return [
        ServerWebLinksRead(
            server_id=provider.server_id, item=links.item, collection=links.collection
        )
        for provider, links in await providers.web_links()
    ]
