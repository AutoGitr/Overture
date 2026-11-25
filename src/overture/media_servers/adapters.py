"""Normalized media-server adapter contracts."""

lazy from collections.abc import Callable
lazy from dataclasses import dataclass, field
lazy from datetime import datetime
lazy from pathlib import PurePath, PurePosixPath, PureWindowsPath
lazy from typing import Protocol

lazy from ..domain import (
    CollectionFiltering,
    CollectionMode,
    CollectionOrder,
    MediaType,
)
lazy from ..utils.hashing import text_digest

MAX_SEASONS_PER_SHOW = 1000


class ItemIdentity(Protocol):
    """What a server needs to find its copy of a library item."""

    @property
    def media_type(self) -> MediaType: ...

    @property
    def title(self) -> str: ...

    @property
    def tmdb_id(self) -> int | None: ...

    @property
    def tvdb_id(self) -> int | None: ...

    @property
    def imdb_id(self) -> str | None: ...


@dataclass(slots=True, frozen=True)
class UploadThemes:
    """The server stores uploaded collection themes."""


@dataclass(slots=True, frozen=True)
class FolderThemes:
    """The server reads collection themes from its metadata folders."""


@dataclass(slots=True, frozen=True)
class NoCollectionThemes:
    """The server supports collections but cannot store their themes."""


type CollectionSupport = UploadThemes | FolderThemes | NoCollectionThemes


def server_path(path: str) -> PurePath:
    """Interpret a server path by its syntax, independent of Overture's OS."""
    return PureWindowsPath(path) if "\\" in path else PurePosixPath(path)


def image_version(ref: str | None) -> str | None:
    """Name the image a server shows by its link, without revealing the link.

    ``None`` when the server shows none. The name changes whenever the link
    does, so a browser fetches a replaced image again.
    """
    return text_digest(ref, 16) if ref else None


def video_resolution(width: int | None) -> str | None:
    """Name a frame width as Plex names resolutions, so criteria match alike."""
    if not width:
        return None
    for minimum, name in ((3200, "4k"), (1700, "1080"), (1100, "720"), (700, "480")):
        if width >= minimum:
            return name
    return "sd"


@dataclass(slots=True, frozen=True)
class ServerSection:
    """One movie or show library on the media server."""

    #: The server's own key, which only its provider uses.
    key: str
    title: str
    media_type: MediaType
    #: Overture's ID of the library, which names the server as well; the
    #: provider sets it from *key*.
    library_id: str = ""


@dataclass(slots=True, frozen=True)
class ServerWebLinks:
    """Where the server's web app opens an item or a collection.

    ``{id}`` in each stands for the item's or collection's server ID.
    """

    item: str
    collection: str


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
    #: Overture's ID of the library listing it.
    library_id: str = ""
    #: Where Overture sees the item's folder.
    folder_path: str | None = None
    directors: tuple[str, ...] = ()
    #: Metadata version of a movie listed without its directors; the sync
    #: fetches them only when this differs from the stored version.
    director_etag: str | None = None
    sort_title: str | None = None
    studio: str | None = None
    genres: tuple[str, ...] = ()
    actors: tuple[str, ...] = ()
    writers: tuple[str, ...] = ()
    producers: tuple[str, ...] = ()
    countries: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()
    content_rating: str | None = None
    edition: str | None = None
    #: Every resolution its video comes in, named as Plex names them: a
    #: movie's versions, a show's episodes.
    resolutions: tuple[str, ...] = ()
    critic_rating: float | None = None
    audience_rating: float | None = None
    user_rating: float | None = None
    duration_seconds: int | None = None
    plays: int | None = None
    last_played_at: datetime | None = None
    unplayed: bool | None = None
    in_progress: bool | None = None
    release_date: str | None = None
    #: How many versions (files) of a movie the server holds, where it says.
    versions: int | None = None
    server_added_at: datetime | None = None
    server_updated_at: datetime | None = None
    seasons: list[ServerSeason] = field(default_factory=list[ServerSeason])


@dataclass(slots=True, frozen=True)
class ServerCollection:
    """One collection on the media server and the items it holds.

    ``media_type`` and ``library_id`` are ``None`` when the server keeps
    collections outside its libraries (Jellyfin); the sync takes them from the
    members instead.
    """

    id: str
    title: str
    member_ids: tuple[str, ...]
    media_type: MediaType | None = None
    library_id: str | None = None
    summary: str | None = None
    sort_title: str | None = None
    smart: bool = False
    collection_mode: CollectionMode | None = None
    order_type: CollectionOrder | None = None
    collection_filtering: CollectionFiltering | None = None
    thumb_url: str | None = None
    art_url: str | None = None
    theme_id: str | None = None
    #: The TMDB collection ID the server names, such as a Jellyfin BoxSet's.
    tmdb_id: int | None = None
    #: The server's folder for the collection, where Jellyfin reads its theme.
    path: str | None = None
    added_at: datetime | None = None


@dataclass(slots=True, frozen=True)
class CollectionDetails:
    """What a sync sends a server collection besides its members.

    A server keeps what it can: only Plex has modes, visibility and filtering.
    """

    title: str
    #: ``None`` leaves the server's summary or sort title as it is; an empty
    #: sort title hands it back to the server.
    summary: str | None
    sort_title: str | None
    mode: CollectionMode
    order: CollectionOrder
    smart: bool
    visible_home: bool
    visible_shared: bool = False
    visible_library: bool = False
    filtering: CollectionFiltering | None = None
    #: It has a Plex hub whose visibility the sync sets; an empty separator
    #: has none, and Plex answers 404 when asked for one.
    hub: bool = True


@dataclass(slots=True, frozen=True)
class MemberWrite:
    """What a server collection holds after a membership write, and its changes."""

    #: The server's IDs of its members, in the order the write left them.
    held: list[str]
    #: How many members the write added and removed.
    added: int
    removed: int


@dataclass(slots=True)
class SyncItemResult:
    """Result of syncing one server item."""

    item_id: int | None
    media_type: str
    visible_changed: bool = False
    created: bool = False
    #: What changed on an existing item, in words for the sync log.
    changes: tuple[str, ...] = ()
    #: Libraries the title was held in before, which its library may succeed.
    left_libraries: tuple[str, ...] = ()


#: Returns True once the caller wants the run to stop.
type SyncStopCheck = Callable[[], bool]


@dataclass(slots=True, frozen=True)
class ProviderImageRequest:
    """Provider-authenticated image request details."""

    url: str
    headers: dict[str, str]
    params: dict[str, str] | None = None
