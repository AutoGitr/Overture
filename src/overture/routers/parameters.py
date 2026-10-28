"""Shared FastAPI path, query, header, and cookie parameter types."""

lazy from typing import Annotated

lazy from fastapi import Cookie, Header, Path, Query

lazy from ..domain import ArtType, ImageSize, MediaType
lazy from ..utils.http_security import SESSION_COOKIE

ItemIdPath = Annotated[int, Path(description="Media item ID")]
CollectionIdPath = Annotated[int, Path(gt=0, description="Collection ID")]
SeasonIdPath = Annotated[int, Path(description="Season ID")]
SeasonIdQuery = Annotated[
    int | None,
    Query(description="Required for season_poster, ignored otherwise"),
]
ArtTypePath = Annotated[ArtType, Path(description="Which artwork slot")]
ScheduleIdPath = Annotated[int, Path(description="Saved schedule ID")]
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
    str | None,
    Cookie(alias=SESSION_COOKIE, description="Session token"),
]
ForwardedForHeader = Annotated[
    str | None,
    Header(alias="X-Forwarded-For", description="Forwarded client IP address"),
]
