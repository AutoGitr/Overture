"""Art router - sources, save, clear, match.

Every artwork operation acts on one slot, and a slot is named by the item, the
art type, and - for season artwork - the season. All three live in the request
line, so a body carries only what is being written.
"""

lazy from typing import Annotated, Any

lazy from fastapi import APIRouter, Depends, Query, Request

lazy from ..dependencies import ArtDep, ArtUploadsDep, RemoverDep
lazy from ..domain import MATCH_THRESHOLD_DEFAULT, MATCH_THRESHOLD_MAX
lazy from ..schemas.art import (
    ArtMatchResponse,
    ArtSourcesResponse,
    ArtUploadResponse,
    SaveArtRequest,
)
lazy from ..schemas.common import StatusResponse
lazy from ..schemas.library import ItemSelectionResponse
lazy from ..schemas.removal import AssetRemoval, RemovalOptions, RemovalTarget
lazy from ..utils.errors import PublicServiceError
lazy from ..utils.image import MAX_IMAGE_BYTES
lazy from .auth import require_auth
lazy from .parameters import (
    ArtTypePath,
    ItemIdPath,
    SeasonIdQuery,
)

router = APIRouter(prefix="/art", tags=["art"], dependencies=[Depends(require_auth)])

#: The upload body is the image file itself.
_IMAGE_BODY: dict[str, Any] = {
    "requestBody": {
        "required": True,
        "content": {
            "application/octet-stream": {
                "schema": {"type": "string", "format": "binary"}
            }
        },
    }
}


async def _image_body(request: Request) -> bytes:
    """Read an uploaded image, refusing one larger than any image Overture keeps.

    Raises:
        PublicServiceError: 413 once the body passes the limit.
    """
    data = bytearray()
    async for chunk in request.stream():
        data += chunk
        if len(data) > MAX_IMAGE_BYTES:
            raise PublicServiceError(
                413, f"Images may be at most {MAX_IMAGE_BYTES // 1024 // 1024} MB"
            )
    return bytes(data)


@router.post("/uploads", openapi_extra=_IMAGE_BODY)
async def upload_art(request: Request, uploads: ArtUploadsDep) -> ArtUploadResponse:
    """Keep an uploaded JPEG or PNG until an art slot selects it.

    Save it into a slot by sending the returned ``upload_hash`` in place of a
    link.
    """
    return await uploads.store(await _image_body(request))


@router.get("/{item_id}/{art_type}/sources")
async def get_art_sources(
    item_id: ItemIdPath,
    art_type: ArtTypePath,
    art: ArtDep,
    season_id: SeasonIdQuery = None,
) -> ArtSourcesResponse:
    """Fetch art options from TMDB and/or the configured media server."""
    return await art.get_sources(
        item_id=item_id,
        art_type=art_type,
        season_id=season_id,
    )


@router.post("/{item_id}/{art_type}/match")
async def match_art(
    item_id: ItemIdPath,
    art_type: ArtTypePath,
    art: ArtDep,
    season_id: SeasonIdQuery = None,
    threshold: Annotated[
        int, Query(ge=0, le=MATCH_THRESHOLD_MAX)
    ] = MATCH_THRESHOLD_DEFAULT,
) -> ArtMatchResponse:
    """Run pHash match for one slot."""
    return await art.match(
        item_id=item_id,
        art_type=art_type,
        season_id=season_id,
        threshold=threshold,
    )


@router.put("/{item_id}/{art_type}")
async def save_art(
    item_id: ItemIdPath,
    art_type: ArtTypePath,
    body: SaveArtRequest,
    art: ArtDep,
    season_id: SeasonIdQuery = None,
) -> ItemSelectionResponse:
    """Record the chosen artwork for one slot and enqueue its download.

    An item without a local folder only records the choice.
    """
    return await art.save(
        item_id=item_id,
        art_type=art_type,
        body=body,
        season_id=season_id,
    )


@router.delete("/{item_id}/{art_type}")
async def remove_art(
    item_id: ItemIdPath,
    art_type: ArtTypePath,
    removal: Annotated[AssetRemoval, Query()],
    art: ArtDep,
    season_id: Annotated[
        int | None,
        Query(description="The season; omit to remove every season's poster"),
    ] = None,
) -> StatusResponse:
    """Forget a slot's art, delete its local file or the server's copy."""
    return await art.remove(item_id, art_type, removal, season_id)


@router.delete("/{item_id}")
async def remove_all_art(
    item_id: ItemIdPath, removal: Annotated[AssetRemoval, Query()], art: ArtDep
) -> StatusResponse:
    """Remove every art slot of an item and its seasons."""
    return await art.remove(item_id, "art", removal)


@router.post("/removal-options")
async def get_removal_options(
    target: RemovalTarget, remover: RemoverDep
) -> RemovalOptions:
    """Say what each removal choice would change for items or collections."""
    return await remover.options(target)
