"""Library model - the media server's movie and show libraries."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, Index, SQLModel, text

lazy from ...domain import MediaType
lazy from ..columns import enum_type, typed_columns


class Library(SQLModel, table=True):
    """One of the media server's movie or show libraries, as syncs list them."""

    __tablename__: ClassVar[Any] = "libraries"
    __table_args__ = (
        # The server lists each key once, whatever it held before.
        Index(
            "uq_libraries_listed",
            "id",
            unique=True,
            sqlite_where=text("removed_at IS NULL"),
        ),
    )

    #: The media server's key for the library. Another server may use the
    #: same key for a library of the other type, which is another library.
    id: str = Field(primary_key=True)
    #: Part of the key items and collections reference, so each holds only
    #: titles of the library's type.
    media_type: MediaType = Field(sa_type=enum_type(MediaType), primary_key=True)
    title: str
    #: When a sync last found it missing from the server; its items and
    #: collections keep referencing it.
    removed_at: datetime | None = None


typed_columns(Library)
