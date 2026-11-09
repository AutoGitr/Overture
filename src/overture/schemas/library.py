"""Library REST and WebSocket schemas."""

lazy from collections.abc import Mapping, Sequence
lazy from dataclasses import asdict
lazy from datetime import datetime
lazy from typing import Literal

lazy from pydantic import Field

lazy from ..db.art_slots import flattened_art, read_art_slot
lazy from ..db.completion import art_completion, slot_status, theme_status
lazy from ..db.models.art import ArtSlot
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.season import Season
lazy from ..domain import (
    ArtSource,
    ArtType,
    AssetStatus,
    BulkItemOperationKind,
    MediaType,
    ThemeIdSource,
)
lazy from ..utils.art_urls import art_preview_url
lazy from .base import StrictBaseModel
lazy from .common import SaveSelectionResponse


class MediaItemRead(StrictBaseModel):
    """Public media item response."""

    id: int
    media_type: MediaType
    title: str
    #: The media server's sort title, which leaves out leading articles in
    #: the library's language, or the one someone set there.
    sort_title: str | None = None
    year: int | None = None
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None
    #: The TMDB collection a movie belongs to.
    tmdb_collection_id: int | None = None
    library_collection_id: int | None = None
    folder_path: str | None = None
    server_item_id: str | None = None
    server_verified_at: datetime | None = None
    library_id: str | None = None
    monitored: bool = True
    directors: list[str] = Field(default_factory=list[str])
    studio: str | None = None

    # Artwork & Assets
    art_status: AssetStatus = AssetStatus.MISSING
    poster_status: AssetStatus = AssetStatus.MISSING
    background_status: AssetStatus = AssetStatus.MISSING
    season_posters_status: AssetStatus = AssetStatus.MISSING
    poster_url: str | None = None
    poster_preview_url: str | None = None
    poster_source: ArtSource | None = None
    poster_hash: str | None = None
    poster_phash: str | None = None
    poster_width: int | None = None
    poster_height: int | None = None
    background_url: str | None = None
    background_source: ArtSource | None = None
    background_hash: str | None = None
    background_phash: str | None = None
    background_width: int | None = None
    background_height: int | None = None
    has_incorrect_aspect_ratio: bool = False

    # Theme
    youtube_id: str | None = None
    youtube_id_source: ThemeIdSource | None = None
    #: OvertureDB says the title has no theme music, so none is missing.
    catalog_no_theme: bool = False
    #: The item's OvertureDB entry, which the catalog view opens.
    catalog_entry_key: str | None = None
    youtube_title: str | None = None
    youtube_duration: int | None = None
    theme_file_hash: str | None = None
    theme_duration: int | None = Field(
        default=None,
        description="Seconds: the local file's length, else the selected video's.",
    )
    theme_status: AssetStatus = AssetStatus.MISSING

    # Computed
    public_dataset_complete: bool = False
    public_dataset_themerrdb: bool = False
    public_dataset_ids: Literal["matching", "mismatching"] | None = Field(
        default=None,
        description=(
            "Whether the IDs the item and its OvertureDB entry both carry agree; "
            "null without an entry."
        ),
    )

    # Timestamps
    last_synced_at: datetime | None = None
    last_matched_at: datetime | None = None
    created_at: datetime | None = None
    server_added_at: datetime | None = None
    server_removed_at: datetime | None = None


class MediaItemListResponse(StrictBaseModel):
    """Library item list response."""

    items: list[MediaItemRead]
    total: int


class SeasonRead(StrictBaseModel):
    """Public season response."""

    id: int
    media_item_id: int
    season_num: int
    title: str | None = None
    file_count: int = 0
    folder_path: str | None = None
    server_item_id: str | None = None

    poster_status: AssetStatus = AssetStatus.MISSING
    poster_url: str | None = None
    poster_source: ArtSource | None = None
    poster_preview_url: str | None = None
    poster_hash: str | None = None
    poster_phash: str | None = None
    poster_width: int | None = None
    poster_height: int | None = None

    last_matched_at: datetime | None = None


class LibrarySectionRead(StrictBaseModel):
    """Library selector response."""

    id: str
    title: str
    media_type: MediaType
    count: int


class FolderRootsResponse(StrictBaseModel):
    """Trusted media folder roots derived from the local DB."""

    movies: list[str]
    shows: list[str]


def _preview_url(slot: ArtSlot, art_type: ArtType) -> str | None:
    """Return the smaller rendition of the slot's selected artwork, if any."""
    return slot.url and art_preview_url(slot.url, art_type)


def media_item_read_from_model(
    item: MediaItem,
    *,
    public_dataset_complete: bool = False,
    public_dataset_themerrdb: bool = False,
    seasons: Sequence[Season],
    directors: Sequence[str] = (),
    has_incorrect_aspect_ratio: bool = False,
    catalog_no_theme: bool = False,
    catalog_entry_key: str | None = None,
    public_dataset_ids: Literal["matching", "mismatching"] | None = None,
    library_collection_id: int | None = None,
) -> MediaItemRead:
    """Map a persisted media item to the public library item response.

    *seasons* are the item's tracked seasons, which a show's artwork status
    depends on, and *directors* a movie's; callers load both in bulk.
    """
    poster = read_art_slot(item, ArtType.POSTER)
    background = read_art_slot(item, ArtType.BACKGROUND)
    return MediaItemRead.model_validate(
        {
            # Item metadata stays internal: it serves collection criteria only.
            **item.model_dump(include=set(MediaItemRead.model_fields)),
            "directors": list(directors),
            **flattened_art(poster, "poster"),
            **flattened_art(background, "background"),
            # Only a remote poster is shown in place of a file, at preview size.
            "poster_preview_url": _preview_url(poster, ArtType.POSTER),
            **asdict(art_completion(item, seasons)),
            "theme_duration": item.theme_file_duration or item.youtube_duration,
            "theme_status": AssetStatus.COMPLETE
            if catalog_no_theme
            else theme_status(item),
            "catalog_no_theme": catalog_no_theme,
            "catalog_entry_key": catalog_entry_key,
            "public_dataset_complete": public_dataset_complete,
            "public_dataset_themerrdb": public_dataset_themerrdb,
            "library_collection_id": library_collection_id,
            "public_dataset_ids": public_dataset_ids,
            "has_incorrect_aspect_ratio": has_incorrect_aspect_ratio,
        }
    )


def season_read_from_model(season: Season, *, files: bool) -> SeasonRead:
    """Map a persisted season to the public season response.

    *files* tells whether the season's item holds local files.
    """
    poster = read_art_slot(season, ArtType.SEASON_POSTER)
    return SeasonRead.model_validate(
        {
            **season.model_dump(include=set(SeasonRead.model_fields)),
            "poster_status": slot_status(poster, files=files),
            **flattened_art(poster, "poster"),
            "poster_preview_url": _preview_url(poster, ArtType.SEASON_POSTER),
        }
    )


def folder_roots_response(roots: Mapping[str, Sequence[str]]) -> FolderRootsResponse:
    """Map repository folder root data to the public folder-root response."""
    return FolderRootsResponse(
        movies=list(roots.get("movies", [])),
        shows=list(roots.get("shows", [])),
    )


class BulkItemOperation(StrictBaseModel):
    """Apply an operation to item records."""

    item_ids: list[int]
    operation: BulkItemOperationKind


class BulkItemOperationResult(StrictBaseModel):
    """The items a bulk operation actually changed."""

    item_ids: list[int]
    operation: BulkItemOperationKind


class LibraryItemUpsertedEvent(StrictBaseModel):
    """WebSocket payload for visible item upserts."""

    item: MediaItemRead
    source: str | None = None


class LibraryItemRemovedEvent(StrictBaseModel):
    """WebSocket payload for visible item removals."""

    media_item_id: int
    media_type: MediaType | None = None
    source: str | None = None


class ItemUpdatedEvent(StrictBaseModel):
    """WebSocket payload requesting an item refresh."""

    media_item_id: int


class ItemSelectionResponse(StrictBaseModel):
    """A recorded selection and its updated item."""

    selection: SaveSelectionResponse
    item: MediaItemRead
