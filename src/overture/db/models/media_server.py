"""MediaServer model - the media servers Overture talks to or has talked to."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, Index, SQLModel, text

lazy from ...domain import ServerType
lazy from ..columns import enum_type, typed_columns


class MediaServer(SQLModel, table=True):
    """A media server MEDIA_SERVERS names, or named before.

    Its number is what library IDs and copies refer to, so renaming a server
    or reordering MEDIA_SERVERS leaves everything it holds in place.
    """

    __tablename__: ClassVar[Any] = "media_servers"
    __table_args__ = (
        Index(
            "uq_media_servers_key",
            "key",
            unique=True,
            sqlite_where=text("key IS NOT NULL"),
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    #: Its name in MEDIA_SERVERS, lower-cased; none once another server at
    #: another address took the name.
    key: str | None = None
    title: str
    #: None for the server an upgrade found, until MEDIA_SERVERS names it.
    server_type: ServerType | None = Field(default=None, sa_type=enum_type(ServerType))
    #: Its kind and address, by which a renamed server is recognised.
    identity: str = Field(index=True)
    #: Its place in MEDIA_SERVERS, the lead 0; none while it is not named there.
    position: int | None = None
    #: When it left MEDIA_SERVERS; what it held waits for its return.
    removed_at: datetime | None = None


typed_columns(MediaServer)
