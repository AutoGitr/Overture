"""Media Server router - the configured servers' libraries and web links."""

lazy from fastapi import APIRouter, Depends

lazy from ..dependencies import ProviderRegistryDep, require_media_server
lazy from ..schemas.media_server import (
    MediaServerErrorResponse,
    ServerLibraryRead,
    ServerWebLinksRead,
)
lazy from .auth import require_auth

router = APIRouter(
    prefix="/media-server",
    tags=["media-server"],
    dependencies=[Depends(require_auth), Depends(require_media_server)],
)


@router.get(
    "/libraries",
    responses={
        502: {"model": MediaServerErrorResponse},
        503: {"model": MediaServerErrorResponse},
    },
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
    responses={
        502: {"model": MediaServerErrorResponse},
        503: {"model": MediaServerErrorResponse},
    },
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
