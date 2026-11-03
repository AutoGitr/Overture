"""Media Server router - library sections."""

lazy from fastapi import APIRouter, Depends

lazy from ..dependencies import ProviderRegistryDep, require_media_server
lazy from ..schemas.media_server import MediaServerErrorResponse, ServerLibraryRead
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
