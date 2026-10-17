"""Library REST and WebSocket schemas."""

lazy from collections.abc import Mapping, Sequence
lazy from dataclasses import asdict
lazy from datetime import datetime
lazy from typing import Any, Literal

lazy from pydantic import field_validator

lazy from ..db.art_slots import read_art_slot
lazy from ..db.completion import art_completion, slot_status, theme_status
lazy from ..db.models.art import ArtSlot
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.public_dataset import PublicDatasetItem
lazy from ..db.models.season import Season
lazy from ..domain import ArtSource, ArtType, AssetStatus, MediaType, ThemeIdSource
lazy from ..utils.art_urls import art_preview_url, selected_art_source
lazy from ..utils.security import strip_sensitive_url
lazy from .base import StrictBaseModel


class MediaItemRead(StrictBaseModel):
    """Public media item response."""

    id: int
    media_type: MediaType
    title: str
    year: int | None = None
    tmdb_id: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None
    folder_path: str | None = None
    server_item_id: str | None = None
    server_link: str | None = None
    server_verified_at: datetime | None = None
    library_id: str | None = None
    monitored: bool = True
    director: str | None = None
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
    youtube_title: str | None = None
    youtube_duration: int | None = None
    theme_file_hash: str | None = None
    theme_status: AssetStatus = AssetStatus.MISSING

    # Computed
    public_dataset_complete: bool = False
    public_dataset_themerrdb: bool = False

    # Timestamps
    last_synced_at: datetime | None = None
    last_matched_at: datetime | None = None
    created_at: datetime | None = None
    server_added_at: datetime | None = None
    server_removed_at: datetime | None = None

    @field_validator("poster_url", "background_url")
    @classmethod
    def hide_sensitive_urls(cls, url: str | None) -> str | None:
        """Withhold URLs whose query carries credentials."""
        return strip_sensitive_url(url)


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
    poster_preview_url: str | None = None
    poster_hash: str | None = None
    poster_phash: str | None = None
    poster_width: int | None = None
    poster_height: int | None = None

    last_matched_at: datetime | None = None

    @field_validator("poster_url")
    @classmethod
    def hide_sensitive_urls(cls, url: str | None) -> str | None:
        """Withhold URLs whose query carries credentials."""
        return strip_sensitive_url(url)


class LibrarySectionRead(StrictBaseModel):
    """Library selector response."""

    id: str
    title: str
    count: int


class FolderRootsResponse(StrictBaseModel):
    """Trusted media folder roots derived from the local DB."""

    movies: list[str]
    shows: list[str]


def _art_slot_fields(slot: ArtSlot, prefix: str) -> dict[str, Any]:
    """Flatten one artwork slot into the ``<prefix>_*`` response fields.

    The public contract still exposes artwork as flat, prefixed fields even
    though storage is normalized, so the prefix is applied here in one place
    instead of being re-derived by every caller.
    """
    return {
        f"{prefix}_url": slot.url,
        f"{prefix}_hash": slot.file_hash,
        f"{prefix}_phash": slot.phash,
        f"{prefix}_width": slot.width,
        f"{prefix}_height": slot.height,
    }


def _preview_url(slot: ArtSlot, art_type: ArtType) -> str | None:
    """Return the smaller rendition of the slot's selected artwork, if any."""
    return slot.url and art_preview_url(slot.url, art_type)


def media_item_read_from_model(
    item: MediaItem,
    *,
    public_item: PublicDatasetItem | None = None,
    public_dataset_complete: bool = False,
    public_dataset_themerrdb: bool = False,
    seasons: Sequence[Season],
    has_incorrect_aspect_ratio: bool = False,
) -> MediaItemRead:
    """Map a persisted media item to the public library item response.

    *public_item* is the item's OvertureDB entry, which artwork sources are
    told against. *seasons* are the item's tracked seasons, which a show's
    artwork status depends on; callers load both in bulk.
    """
    poster = read_art_slot(item, ArtType.POSTER)
    background = read_art_slot(item, ArtType.BACKGROUND)
    return MediaItemRead.model_validate(
        {
            **item.model_dump(
                exclude={
                    "director_etag",
                    "theme_file_mtime_ns",
                    "theme_file_size",
                    "theme_provenance_cleared",
                }
            ),
            **_art_slot_fields(poster, "poster"),
            **_art_slot_fields(background, "background"),
            # Only a remote poster is shown in place of a file, at preview size.
            "poster_preview_url": _preview_url(poster, ArtType.POSTER),
            "poster_source": selected_art_source(
                poster.url, public_item and public_item.poster_url
            ),
            "background_source": selected_art_source(
                background.url, public_item and public_item.background_url
            ),
            **asdict(art_completion(item, seasons)),
            "theme_status": theme_status(item),
            "public_dataset_complete": public_dataset_complete,
            "public_dataset_themerrdb": public_dataset_themerrdb,
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
            **season.model_dump(),
            "poster_status": slot_status(poster, files=files),
            **_art_slot_fields(poster, "poster"),
            "poster_preview_url": _preview_url(poster, ArtType.SEASON_POSTER),
        }
    )


def folder_roots_response(roots: Mapping[str, Sequence[str]]) -> FolderRootsResponse:
    """Map repository folder root data to the public folder-root response."""
    return FolderRootsResponse(
        movies=list(roots.get("movies", [])),
        shows=list(roots.get("shows", [])),
    )


#: What a bulk operation changes on item records.
type BulkItemOperationKind = Literal[
    "artwork", "themes", "delete", "monitor", "unmonitor"
]


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
