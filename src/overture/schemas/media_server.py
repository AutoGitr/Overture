"""Media server REST schemas."""

lazy from typing import Self

lazy from ..domain import MediaServerState, MediaType
lazy from ..media_servers.adapters import ServerSection
lazy from ..media_servers.health import MediaServerHealth
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


class MediaServerStatus(StrictBaseModel):
    """Whether the media server answered Overture's last request."""

    state: MediaServerState = MediaServerState.UNKNOWN
    #: What the person running Overture can do about it, while it is down.
    message: str = ""


def media_server_status(health: MediaServerHealth) -> MediaServerStatus:
    """Return the public form of the media server's health."""
    return MediaServerStatus(state=health.state, message=health.message)
