"""Themes router - YouTube search, selection and removal."""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Query

lazy from ..dependencies import ThemesDep
lazy from ..schemas.common import StatusResponse
lazy from ..schemas.library import ItemSelectionResponse
lazy from ..schemas.removal import AssetRemoval
lazy from ..schemas.themes import SearchRequest, SelectThemeRequest, ThemeSearchResponse
lazy from .auth import require_auth
lazy from .parameters import ItemIdPath

router = APIRouter(
    prefix="/themes", tags=["themes"], dependencies=[Depends(require_auth)]
)


@router.get("/search")
async def search_youtube(
    params: Annotated[SearchRequest, Query()], themes: ThemesDep
) -> ThemeSearchResponse:
    """Search YouTube for theme music, filtered by configured duration limits."""
    return await themes.search(params)


@router.put("/{item_id}")
async def select_theme(
    item_id: ItemIdPath, body: SelectThemeRequest, themes: ThemesDep
) -> ItemSelectionResponse:
    """Select an item's theme and download it.

    An item without a local folder only records the choice.
    """
    return await themes.select(item_id, body.youtube_id)


@router.delete("/{item_id}")
async def remove_theme(
    item_id: ItemIdPath,
    removal: Annotated[AssetRemoval, Query()],
    themes: ThemesDep,
) -> StatusResponse:
    """Forget an item's theme, delete its local file or the server's copy."""
    return await themes.remove(item_id, removal)
