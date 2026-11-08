"""Term models - metadata values titles share, such as genres and people."""

lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, Index, Relationship, SQLModel, UniqueConstraint

lazy from ...domain import TermKind
lazy from ..columns import enum_type, typed_columns


class Term(SQLModel, table=True):
    """One value of one kind of metadata, such as the genre Action."""

    __tablename__: ClassVar[Any] = "terms"
    __table_args__ = (UniqueConstraint("kind", "name", name="uq_terms"),)

    id: int | None = Field(default=None, primary_key=True)
    kind: TermKind = Field(sa_type=enum_type(TermKind))
    name: str


class MediaItemTerm(SQLModel, table=True):
    """A value a title holds, in the order its server or TMDB lists them."""

    __tablename__: ClassVar[Any] = "media_item_terms"
    __table_args__ = (Index("ix_media_item_terms_term", "term_id"),)

    # Set from the item and the term when the link is saved.
    media_item_id: int | None = Field(
        default=None, foreign_key="media_items.id", ondelete="CASCADE", primary_key=True
    )
    term_id: int | None = Field(
        default=None, foreign_key="terms.id", ondelete="RESTRICT", primary_key=True
    )
    #: Where the value comes among the title's values of its kind.
    position: int = 0

    term: Term = Relationship(sa_relationship_kwargs={"lazy": "joined"})


typed_columns(Term)
