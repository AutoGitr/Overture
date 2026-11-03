"""Theme REST schemas."""

lazy from typing import Annotated

lazy from pydantic import Field

lazy from .base import StrictBaseModel
lazy from .validators import UniqueList, YouTubeId


class SearchRequest(StrictBaseModel):
    """A YouTube theme search: free text, explicit video IDs, or both."""

    query: str = ""
    limit: Annotated[int, Field(ge=1, le=50)] = 10
    video_ids: Annotated[UniqueList[YouTubeId], Field(max_length=20)] = Field(
        default_factory=list[str]
    )


class SelectThemeRequest(StrictBaseModel):
    """The chosen theme video; the item comes from the request path."""

    youtube_id: YouTubeId


class ThemeSearchResult(StrictBaseModel):
    """One theme search result."""

    id: str
    title: str
    channel: str | None = None
    duration: int | None = None
    thumbnail: str | None = None
    url: str | None = None


class ThemeSearchResponse(StrictBaseModel):
    """Theme search response."""

    results: list[ThemeSearchResult] = Field(default_factory=list[ThemeSearchResult])
