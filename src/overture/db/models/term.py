"""Term models - metadata values titles share, such as genres and people."""

lazy from typing import Any, ClassVar

lazy from sqlmodel import (
    Field,
    ForeignKeyConstraint,
    Index,
    SQLModel,
    UniqueConstraint,
)

lazy from ...domain import TermKind
lazy from ..columns import enum_type, typed_columns


class Term(SQLModel, table=True):
    """One value of one kind of metadata, such as the genre Action."""

    __tablename__: ClassVar[Any] = "terms"
    __table_args__ = (
        UniqueConstraint("kind", "name", name="uq_terms"),
        # What a link's foreign key references, so it cannot state another kind.
        Index("uq_terms_id_kind", "id", "kind", unique=True),
    )

    id: int | None = Field(default=None, primary_key=True)
    kind: TermKind = Field(sa_type=enum_type(TermKind))
    name: str


class MediaItemTerm(SQLModel, table=True):
    """A value a title holds, in the order its server or TMDB lists them.

    The key clusters a title's values by kind and in order, so reading one
    kind never visits the title's others; a title can hold dozens of people.
    The index answers which titles hold a term from the index alone.
    """

    __tablename__: ClassVar[Any] = "media_item_terms"
    __table_args__ = (
        ForeignKeyConstraint(
            ["term_id", "kind"],
            ["terms.id", "terms.kind"],
            ondelete="RESTRICT",
            name="fk_media_item_terms_term",
        ),
        Index("uq_media_item_terms_term", "term_id", "media_item_id", unique=True),
        {"sqlite_with_rowid": False},
    )

    media_item_id: int = Field(
        foreign_key="media_items.id", ondelete="CASCADE", primary_key=True
    )
    kind: TermKind = Field(sa_type=enum_type(TermKind), primary_key=True)
    #: Where the value comes among the title's values of its kind.
    position: int = Field(primary_key=True)
    term_id: int


typed_columns(Term)
typed_columns(MediaItemTerm)
