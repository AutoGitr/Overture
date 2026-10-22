"""Media server REST schemas."""

lazy from typing import Self

lazy from ..domain import MediaType
lazy from ..media_servers.adapters import ServerSection
lazy from .base import StrictBaseModel


class MediaServerErrorResponse(StrictBaseModel):
    """Provider failure, distinct from a successful empty library list."""

    detail: str


class ServerLibraryRead(StrictBaseModel):
    """One movie or show library on the media server."""

    key: str
    title: str
    media_type: MediaType

    @classmethod
    def from_section(cls, section: ServerSection) -> Self:
        """Return the public form of a provider library section."""
        return cls(key=section.key, title=section.title, media_type=section.media_type)
