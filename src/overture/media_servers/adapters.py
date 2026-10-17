"""Normalized media-server adapter contracts."""

lazy from collections.abc import Awaitable, Callable
lazy from dataclasses import dataclass, field
lazy from datetime import datetime
lazy from pathlib import PurePath, PurePosixPath, PureWindowsPath

lazy from ..domain import MediaType
lazy from ..jobs.progress_log import JobLogEntry

MAX_SEASONS_PER_SHOW = 1000


def server_path(path: str) -> PurePath:
    """Interpret a server path by its syntax, independent of Overture's OS."""
    return PureWindowsPath(path) if "\\" in path else PurePosixPath(path)


@dataclass(slots=True, frozen=True)
class ServerSection:
    """One movie or show library on the media server."""

    key: str
    title: str
    media_type: MediaType


@dataclass(slots=True, frozen=True)
class ServerTheme:
    """One theme song the media server plays for an item.

    Plex keeps its own copy and serves it at *url*; Jellyfin and Emby play the
    file at *path*.
    """

    id: str
    title: str = "theme"
    path: str | None = None
    url: str | None = None
    duration: float | None = None


@dataclass(slots=True, frozen=True)
class ServerSeason:
    """Complete provider season snapshot; absent IDs clear stored references."""

    num: int
    title: str | None = None
    file_count: int = 0
    poster_url: str | None = None
    server_item_id: str | None = None


@dataclass(slots=True)
class ServerItem:
    """Standardized representation of an item across any media server."""

    id: str
    title: str
    year: int | None
    guids: dict[str, str]
    media_type: MediaType
    poster_url: str | None
    background_url: str | None
    server_link: str
    library_id: str = ""
    folder_path: str | None = None
    director: str | None = None
    #: Metadata version of a movie listed without its director; the sync
    #: fetches the director only when this differs from the stored version.
    director_etag: str | None = None
    studio: str | None = None
    server_added_at: datetime | None = None
    server_updated_at: datetime | None = None
    seasons: list[ServerSeason] = field(default_factory=list[ServerSeason])


@dataclass(slots=True)
class SyncItemResult:
    """Result of syncing one server item."""

    item_id: int | None
    media_type: str
    visible_changed: bool = False
    created: bool = False
    #: What changed on an existing item, in words for the sync log.
    changes: tuple[str, ...] = ()


#: Called after the shared tally is updated, with the current item's log entry.
type SyncProgressCallback = Callable[[JobLogEntry], Awaitable[None]]
#: Returns True once the caller wants the run to stop.
type SyncStopCheck = Callable[[], bool]


@dataclass(slots=True, frozen=True)
class ProviderImageRequest:
    """Provider-authenticated image request details."""

    url: str
    headers: dict[str, str]
    params: dict[str, str] | None = None
