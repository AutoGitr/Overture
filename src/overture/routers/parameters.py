"""Shared FastAPI path, query, header, and cookie parameter types."""

lazy from typing import Annotated, Any

lazy from fastapi import Cookie, Header, Path, Query
lazy from pydantic import SecretStr

lazy from ..domain import MAX_SAFE_INTEGER, ArtType, ImageSize, MediaType
lazy from ..utils.http_security import API_KEY_HEADER, SESSION_COOKIE


def _id_path(description: str) -> Any:
    """A path parameter naming a row, or a TMDB record a row stores."""
    return Path(gt=0, le=MAX_SAFE_INTEGER, description=description)


ItemIdPath = Annotated[int, _id_path("Media item ID")]
CollectionIdPath = Annotated[int, _id_path("Collection ID")]
SeasonIdPath = Annotated[int, _id_path("Season ID")]
SavedFilterIdPath = Annotated[int, _id_path("Saved filter ID")]
ApiKeyIdPath = Annotated[int, _id_path("API key ID")]
TmdbIdPath = Annotated[int, _id_path("TMDB ID")]
TmdbCollectionIdPath = Annotated[int, _id_path("TMDB collection ID")]

SeasonIdQuery = Annotated[
    int | None,
    Query(
        gt=0,
        le=MAX_SAFE_INTEGER,
        description="Required for season_poster, ignored otherwise",
    ),
]
ArtTypePath = Annotated[ArtType, Path(description="Which artwork slot")]
ScheduleIdPath = Annotated[int, _id_path("Saved schedule ID")]
ImageSizeQuery = Annotated[
    ImageSize | None,
    Query(description="Downscaled rendition to return; omit for the original"),
]
ImageVersionQuery = Annotated[
    str | None,
    Query(
        alias="t",
        description="The artwork hash the client shows; a current one is cacheable",
    ),
]
ImageCacheKeyQuery = Annotated[
    str | None,
    Query(
        alias="t",
        description=(
            "Changes whenever the shown image does, so a cached copy is never"
            " reused for another; the server does not read it"
        ),
    ),
]
MediaTypePath = Annotated[
    MediaType,
    Path(description="Media type ('movie' or 'show')"),
]
MediaTypeQuery = Annotated[
    MediaType,
    Query(description="Media type ('movie' or 'show')"),
]
AuthTokenCookie = Annotated[
    SecretStr | None,
    Cookie(alias=SESSION_COOKIE, description="Session token"),
]
ForwardedForHeader = Annotated[
    str | None,
    Header(alias="X-Forwarded-For", description="Forwarded client IP address"),
]
ApiKeyHeader = Annotated[
    SecretStr | None,
    Header(alias=API_KEY_HEADER, description="Read-only API key"),
]
