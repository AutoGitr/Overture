"""Art router - sources, save, clear, match.

Every artwork operation acts on one slot, and a slot is named by the item, the
art type, and - for season artwork - the season. All three live in the request
line, so a body carries only what is being written.
"""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Query

lazy from ..dependencies import ArtDep
lazy from ..domain import MATCH_THRESHOLD_DEFAULT, MATCH_THRESHOLD_MAX
lazy from ..schemas.art import (
    ArtMatchResponse,
    ArtSourcesResponse,
    SaveArtRequest,
)
lazy from ..schemas.common import SaveSelectionResponse, StatusResponse
lazy from .auth import require_auth
lazy from .parameters import (
    ArtTypePath,
    ItemIdPath,
    SeasonIdQuery,
)

router = APIRouter(prefix="/art", tags=["art"], dependencies=[Depends(require_auth)])


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
) -> SaveSelectionResponse:
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
async def clear_art(
    item_id: ItemIdPath,
    art_type: ArtTypePath,
    art: ArtDep,
    season_id: Annotated[
        int | None,
        Query(description="The season to clear; omit to clear every season's poster"),
    ] = None,
) -> StatusResponse:
    """Forget a slot's selected artwork.

    A season poster without ``season_id`` forgets every season's.
    """
    return await art.clear(
        item_id=item_id,
        art_type=art_type,
        season_id=season_id,
    )


@router.delete("/{item_id}")
async def clear_all_art(
    item_id: ItemIdPath,
    art: ArtDep,
) -> StatusResponse:
    """Clear every artwork slot across an item tree."""
    return await art.clear_all(item_id)
