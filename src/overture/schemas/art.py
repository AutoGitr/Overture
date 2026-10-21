"""Artwork REST schemas."""

lazy from typing import Literal

lazy from pydantic import Field

lazy from ..domain import ArtType
lazy from .base import StrictBaseModel


class SaveArtRequest(StrictBaseModel):
    """The chosen artwork for one slot.

    Which slot it is comes from the request path and query, so the body only
    carries the picture itself.
    """

    url: str
    width: int | None = None
    height: int | None = None


class ArtCandidate(StrictBaseModel):
    """One artwork option, from TMDB, the media server or OvertureDB.

    A matched candidate also carries its pHash distance from the reference
    image, and whether its original bytes equal the local file.
    """

    url: str
    preview_url: str | None = None
    width: int | None = None
    height: int | None = None
    iso_639_1: str | None = None
    source: str | None = None
    title: str | None = None
    art_type: ArtType | None = None
    hamming: int | None = None
    perfect_match: bool | None = None

    @property
    def area(self) -> int:
        """Return the image's pixel count, ``0`` when its size is unknown."""
        return (self.width or 0) * (self.height or 0)


#: What a match compared candidates against: the local file, the media
#: server's current image, or the saved URL.
type MatchReference = Literal["local_file", "media_server", "saved_url"]


class ArtSourcesResponse(StrictBaseModel):
    """Artwork source response."""

    sources: dict[str, list[ArtCandidate]] = Field(default_factory=dict)
    current_url: str | None = None


class ArtMatchResponse(StrictBaseModel):
    """Artwork match response."""

    matches: list[ArtCandidate] = Field(default_factory=list[ArtCandidate])
    total_compared: int = 0
    prefiltered: int = 0
    reference: MatchReference | None = None
    reason: str | None = None
    errors: list[str] = Field(default_factory=list)
    failed: int = 0
