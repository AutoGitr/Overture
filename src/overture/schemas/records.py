"""Database record REST schemas."""

lazy from pydantic import BaseModel

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
    API shows that no column stores.
    """

    stored: list[StoredRow]
    derived: dict[str, JsonValue]

    @classmethod
    def of(cls, stored: list[StoredRow], read: BaseModel) -> DatabaseRecord:
        """The stored rows, and what *read* shows beyond the record's own columns."""
        columns = stored[0].values.keys() if stored else set[str]()
        return cls(
            stored=stored,
            derived={
                key: value
                for key, value in read.model_dump(mode="json").items()
                if key not in columns
            },
        )
