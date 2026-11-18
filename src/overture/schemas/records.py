"""Database record REST schemas."""

lazy from collections.abc import Mapping, Sequence

lazy from pydantic import BaseModel, Field

lazy from ..db.art_slots import flattened_art_names
lazy from ..db.models.art import ArtSlot
lazy from ..db.models.media_collection import CollectionLibrary
lazy from ..db.models.media_item_copy import MediaItemCopy
lazy from ..db.models.season import Season
lazy from ..domain import ArtType, TermKind
lazy from ..utils.types import JsonValue
lazy from .base import StrictBaseModel


class StoredRow(StrictBaseModel):
    """One row exactly as its table stores it."""

    table: str
    #: What the row holds, such as "Background" or "Season 2".
    title: str
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
        *,
        libraries: Mapping[str, str],
    ) -> DatabaseRecord:
        """The stored rows, and what *read* shows beyond the record's own columns.

        *libraries* names each library a row is in, by its ID.
        """
        season_nums = {
            values["id"]: values["season_num"]
            for table, values in rows
            if table == Season.__tablename__
        }
        stored = [
            StoredRow(
                table=table,
                title=_title(table, values, season_nums, libraries),
                values=values,
            )
            for table, values in rows
        ]
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


def _title(
    table: str,
    values: dict[str, JsonValue],
    season_nums: dict[JsonValue, JsonValue],
    libraries: Mapping[str, str],
) -> str:
    """Name a stored row by what it holds, or by its table and key."""
    if table in {MediaItemCopy.__tablename__, CollectionLibrary.__tablename__}:
        library = str(values["library_id"])
        return f"Copy in {libraries.get(library, library)}"
    if table == Season.__tablename__:
        return f"Season {values['season_num']}"
    if table == ArtSlot.__tablename__:
        label = ArtType(str(values["art_type"])).label.capitalize()
        season = season_nums.get(values["season_id"])
        return label if season is None else f"Season {season} poster"
    key = values.get("id")
    return table if key is None else f"{table} {key}"
