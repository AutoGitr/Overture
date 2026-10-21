"""Collection REST and WebSocket schemas."""

lazy import hashlib
lazy from collections.abc import Mapping
lazy from typing import Any

lazy from ..config import API_PREFIX
lazy from ..db.completion import collection_theme_status
lazy from ..domain import AssetStatus, MediaType, ServerType
lazy from .base import StrictBaseModel
lazy from .common import StatusResponse
lazy from .validators import YouTubeId


class CollectionRead(StrictBaseModel):
    """Media-server collection response."""

    id: str
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

    server_id: str
    media_type: MediaType
    has_theme: bool
    youtube_id: str | None = None
    youtube_title: str | None = None
    youtube_duration: int | None = None
    theme_status: AssetStatus


def _collection_image_url(
    collection_id: str, image_type: str, server_url: str | None
) -> str | None:
    """Return Overture's route for a collection image the server has.

    ``t`` names the server's current image, so a replaced one is fetched anew
    instead of read from the browser's cache, without revealing the server URL.
    """
    if not server_url:
        return None
    version = hashlib.sha256(server_url.encode()).hexdigest()[:16]
    return f"{API_PREFIX}/collections/{collection_id}/image/{image_type}?t={version}"


def collection_read_from_provider(
    collection: Mapping[str, Any],
    *,
    youtube_id: str | None,
    youtube_title: str | None,
    youtube_duration: int | None,
    monitored: bool,
) -> CollectionRead:
    """Map provider collection metadata plus Overture provenance to public output."""
    collection_id = str(collection.get("id") or "")
    has_provider_theme = bool(collection.get("theme_id"))
    return CollectionRead(
        id=collection_id,
        title=str(collection.get("title") or ""),
        summary=collection.get("summary") or "",
        thumb_url=_collection_image_url(
            collection_id, "poster", collection.get("thumb_url")
        ),
        art_url=_collection_image_url(
            collection_id, "background", collection.get("art_url")
        ),
        child_count=int(collection.get("child_count") or 0),
        media_type=collection["media_type"],
        library_id=collection.get("library_id"),
        server_added_at=collection.get("server_added_at"),
        server_type=collection["server_type"],
        server_link=collection.get("server_link"),
        has_theme=has_provider_theme,
        youtube_id=youtube_id,
        youtube_title=youtube_title,
        youtube_duration=youtube_duration,
        theme_status=collection_theme_status(
            server_has_theme=has_provider_theme, youtube_id=youtube_id
        ),
        monitored=bool(monitored),
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

    collection_ids: list[str]
    media_type: MediaType
    monitored: bool
