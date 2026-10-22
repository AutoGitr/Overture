"""TMDB search and unsaved-item REST schemas."""

lazy from collections.abc import Mapping
lazy from typing import Annotated, Literal

lazy from pydantic import Field

lazy from ..domain import ArtType, MediaType
lazy from ..integrations.tmdb import TmdbCollection, TmdbDetails, TmdbTitle
lazy from ..utils.art_urls import art_preview_url
lazy from .base import StrictBaseModel


class TmdbItemResult(StrictBaseModel):
    """A movie or show TMDB found."""

    kind: Literal["item"] = "item"
    media_type: MediaType
    tmdb_id: int
    title: str
    year: int | None = None
    poster_url: str | None = None
    poster_preview_url: str | None = None
    #: The stored item with this TMDB ID, which opens instead.
    existing_item_id: int | None = None


class TmdbCollectionResult(StrictBaseModel):
    """A TMDB collection, which expands into its movies."""

    kind: Literal["collection"] = "collection"
    tmdb_id: int
    title: str
    poster_url: str | None = None
    poster_preview_url: str | None = None


type TmdbSearchResult = Annotated[
    TmdbItemResult | TmdbCollectionResult, Field(discriminator="kind")
]


class TmdbSearchResponse(StrictBaseModel):
    """TMDB search results: movies or shows first, then collections."""

    results: list[TmdbSearchResult]


class TmdbCollectionResponse(StrictBaseModel):
    """A TMDB collection with its movies."""

    tmdb_id: int
    title: str
    items: list[TmdbItemResult]


class TmdbSeasonPreview(StrictBaseModel):
    """One season of an unsaved show."""

    season_num: int
    title: str | None = None
    poster_url: str | None = None
    poster_preview_url: str | None = None


class TmdbItemPreview(StrictBaseModel):
    """A movie or show as TMDB describes it, before anything is saved.

    Field names match :class:`MediaItemRead`, so the item view reads both.
    """

    media_type: MediaType
    tmdb_id: int
    title: str
    year: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None
    poster_url: str | None = None
    poster_preview_url: str | None = None
    background_url: str | None = None
    seasons: list[TmdbSeasonPreview]
    #: The stored item matching these IDs, which opens instead.
    existing_item_id: int | None = None


def _preview(url: str | None, art_type: ArtType) -> str | None:
    return url and art_preview_url(url, art_type)


def tmdb_item_result(
    media_type: MediaType, title: TmdbTitle, existing_item_id: int | None
) -> TmdbItemResult:
    """Map a TMDB movie or show to its search result."""
    return TmdbItemResult(
        media_type=media_type,
        tmdb_id=title.tmdb_id,
        title=title.title,
        year=title.year,
        poster_url=title.poster_url,
        poster_preview_url=_preview(title.poster_url, ArtType.POSTER),
        existing_item_id=existing_item_id,
    )


def tmdb_collection_result(title: TmdbTitle) -> TmdbCollectionResult:
    """Map a TMDB collection to its search result."""
    return TmdbCollectionResult(
        tmdb_id=title.tmdb_id,
        title=title.title,
        poster_url=title.poster_url,
        poster_preview_url=_preview(title.poster_url, ArtType.POSTER),
    )


def tmdb_collection_response(
    collection: TmdbCollection, existing_item_ids: Mapping[int, int]
) -> TmdbCollectionResponse:
    """Map a collection to its response, oldest movie first."""
    parts = sorted(
        collection.parts, key=lambda part: (part.release_date or "9999", part.title)
    )
    return TmdbCollectionResponse(
        tmdb_id=collection.tmdb_id,
        title=collection.title,
        items=[
            tmdb_item_result(MediaType.MOVIE, part, existing_item_ids.get(part.tmdb_id))
            for part in parts
        ],
    )


def tmdb_item_preview(
    details: TmdbDetails, existing_item_id: int | None
) -> TmdbItemPreview:
    """Map TMDB details to the unsaved item's preview."""
    return TmdbItemPreview(
        media_type=details.media_type,
        tmdb_id=details.tmdb_id,
        title=details.title,
        year=details.year,
        tvdb_id=details.tvdb_id,
        imdb_id=details.imdb_id,
        poster_url=details.poster_url,
        poster_preview_url=_preview(details.poster_url, ArtType.POSTER),
        background_url=details.background_url,
        seasons=[
            TmdbSeasonPreview(
                season_num=season.season_num,
                title=season.title,
                poster_url=season.poster_url,
                poster_preview_url=_preview(season.poster_url, ArtType.SEASON_POSTER),
            )
            for season in details.tracked_seasons
        ],
        existing_item_id=existing_item_id,
    )
