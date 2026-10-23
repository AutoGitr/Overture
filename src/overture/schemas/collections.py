"""Collection REST and WebSocket schemas."""

lazy import hashlib
lazy from typing import Annotated

lazy from pydantic import Field

lazy from ..config import API_PREFIX
lazy from ..db.completion import collection_theme_status
lazy from ..db.models.media_collection import MediaCollection
lazy from ..db.models.public_dataset import PublicDatasetCollection
lazy from ..domain import AssetStatus, CollectionMatch, MediaType, ServerType
lazy from .base import StrictBaseModel
lazy from .common import StatusResponse
lazy from .validators import YouTubeId


class CollectionRead(StrictBaseModel):
    """Media-server collection response."""

    id: int
    title: str
    summary: str | None = None
    thumb_url: str | None = None
    art_url: str | None = None
    child_count: int = 0
    media_type: MediaType
    library_id: str | None = None
    server_added_at: str | None = None
    server_type: ServerType
    server_link: str | None = None
    #: The media server holds a theme for the collection.
    has_theme: bool = False
    youtube_id: str | None = None
    youtube_title: str | None = None
    youtube_duration: int | None = None
    theme_status: AssetStatus = AssetStatus.MISSING
    monitored: bool = True
    tmdb_collection_id: int | None = None
    tmdb_match: CollectionMatch = CollectionMatch.AUTO
    #: The catalog has an OvertureDB theme for the collection's TMDB collection.
    public_dataset_complete: bool = False
    #: The catalog has a ThemerrDB theme for it.
    public_dataset_themerrdb: bool = False


class CollectionMember(StrictBaseModel):
    """A stored item a collection holds."""

    id: int
    title: str
    year: int | None = None
    media_type: MediaType
    tmdb_id: int | None = None


class CollectionDetail(CollectionRead):
    """One collection with its members and what limits its theme."""

    members: list[CollectionMember]
    #: Why a theme cannot be stored on this collection, if it cannot.
    theme_unavailable: str | None = None
    theme_writable: bool = False
    catalog_entry_key: str | None = None
    #: The catalog entry's title, when OvertureDB has the TMDB collection.
    catalog_title: str | None = None
    #: The catalog's theme candidates for the collection.
    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None


class CollectionMatchRequest(StrictBaseModel):
    """Match a collection to a TMDB collection; ``None`` keeps it unmatched."""

    media_type: MediaType
    tmdb_collection_id: Annotated[int, Field(gt=0)] | None


class CollectionThemeStatusResponse(StrictBaseModel):
    """Collection theme status response."""

    has_theme: bool
    youtube_id: str | None = None
    youtube_title: str | None = None
    youtube_duration: int | None = None


class SetCollectionThemeRequest(StrictBaseModel):
    """Validate the set collection theme request payload."""

    youtube_id: YouTubeId
    media_type: MediaType


class DeleteCollectionThemeResponse(StatusResponse):
    """Collection theme delete response."""

    has_theme: bool
    theme_status: AssetStatus


class CollectionThemeUpdatedEvent(StrictBaseModel):
    """Collection theme state update."""

    collection_id: int
    media_type: MediaType
    has_theme: bool
    youtube_id: str | None = None
    youtube_title: str | None = None
    youtube_duration: int | None = None
    theme_status: AssetStatus


def _collection_image_url(
    collection_id: int, image_type: str, server_url: str | None
) -> str | None:
    """Return Overture's route for a collection image the server has.

    ``t`` names the server's current image, so a replaced one is fetched anew
    instead of read from the browser's cache, without revealing the server URL.
    """
    if not server_url:
        return None
    version = hashlib.sha256(server_url.encode()).hexdigest()[:16]
    return f"{API_PREFIX}/collections/{collection_id}/image/{image_type}?t={version}"


def collection_read(
    row: MediaCollection, catalog: PublicDatasetCollection | None
) -> CollectionRead:
    """Map a stored collection and its catalog entry to public output."""
    has_theme = row.server_theme_id is not None or row.theme_file_hash is not None
    return CollectionRead(
        id=row.id or 0,
        title=row.title,
        summary=row.summary,
        thumb_url=_collection_image_url(row.id or 0, "poster", row.thumb_url),
        art_url=_collection_image_url(row.id or 0, "background", row.art_url),
        child_count=row.child_count,
        media_type=row.media_type,
        library_id=row.library_id,
        server_added_at=row.server_added_at.isoformat()
        if row.server_added_at
        else None,
        server_type=row.server_type,
        server_link=row.server_link,
        has_theme=has_theme,
        youtube_id=row.youtube_id,
        youtube_title=row.youtube_title,
        youtube_duration=row.youtube_duration,
        theme_status=collection_theme_status(
            server_has_theme=has_theme, youtube_id=row.youtube_id
        ),
        monitored=row.monitored,
        tmdb_collection_id=row.tmdb_collection_id,
        tmdb_match=row.tmdb_match,
        public_dataset_complete=bool(catalog and catalog.youtube_id_overturedb),
        public_dataset_themerrdb=bool(catalog and catalog.youtube_id_themerrdb),
    )


def collection_theme_status_response(
    collection: CollectionRead,
) -> CollectionThemeStatusResponse:
    """Project synchronized collection theme state."""
    return CollectionThemeStatusResponse(
        has_theme=collection.has_theme,
        youtube_id=collection.youtube_id,
        youtube_title=collection.youtube_title,
        youtube_duration=collection.youtube_duration,
    )


class BulkCollectionMonitorUpdate(StrictBaseModel):
    """Validate bulk collection monitor updates."""

    collection_ids: list[int]
    media_type: MediaType
    monitored: bool


class CollectionUpdatedEvent(StrictBaseModel):
    """A collection's match, membership or monitoring changed."""

    collection_id: int


class CollectionThemeSources(StrictBaseModel):
    """The catalog's theme candidates for a matched collection."""

    youtube_id_overturedb: str | None = None
    youtube_id_themerrdb: str | None = None
