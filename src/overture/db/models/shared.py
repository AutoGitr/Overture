"""Columns several tables declare alike, declared once here."""

lazy from sqlmodel import JSON, Field, SQLModel

lazy from ...domain import (
    ArtStyle,
    AutoArtSource,
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    CollectionPosterStyle,
    SyncMode,
)
lazy from ..columns import enum_type


class PolicyOverrides(SQLModel):
    """A group's or a collection's choices; ``None`` inherits the next tier's."""

    sync_mode: SyncMode | None = Field(default=None, sa_type=enum_type(SyncMode))
    minimum_items: int | None = None
    delete_below_minimum: bool | None = None
    collection_mode: CollectionMode | None = Field(
        default=None, sa_type=enum_type(CollectionMode)
    )
    order_type: CollectionOrder | None = Field(
        default=None, sa_type=enum_type(CollectionOrder)
    )
    collection_filtering: CollectionFiltering | None = Field(
        default=None, sa_type=enum_type(CollectionFiltering)
    )
    visible_home: bool | None = None
    visible_shared: bool | None = None
    visible_library: bool | None = None
    sort_title_format: str | None = None
    summary_format: str | None = None
    active_start_mmdd: str | None = None
    active_end_mmdd: str | None = None
    delete_when_inactive: bool | None = None
    #: The sources Automatic art tries, first to last; empty turns it off.
    auto_art: list[AutoArtSource] | None = Field(default=None, sa_type=JSON)
    generated_style: ArtStyle | None = Field(default=None, sa_type=enum_type(ArtStyle))
    #: Generated posters show the collection's title alone, without its group.
    generated_title_only: bool | None = None
    #: The OvertureDB poster styles taken, first to last; empty takes none.
    overturedb_posters: list[CollectionPosterStyle] | None = Field(
        default=None, sa_type=JSON
    )
    backgrounds: bool | None = None
    themes: bool | None = None
    auto_match_theme: bool | None = None
    request_missing: bool | None = None
    member_label: str | None = None
    arr_tag: str | None = None
    home_order: int | None = None
