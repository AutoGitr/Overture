"""Database record REST schemas."""

lazy from collections.abc import Mapping, Sequence

lazy from pydantic import BaseModel, Field

lazy from ..db.art_slots import flattened_art_names
lazy from ..db.models.art import ArtSlot
lazy from ..domain import TermKind
lazy from ..utils.types import JsonValue
lazy from .base import StrictBaseModel


class StoredRow(StrictBaseModel):
    """One row exactly as its table stores it."""

    table: str
    values: dict[str, JsonValue]


class DatabaseRecord(StrictBaseModel):
    """A record as stored, and what the API derives from it.

    ``stored`` is the record's own row first, then every row that refers to
    it through a foreign key, and theirs in turn. ``derived`` holds what the
    API shows that no column stores, so not the fields copied from artwork rows.
    """

    stored: list[StoredRow]
    #: The metadata values a title holds, such as its genres, by kind.
    values: dict[str, list[str]] = Field(default_factory=dict[str, list[str]])
    derived: dict[str, JsonValue]

    @classmethod
    def of(
        cls,
        rows: Sequence[tuple[str, dict[str, JsonValue]]],
        read: BaseModel,
        values: Mapping[TermKind, list[str]] | None = None,
    ) -> DatabaseRecord:
        """The stored rows, and what *read* shows beyond the record's own columns."""
        stored = [StoredRow(table=table, values=values) for table, values in rows]
        shown = set(stored[0].values) if stored else set[str]()
        for row in stored:
            if row.table == ArtSlot.__tablename__:
                shown |= flattened_art_names(str(row.values["art_type"]))
        return cls(
            stored=stored,
            values={str(kind): names for kind, names in (values or {}).items()},
            derived={
                key: value
                for key, value in read.model_dump(mode="json").items()
                if key not in shown
            },
        )
