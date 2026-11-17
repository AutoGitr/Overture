"""Media server REST schemas."""

lazy from typing import Self

lazy from ..domain import MediaServerState, MediaType, ServerType
lazy from ..media_servers.adapters import ServerSection
lazy from ..media_servers.health import MediaServerHealth
lazy from .base import PublicText, StrictBaseModel


class MediaServerErrorResponse(StrictBaseModel):
    """Provider failure, distinct from a successful empty library list."""

    detail: PublicText


class ServerLibraryRead(StrictBaseModel):
    """One movie or show library on a media server."""

    #: Overture's ID of the library, which names its server as well.
    key: str
    title: str
    media_type: MediaType
    #: The database's number of its server.
    server_id: int

    @classmethod
    def from_section(cls, section: ServerSection, server_id: int) -> Self:
        """Return the public form of a provider library section."""
        return cls(
            key=section.library_id,
            title=section.title,
            media_type=section.media_type,
            server_id=server_id,
        )


class MediaServerRead(StrictBaseModel):
    """One media server MEDIA_SERVERS configures, the lead first."""

    #: The database's number of the server, which library IDs carry.
    id: int
    #: Its name in MEDIA_SERVERS, as shown to users.
    title: str
    type: ServerType
    #: It has collections Overture can manage.
    collections: bool


class ServerWebLinksRead(StrictBaseModel):
    """Where one server's web app opens an item or a collection.

    ``{id}`` in each stands for the item's or collection's server ID.
    """

    #: The database's number of the server.
    server_id: int
    item: str
    collection: str


class MediaServerStatus(StrictBaseModel):
    """Whether one media server answered Overture's last request."""

    #: The database's number of the server.
    server_id: int
    #: Its name in MEDIA_SERVERS, as shown to users.
    title: str
    state: MediaServerState = MediaServerState.UNKNOWN
    #: What the person running Overture can do about it, while it is down.
    message: PublicText = ""


def media_server_status(
    server_id: int, title: str, health: MediaServerHealth
) -> MediaServerStatus:
    """Return the public form of one media server's health."""
    return MediaServerStatus(
        server_id=server_id, title=title, state=health.state, message=health.message
    )
