"""Columns several tables declare alike, declared once here."""

lazy from sqlmodel import Field, SQLModel

lazy from ...domain import (
    ArtStyle,
    AutoArt,
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
    auto_art: AutoArt | None = Field(default=None, sa_type=enum_type(AutoArt))
    drawn_style: ArtStyle | None = Field(default=None, sa_type=enum_type(ArtStyle))
    overturedb_posters: CollectionPosterStyle | None = Field(
        default=None, sa_type=enum_type(CollectionPosterStyle)
    )
    backgrounds: bool | None = None
    auto_match_theme: bool | None = None
    request_missing: bool | None = None
    member_label: str | None = None
    arr_tag: str | None = None
    home_order: int | None = None


class ThemeColumns(SQLModel):
    """The theme a title or collection has: its video and its local file.

    The file columns describe one inspection of the local theme file, and are
    written together through :mod:`overture.db.theme_file`.
    """

    youtube_id: str | None = None
    youtube_title: str | None = None
    #: Seconds, as YouTube gives the video's length.
    youtube_duration: int | None = None
    theme_file_hash: str | None = None
    theme_file_mtime_ns: int | None = None
    theme_file_size: int | None = None
    #: Seconds, read from the file at the revision above.
    theme_file_duration: int | None = None
