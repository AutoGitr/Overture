"""Library REST and WebSocket schemas."""

lazy from collections.abc import Mapping, Sequence
lazy from datetime import datetime
lazy from typing import Literal

lazy from pydantic import Field

lazy from ..db.ledger import item_art_status, read_asset
lazy from ..db.models.media_item import MediaItem
lazy from ..db.models.season import Season
lazy from ..domain import (
    AssetStatus,
    BulkItemOperationKind,
    MediaType,
    MetadataIssue,
    ServerAsset,
)
lazy from .assets import AssetRead, TitleAssets, asset_read, assets_read
lazy from .base import PositiveId, PublicText, StrictBaseModel
lazy from .catalog import CatalogSelections
lazy from .common import SaveSelectionResponse
lazy from .removal import AssetRemoval
lazy from .validators import UniqueList


class ItemCopyRead(StrictBaseModel):
    """One media server's copy of a title, which that server lists."""

    #: The database's number of the server.
    server_id: int
    #: The server's own ID of the title, which its web app opens.
    server_item_id: str
    library_id: str


class MediaItemRead(StrictBaseModel):
    """Public media item response."""

    id: int
    media_type: MediaType
    title: str
    #: The lead server's sort title, which leaves out leading articles in
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
    #: The copies the configured servers list, in no particular order.
    copies: list[ItemCopyRead] = Field(default_factory=list[ItemCopyRead])
    monitored: bool = True
    directors: list[str] = Field(default_factory=list[str])
    studio: str | None = None

    #: The poster, background and theme.
    assets: TitleAssets
    #: The poster, background and, for a show, every tracked season's poster,
    #: taken together.
    art_status: AssetStatus = AssetStatus.MISSING
    #: Every tracked season's poster taken together; a show without one is
    #: missing them.
    season_posters_status: AssetStatus = AssetStatus.MISSING
    has_incorrect_aspect_ratio: bool = False
    #: The item's OvertureDB entry, which the catalog view opens.
    catalog_entry_key: str | None = None

    # Computed
    catalog_complete: bool = False
    catalog_themerrdb: bool = False
    catalog_ids: Literal["matching", "mismatching"] | None = Field(
        default=None,
        description=(
            "Whether the IDs the item and its OvertureDB entry both carry agree; "
            "null without an entry."
        ),
    )
    #: The gaps and conflicts in the title's metadata.
    metadata_issues: list[MetadataIssue] = Field(default_factory=list[MetadataIssue])
    catalog_selections: CatalogSelections | None = Field(
        default=None,
        description=(
            "How each selection compares with the item's OvertureDB entry; "
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
    poster: AssetRead
    last_matched_at: datetime | None = None


class LibrarySectionRead(StrictBaseModel):
    """Library selector response."""

    #: Overture's ID of the library, which names its server as well.
    id: str
    title: str
    media_type: MediaType
    #: The database's number of its server.
    server_id: int
    count: int


class FolderRootsResponse(StrictBaseModel):
    """Trusted media folder roots derived from the local DB."""

    movies: list[str]
    shows: list[str]


def item_metadata_issues(
    item: MediaItem,
    catalog_ids: Literal["matching", "mismatching"] | None,
    copies: Sequence[ItemCopyRead],
) -> list[MetadataIssue]:
    """The gaps and conflicts in a title's metadata, in the enum's order."""
    found = {
        MetadataIssue.NO_TMDB_ID: not item.tmdb_id,
        MetadataIssue.NO_TVDB_ID: item.media_type is MediaType.SHOW
        and not item.tvdb_id,
        MetadataIssue.NO_IMDB_ID: not item.imdb_id,
        MetadataIssue.NO_LOCAL_PATH: not item.folder_path,
        MetadataIssue.NO_YEAR: not item.year,
        MetadataIssue.NO_SERVER_ID: not copies,
        MetadataIssue.ID_MISMATCH: catalog_ids == "mismatching",
    }
    return [issue for issue in MetadataIssue if found[issue]]


def media_item_read_from_model(
    item: MediaItem,
    *,
    catalog_complete: bool = False,
    catalog_themerrdb: bool = False,
    seasons: Sequence[Season],
    directors: Sequence[str] = (),
    has_incorrect_aspect_ratio: bool = False,
    catalog_entry_key: str | None = None,
    catalog_ids: Literal["matching", "mismatching"] | None = None,
    catalog_selections: CatalogSelections | None = None,
    library_collection_id: int | None = None,
    copies: Sequence[ItemCopyRead] = (),
) -> MediaItemRead:
    """Map a persisted media item to the public library item response.

    *seasons* are the item's tracked seasons, which a show's artwork status
    depends on, and *directors* a movie's; callers load both in bulk.
    """
    art = item_art_status(item, seasons)
    return MediaItemRead.model_validate(
        {
            # Item metadata stays internal: it serves collection criteria only.
            **item.model_dump(include=set(MediaItemRead.model_fields)),
            "directors": list(directors),
            "assets": assets_read(item),
            "art_status": art.art,
            "season_posters_status": art.season_posters,
            "catalog_entry_key": catalog_entry_key,
            "catalog_complete": catalog_complete,
            "catalog_themerrdb": catalog_themerrdb,
            "library_collection_id": library_collection_id,
            "catalog_ids": catalog_ids,
            "catalog_selections": catalog_selections,
            "copies": list(copies),
            "metadata_issues": item_metadata_issues(item, catalog_ids, copies),
            "has_incorrect_aspect_ratio": has_incorrect_aspect_ratio,
        }
    )


def season_read_from_model(season: Season) -> SeasonRead:
    """Map a persisted season to the public season response."""
    return SeasonRead.model_validate(
        {
            **season.model_dump(include=set(SeasonRead.model_fields)),
            "poster": asset_read(read_asset(season, ServerAsset.SEASON_POSTER)),
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

    item_ids: UniqueList[PositiveId]
    operation: BulkItemOperationKind
    #: What ``artwork`` and ``themes`` remove.
    removal: AssetRemoval = Field(default_factory=AssetRemoval)


class BulkItemOperationResult(StrictBaseModel):
    """The items a bulk operation actually changed."""

    item_ids: list[int]
    operation: BulkItemOperationKind
    #: Items left as they were, and why.
    errors: dict[int, PublicText] = Field(default_factory=dict[int, PublicText])


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
