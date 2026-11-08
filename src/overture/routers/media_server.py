"""Media Server router - library sections."""

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
    """List the media server's movie and show libraries, movies first."""
    return [
        ServerLibraryRead.from_section(section)
        for section in await providers.provider.get_sections()
    ]


@router.get(
    "/links",
    responses={
        502: {"model": MediaServerErrorResponse},
        503: {"model": MediaServerErrorResponse},
    },
)
async def get_server_web_links(providers: ProviderRegistryDep) -> ServerWebLinksRead:
    """Return where the server's web app opens items and collections."""
    links = await providers.provider.web_links()
    return ServerWebLinksRead(item=links.item, collection=links.collection)
