"""TMDB router - search, and items that are stored on their first selection.

An unsaved item is named by its media type and TMDB ID. Its first art or theme
selection stores it; from then on the item routes take over.
"""

lazy from typing import Annotated

lazy from fastapi import APIRouter, Depends, Path, Query

lazy from ..dependencies import TmdbItemsDep
lazy from ..schemas.art import ArtSourcesResponse, SaveArtRequest
lazy from ..schemas.public_dataset import PublicDatasetSources
lazy from ..schemas.themes import SelectThemeRequest
lazy from ..schemas.tmdb import (
    TmdbCollectionResponse,
    TmdbItemPreview,
    TmdbSearchResponse,
    TmdbSelectionResponse,
)
lazy from .auth import require_auth
lazy from .parameters import ArtTypePath, MediaTypePath, MediaTypeQuery

router = APIRouter(prefix="/tmdb", tags=["tmdb"], dependencies=[Depends(require_auth)])

TmdbIdPath = Annotated[int, Path(gt=0, description="TMDB ID")]
SeasonNumQuery = Annotated[
    int | None,
    Query(ge=0, description="Required for season_poster, ignored otherwise"),
]


@router.get("/search")
async def search_tmdb(
    media_type: MediaTypeQuery,
    query: Annotated[str, Query(min_length=1, max_length=200)],
    tmdb_items: TmdbItemsDep,
) -> TmdbSearchResponse:
    """Search TMDB by title; a number is also looked up as a TMDB ID."""
    return await tmdb_items.search(media_type, query)


@router.get("/collections/{collection_id}")
async def get_tmdb_collection(
    collection_id: Annotated[int, Path(gt=0, description="TMDB collection ID")],
    tmdb_items: TmdbItemsDep,
) -> TmdbCollectionResponse:
    """List the movies of a TMDB collection."""
    return await tmdb_items.collection(collection_id)


@router.get("/{media_type}/{tmdb_id}")
async def get_tmdb_item(
    media_type: MediaTypePath,
    tmdb_id: TmdbIdPath,
    tmdb_items: TmdbItemsDep,
) -> TmdbItemPreview:
    """Describe a TMDB movie or show, naming the stored item it matches."""
    return await tmdb_items.preview(media_type, tmdb_id)


@router.get("/{media_type}/{tmdb_id}/art/{art_type}/sources")
async def get_tmdb_art_sources(
    media_type: MediaTypePath,
    tmdb_id: TmdbIdPath,
    art_type: ArtTypePath,
    tmdb_items: TmdbItemsDep,
    season_num: SeasonNumQuery = None,
) -> ArtSourcesResponse:
    """Fetch artwork options for one slot of an unsaved item."""
    return await tmdb_items.art_sources(media_type, tmdb_id, art_type, season_num)


@router.get("/{media_type}/{tmdb_id}/public-dataset")
async def get_tmdb_public_dataset_sources(
    media_type: MediaTypePath,
    tmdb_id: TmdbIdPath,
    tmdb_items: TmdbItemsDep,
) -> PublicDatasetSources:
    """Look up what OvertureDB holds for an unsaved item."""
    return await tmdb_items.public_dataset_sources(media_type, tmdb_id)


@router.put("/{media_type}/{tmdb_id}/art/{art_type}")
async def save_tmdb_art(
    media_type: MediaTypePath,
    tmdb_id: TmdbIdPath,
    art_type: ArtTypePath,
    body: SaveArtRequest,
    tmdb_items: TmdbItemsDep,
    season_num: SeasonNumQuery = None,
) -> TmdbSelectionResponse:
    """Record artwork for a TMDB item, storing the item if it is new."""
    return await tmdb_items.save_art(media_type, tmdb_id, art_type, season_num, body)


@router.put("/{media_type}/{tmdb_id}/theme")
async def select_tmdb_theme(
    media_type: MediaTypePath,
    tmdb_id: TmdbIdPath,
    body: SelectThemeRequest,
    tmdb_items: TmdbItemsDep,
) -> TmdbSelectionResponse:
    """Record a theme for a TMDB item, storing the item if it is new."""
    return await tmdb_items.select_theme(media_type, tmdb_id, body)
