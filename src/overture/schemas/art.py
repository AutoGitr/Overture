"""Artwork REST schemas."""

lazy from typing import Literal, Self

lazy from pydantic import Field, model_validator

lazy from ..domain import ArtGeneration, ArtStyle, ArtType
lazy from .base import PublicText, StrictBaseModel
lazy from .validators import ImageHash


class SaveArtRequest(StrictBaseModel):
    """The chosen artwork for one slot: a link, an uploaded image or one to generate.

    Which slot it is comes from the request path and query, so the body only
    carries the picture itself.
    """

    url: str | None = None
    #: An image ``POST /api/art/uploads`` kept, by the hash it returned.
    upload_hash: ImageHash | None = None
    #: Art Overture generates in this style from a collection's title.
    generated: ArtStyle | None = None
    #: Generate a poster with the title alone, without its group.
    title_only: bool = False
    width: int | None = None
    height: int | None = None

    @property
    def generation(self) -> ArtGeneration | None:
        """How to generate the art, when it is art to generate."""
        if self.generated is None:
            return None
        return ArtGeneration(self.generated, title_only=self.title_only)

    @model_validator(mode="after")
    def validate_source(self) -> Self:
        """Require exactly one of a link, an upload and a style to generate."""
        chosen = (self.url, self.upload_hash, self.generated)
        if sum(value is not None for value in chosen) != 1:
            raise ValueError("Choose a link, an uploaded image or a generated style")
        if self.title_only and self.generated is None:
            raise ValueError("Only generated art can show the title alone")
        return self


class ArtUploadResponse(StrictBaseModel):
    """An uploaded image, kept until a slot selects it."""

    upload_hash: ImageHash
    width: int
    height: int


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
    #: Choosing it generates the art in this style; *url* shows what it looks like.
    generated: ArtStyle | None = None
    #: Choosing it generates a poster with the title alone, without its group.
    title_only: bool = False

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
    reason: PublicText | None = None
    errors: list[PublicText] = Field(default_factory=list[PublicText])
    failed: int = 0
