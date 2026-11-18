"""Shared domain vocabulary.

Every closed set of values that a database column, a service, or an API
payload talks about is spelled once here, as a :class:`~enum.StrEnum`.
Persistence code, services, and schemas use these enums instead of re-typing
string literals, so a typo is a type error rather than a silently empty query
result. Pydantic publishes each enum as a named OpenAPI schema, which the
generated frontend client turns into a named type.
"""

lazy from collections.abc import Mapping
lazy from dataclasses import dataclass
lazy from enum import StrEnum
lazy from typing import Literal

lazy from .catalog_contract.contract import (
    ART_SOURCE_LABELS,
    ASPECT_RATIOS,
    ASPECT_TOLERANCE,
)


class MediaType(StrEnum):
    """Kind of library item Overture tracks."""

    MOVIE = "movie"
    SHOW = "show"

    @property
    def plural(self) -> str:
        """Return how its titles are named together, such as "movies"."""
        return f"{self.value}s"


class TermKind(StrEnum):
    """A kind of metadata a title holds several values of, such as its genres."""

    GENRE = "genre"
    ACTOR = "actor"
    DIRECTOR = "director"
    WRITER = "writer"
    PRODUCER = "producer"
    COUNTRY = "country"
    #: Plex labels or Jellyfin and Emby tags.
    LABEL = "label"
    TMDB_KEYWORD = "tmdb_keyword"
    COMPANY = "company"
    NETWORK = "network"
    #: Subscription services streaming the title in the configured region.
    STREAMING = "streaming"
    ORIGIN_COUNTRY = "origin_country"


class CatalogMediaType(StrEnum):
    """Kind of OvertureDB catalog entry: a movie, a show or a movie collection."""

    MOVIE = "movie"
    SHOW = "show"
    COLLECTION = "collection"


class SyncMode(StrEnum):
    """How a dynamic collection applies source membership."""

    SYNC = "sync"
    APPEND = "append"


class CollectionMode(StrEnum):
    """Collection visibility on servers supporting library display modes."""

    DEFAULT = "default"
    HIDE_ITEMS = "hide_items"
    SHOW_ITEMS = "show_items"
    HIDE = "hide"


class CollectionOrder(StrEnum):
    """How a collection orders its members: a field and direction, or ``custom``.

    ``custom`` keeps the manual order, or the order of the collection's first
    ordered source. Plex sorts smart collections itself; Overture orders the
    members of other collections and stores the result as a custom order.
    """

    CUSTOM = "custom"
    RELEASE_ASC = "release.asc"
    RELEASE_DESC = "release.desc"
    TITLE_ASC = "title.asc"
    TITLE_DESC = "title.desc"
    ADDED_DESC = "added.desc"
    ADDED_ASC = "added.asc"
    CRITIC_RATING_DESC = "critic_rating.desc"
    CRITIC_RATING_ASC = "critic_rating.asc"
    AUDIENCE_RATING_DESC = "audience_rating.desc"
    AUDIENCE_RATING_ASC = "audience_rating.asc"
    USER_RATING_DESC = "user_rating.desc"
    USER_RATING_ASC = "user_rating.asc"
    DURATION_DESC = "duration.desc"
    DURATION_ASC = "duration.asc"
    PLAYS_DESC = "plays.desc"
    PLAYS_ASC = "plays.asc"
    LAST_PLAYED_DESC = "last_played.desc"
    LAST_PLAYED_ASC = "last_played.asc"
    EPISODE_ADDED_DESC = "episode_added.desc"
    EPISODE_ADDED_ASC = "episode_added.asc"
    UNPLAYED_EPISODES_DESC = "unplayed_episodes.desc"
    UNPLAYED_EPISODES_ASC = "unplayed_episodes.asc"
    RANDOM = "random"


class AutoAdvance(StrEnum):
    """What the editor moves on to once a selection is saved."""

    OFF = "off"
    #: The item's next slot, stopping after its last one.
    SLOTS = "slots"
    #: The next slot, then the next item.
    SLOTS_AND_ITEMS = "slots_and_items"


#: The order a collection takes when nothing else names one.
DEFAULT_COLLECTION_ORDER = CollectionOrder.RELEASE_ASC
#: Why a smart collection cannot take a custom order.
SMART_CUSTOM_ORDER = "Smart collections are ordered by Plex; choose a sort"

#: The Radarr and Sonarr tag on every title Overture adds; no member tag may use it.
ARR_ADDED_TAG = "overture"
#: The sort title of a separated group's collections when none is set, which
#: keeps them together behind their separator.
SEPARATED_SORT_TITLE = "{group} {title}"
#: The virtual group of collections without rules; no stored group may use it.
UNMANAGED_GROUP = "Unmanaged"
UNGROUPED_GROUP = "Ungrouped"
#: Why a collection Overture does not manage refuses every change but adoption.
UNMANAGED_REFUSAL = "Adopt the collection before changing it"


class CollectionKind(StrEnum):
    """How a collection's membership is maintained on the media server."""

    REGULAR = "regular"
    SMART = "smart"
    #: An empty collection heading its group's collections, kept by the group.
    SEPARATOR = "separator"


class CollectionFiltering(StrEnum):
    """User-context filtering mode for Plex smart collections."""

    ADMIN = "admin"
    USER = "user"


class SourceType(StrEnum):
    """External lists a collection condition can test membership of."""

    TMDB_COLLECTION = "tmdb_collection"
    TMDB_ITEM = "tmdb_item"
    TMDB_LIST = "tmdb_list"
    TMDB_PERSON = "tmdb_person"
    TMDB_CHART = "tmdb_chart"
    MDBLIST = "mdblist"
    RADARR_TAG = "radarr_tag"
    SONARR_TAG = "sonarr_tag"


class TmdbChart(StrEnum):
    """A TMDB chart; some exist for movies or for shows only."""

    POPULAR = "popular"
    TOP_RATED = "top_rated"
    TRENDING_DAY = "trending_day"
    TRENDING_WEEK = "trending_week"
    NOW_PLAYING = "now_playing"
    UPCOMING = "upcoming"
    AIRING_TODAY = "airing_today"
    ON_THE_AIR = "on_the_air"


class TmdbSearchBy(StrEnum):
    """What a TMDB search looks for: titles, or the titles of something else."""

    TITLE = "title"
    #: The titles a person is credited in.
    PERSON = "person"
    #: A company's most popular titles.
    COMPANY = "company"
    #: The most popular titles with a keyword.
    KEYWORD = "keyword"
    #: The titles on a public list.
    LIST = "list"


class TmdbPersonRole(StrEnum):
    """Credit roles included by a TMDB person condition."""

    ACTOR = "actor"
    DIRECTOR = "director"
    WRITER = "writer"
    PRODUCER = "producer"
    BIOGRAPHY = "biography"


class FilterField(StrEnum):
    """Item metadata a collection condition tests."""

    TITLE = "title"
    TMDB_ID = "tmdb_id"
    TVDB_ID = "tvdb_id"
    IMDB_ID = "imdb_id"
    STUDIO = "studio"
    EDITION = "edition"
    GENRE = "genre"
    ACTOR = "actor"
    DIRECTOR = "director"
    WRITER = "writer"
    PRODUCER = "producer"
    COUNTRY = "country"
    LABEL = "label"
    COLLECTION = "collection"
    CONTENT_RATING = "content_rating"
    NETWORK = "network"
    RESOLUTION = "resolution"
    AUDIO_LANGUAGE = "audio_language"
    SUBTITLE_LANGUAGE = "subtitle_language"
    HDR = "hdr"
    DOLBY_VISION = "dolby_vision"
    HDR10_PLUS = "hdr10_plus"
    ATMOS = "atmos"
    VIDEO_CODEC = "video_codec"
    AUDIO_CODEC = "audio_codec"
    SUBTITLE_CODEC = "subtitle_codec"
    AUDIO_LAYOUT = "audio_layout"
    FILE_SIZE = "file_size"
    BITRATE = "bitrate"
    YEAR = "year"
    DECADE = "decade"
    CRITIC_RATING = "critic_rating"
    AUDIENCE_RATING = "audience_rating"
    USER_RATING = "user_rating"
    AGE_RATING = "age_rating"
    DURATION = "duration"
    PLAYS = "plays"
    ADDED = "added"
    RELEASED = "released"
    LAST_PLAYED = "last_played"
    #: When a show's latest episode was added, and one of them last played.
    EPISODE_ADDED = "episode_added"
    EPISODE_LAST_PLAYED = "episode_last_played"
    UNPLAYED_EPISODES = "unplayed_episodes"
    UNPLAYED = "unplayed"
    IN_PROGRESS = "in_progress"
    #: Whether another listed collection holds the title; false is a catch-all.
    IN_COLLECTION = "in_collection"
    VERSIONS = "versions"
    FOLDER = "folder"
    ORIGINAL_LANGUAGE = "original_language"
    ORIGIN_COUNTRY = "origin_country"
    TMDB_RATING = "tmdb_rating"
    TMDB_VOTES = "tmdb_votes"
    TMDB_KEYWORD = "tmdb_keyword"
    COMPANY = "company"
    STREAMING = "streaming"
    SHOW_STATUS = "show_status"
    LAST_AIRED = "last_aired"
    # The library's own status of each title, which only library filters test.
    MONITORED = "monitored"
    ART_STATUS = "art_status"
    POSTER_STATUS = "poster_status"
    BACKGROUND_STATUS = "background_status"
    SEASON_POSTERS_STATUS = "season_posters_status"
    POSTER_SOURCE = "poster_source"
    BACKGROUND_SOURCE = "background_source"
    POSTER_WIDTH = "poster_width"
    BACKGROUND_WIDTH = "background_width"
    INCORRECT_ASPECT_RATIO = "incorrect_aspect_ratio"
    THEME_STATUS = "theme_status"
    THEME_SOURCE = "theme_source"
    THEME_LENGTH = "theme_length"
    METADATA_ISSUE = "metadata_issue"
    OVERTUREDB_COMPLETE = "overturedb_complete"
    THEMERRDB_THEME = "themerrdb_theme"
    OVERTUREDB_POSTER = "overturedb_poster"
    OVERTUREDB_BACKGROUND = "overturedb_background"
    OVERTUREDB_SEASON_POSTERS = "overturedb_season_posters"
    OVERTUREDB_THEME = "overturedb_theme"


class FieldKind(StrEnum):
    """The value type of a filter field, which decides its operators."""

    TEXT = "text"
    TAG = "tag"
    NUMBER = "number"
    DATE = "date"
    BOOLEAN = "boolean"


class FilterOperator(StrEnum):
    """Comparison operator for a filter condition."""

    IS = "is"
    IS_NOT = "is_not"
    CONTAINS = "contains"
    DOES_NOT_CONTAIN = "does_not_contain"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN_LAST = "in_last"
    NOT_IN_LAST = "not_in_last"
    BEFORE = "before"
    AFTER = "after"


class SetDimension(StrEnum):
    """The metadata a collection set creates one collection per value of."""

    DECADE = "decade"
    YEAR = "year"
    GENRE = "genre"
    STUDIO = "studio"
    COUNTRY = "country"
    CONTENT_RATING = "content_rating"
    RESOLUTION = "resolution"
    LABEL = "label"
    ACTOR = "actor"
    DIRECTOR = "director"
    WRITER = "writer"
    PRODUCER = "producer"
    FRANCHISE = "franchise"
    EDITION = "edition"
    NETWORK = "network"
    ORIGINAL_LANGUAGE = "original_language"
    ORIGIN_COUNTRY = "origin_country"
    STREAMING = "streaming"
    AUDIO_LANGUAGE = "audio_language"
    SUBTITLE_LANGUAGE = "subtitle_language"
    VIDEO_CODEC = "video_codec"
    AUDIO_CODEC = "audio_codec"
    AUDIO_LAYOUT = "audio_layout"
    COMPANY = "company"
    TMDB_KEYWORD = "tmdb_keyword"
    SHOW_STATUS = "show_status"
    #: Collections the set lists itself, each with its own conditions.
    CUSTOM = "custom"


class ThemeIdSource(StrEnum):
    """Evidence used to record an item's selected YouTube ID."""

    DOWNLOAD = "download"
    EMBEDDED_ID = "embedded_id"
    SOURCE_URL = "source_url"
    METADATA_URL = "metadata_url"
    #: Chosen for an item without a local folder, so nothing was downloaded.
    SELECTION = "selection"


class AssetStatus(StrEnum):
    """How much of an asset Overture holds.

    ``complete`` once both the selection and the local file are recorded (or
    just the selection, for an item without a local folder), ``partial`` when
    only some of it is.
    """

    COMPLETE = "complete"
    PARTIAL = "partial"
    MISSING = "missing"


_MEDIA_TYPE_ORDER: frozendict[str, int] = frozendict(
    {MediaType.MOVIE: 0, MediaType.SHOW: 1}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)


def text_sort_key(value: str, identity: object = "") -> tuple[str, str, str]:
    """Return one deterministic, case-insensitive alphabetical key."""
    return value.casefold(), value, str(identity)


#: Movies before shows, then title; see :func:`media_sort_key`.
type MediaSortKey = tuple[int, str, str, str]


def media_sort_key(media_type: str, title: str, identity: object = "") -> MediaSortKey:
    """Order movies before shows, then alphabetically by title."""
    return (
        _MEDIA_TYPE_ORDER.get(media_type, len(_MEDIA_TYPE_ORDER)),
        *text_sort_key(title, identity),
    )


class ServerAsset(StrEnum):
    """An asset a media server shows for an item: one artwork slot, or the theme.

    A refresh unlocks exactly the assets it is meant to replace.
    """

    POSTER = "poster"
    BACKGROUND = "background"
    SEASON_POSTER = "season_poster"
    THEME = "theme"

    @property
    def art_type(self) -> ArtType | None:
        """Return the artwork slot this asset is, or ``None`` for the theme."""
        return None if self is ServerAsset.THEME else ArtType(self.value)


class ArtType(StrEnum):
    """One artwork slot an owner can hold."""

    POSTER = "poster"
    BACKGROUND = "background"
    SEASON_POSTER = "season_poster"

    @property
    def owned_by_season(self) -> bool:
        """Return whether this slot hangs off a season rather than an item."""
        return self is ArtType.SEASON_POSTER

    @property
    def server_asset(self) -> ServerAsset:
        """Return the media-server asset this slot is shown as."""
        return ServerAsset(self.value)

    @property
    def aspect_ratio(self) -> float:
        """Return the width-to-height ratio artwork in this slot should have."""
        return ASPECT_RATIOS["background" if self is ArtType.BACKGROUND else "poster"]

    @property
    def display_width(self) -> int:
        """Return how wide, in device pixels, this slot's display rendition is.

        Twice the CSS width, for high-density screens: the 200x300px detail
        poster and the detail background banner.
        """
        return 960 if self is ArtType.BACKGROUND else 400

    @property
    def display_height(self) -> int:
        """Return how tall, in device pixels, this slot's display rendition is."""
        if self is ArtType.BACKGROUND:
            return self.display_width * 9 // 16
        return self.display_width * 3 // 2

    @property
    def label(self) -> str:
        """Return how the slot is named in prose ("season poster")."""
        return self.value.replace("_", " ")


#: The box a thumbnail fits in: the widest and the tallest display rendition of
#: any slot. Artwork is shown by its thumbnail everywhere in the interface, so
#: this one box serves every slot and a thumbnail depends on the image alone.
THUMB_BOUNDS: tuple[int, int] = (
    max(art_type.display_width for art_type in ArtType),
    max(art_type.display_height for art_type in ArtType),
)


#: Art types stored against a media item. Ordered for deterministic iteration.
ITEM_ART_TYPES: tuple[ArtType, ...] = (ArtType.POSTER, ArtType.BACKGROUND)


class ArtStyle(StrEnum):
    """The colours of art Overture generates from a title."""

    DARK = "dark"
    LIGHT = "light"
    ACCENT = "accent"


@dataclass(frozen=True, slots=True)
class ArtGeneration:
    """How Overture generates a piece of art.

    A poster shows the title, under its group unless *title_only*; a
    background shows the style's colours alone, as the server draws the title
    over it.
    """

    style: ArtStyle
    title_only: bool = False


class CollectionPosterStyle(StrEnum):
    """Which poster OvertureDB gives a TMDB collection.

    ``matte`` and ``overlay`` take the consistent poster in that layout; a
    collection without one has no OvertureDB poster.
    """

    INDIVIDUAL = "individual"
    MATTE = "matte"
    OVERLAY = "overlay"


class AutoArtSource(StrEnum):
    """Where Automatic art takes a collection slot's art from, in a policy's order.

    A sync tries each in turn and stops at the first that gives art: the best
    art of a catalog source, or, with ``generate``, art generated from the title.
    """

    OVERTUREDB = "overturedb"
    TMDB = "tmdb"
    GENERATE = "generate"

    @property
    def art_source(self) -> ArtSource | None:
        """Return the catalog source it takes art from; ``None`` for ``generate``."""
        return None if self is AutoArtSource.GENERATE else ArtSource(self.value)


class MetadataIssue(StrEnum):
    """A gap or conflict in a title's or collection's metadata."""

    NO_TMDB_ID = "no_tmdb_id"
    NO_TVDB_ID = "no_tvdb_id"
    NO_IMDB_ID = "no_imdb_id"
    NO_LOCAL_PATH = "no_local_path"
    NO_YEAR = "no_year"
    NO_SERVER_ID = "no_server_id"
    #: An ID the title and its OvertureDB entry both carry differs.
    ID_MISMATCH = "id_mismatch"

    @property
    def label(self) -> str:
        """How the issue is named to people."""
        return _METADATA_ISSUE_LABELS[self]

    @property
    def collections(self) -> bool:
        """Whether collections can have it, as well as titles."""
        return self in {MetadataIssue.NO_TMDB_ID, MetadataIssue.NO_SERVER_ID}

    @property
    def show_only(self) -> bool:
        """Whether only shows can have it: TVDB identifies shows."""
        return self is MetadataIssue.NO_TVDB_ID

    @property
    def needs_catalog(self) -> bool:
        """Whether it is found only against an OvertureDB entry."""
        return self is MetadataIssue.ID_MISMATCH


_METADATA_ISSUE_LABELS = {
    MetadataIssue.NO_TMDB_ID: "No TMDB ID",
    MetadataIssue.NO_TVDB_ID: "No TVDB ID",
    MetadataIssue.NO_IMDB_ID: "No IMDb ID",
    MetadataIssue.NO_LOCAL_PATH: "No local path",
    MetadataIssue.NO_YEAR: "No year",
    MetadataIssue.NO_SERVER_ID: "No media server ID",
    MetadataIssue.ID_MISMATCH: "ID mismatch",
}


class NotifyCompleted(StrEnum):
    """Which completed runs are announced."""

    NEVER = "never"
    ALWAYS = "always"
    #: Runs that added, changed, removed or downloaded something, or found a mismatch.
    CHANGES = "changes"
    #: Runs that finished with one or more targets failing.
    ERRORS = "errors"


class ArtSource(StrEnum):
    """Where selected artwork comes from.

    ``overturedb`` when it is the OvertureDB catalog's artwork for the slot,
    ``upload`` when someone uploaded it, else the name of the catalog art
    source whose host serves it. A test keeps the hosts in step with the
    catalog contract's art sources.
    """

    OVERTUREDB = "overturedb"
    TMDB = "tmdb"
    TPDB = "tpdb"
    FANART = "fanart"
    TVDB = "tvdb"
    PLEX = "plex"
    UPLOAD = "upload"
    #: Generated by Overture from the collection's title.
    GENERATED = "generated"

    @property
    def label(self) -> str:
        """How the source is named to people."""
        match self:
            case ArtSource.UPLOAD:
                return "Upload"
            case ArtSource.GENERATED:
                return "Generated"
            case _:
                return ART_SOURCE_LABELS[self.value]


class ImageSize(StrEnum):
    """A downscaled rendition of artwork; no size means the original file."""

    #: Sized for the detail page.
    DISPLAY = "display"


class ServerType(StrEnum):
    """Media server that supplied a record."""

    PLEX = "plex"
    JELLYFIN = "jellyfin"
    EMBY = "emby"

    @property
    def display_name(self) -> str:
        """Return how this media server is named to users."""
        return self.value.capitalize()


#: Separates the server from its own key in a library ID.
_LIBRARY_ID_SEPARATOR = ":"


def library_id(server_id: int, key: str) -> str:
    """Return Overture's ID of library *key* on server *server_id*.

    A server's library keys are unique only on that server, so Overture's
    library IDs name the server too; they stay opaque everywhere else.
    """
    return f"{server_id}{_LIBRARY_ID_SEPARATOR}{key}"


def library_parts(value: str) -> tuple[int, str] | None:
    """Return the server and the server's key a library ID names, if it is one."""
    server, separator, key = value.partition(_LIBRARY_ID_SEPARATOR)
    if not separator or not key or not server.isdecimal():
        return None
    return int(server), key


def library_server(value: str) -> int:
    """Return the server a library ID names.

    Raises:
        ValueError: When *value* is not a library ID.
    """
    parts = library_parts(value)
    if parts is None:
        raise ValueError(f"Library {value} names no server")
    return parts[0]


class JobType(StrEnum):
    """Kind of work a download job performs."""

    ART = "art"
    THEME = "theme"
    COLLECTION_THEME = "collection_theme"


@dataclass(slots=True, frozen=True)
class AssetScope:
    """The assets of one item or collection that download jobs write.

    A field left ``None`` matches every value, so a season poster scope
    without a season covers every season of the item.
    """

    media_item_id: int | None = None
    collection_id: int | None = None
    job_type: JobType | None = None
    art_type: ArtType | None = None
    season_id: int | None = None

    @property
    def lock_key(self) -> int | str:
        """The asset lock that writing these assets takes."""
        if self.media_item_id is not None:
            return self.media_item_id
        return f"collection:{self.collection_id}"


class JobStatus(StrEnum):
    """Lifecycle state of a download job."""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


#: Statuses that keep a job in the queue and block an equivalent new job.
ACTIVE_JOB_STATUSES: tuple[JobStatus, ...] = (JobStatus.PENDING, JobStatus.RUNNING)


class MediaServerState(StrEnum):
    """Whether the media server answered Overture's last request."""

    #: No request has been made since Overture started.
    UNKNOWN = "unknown"
    REACHABLE = "reachable"
    #: The server could not be reached, timed out or answered with a server error.
    UNREACHABLE = "unreachable"
    #: The server refused the configured credentials.
    REJECTED = "rejected"


class ScheduleKind(StrEnum):
    """Category of reusable named schedule."""

    ASSETS = "assets"
    SYNC = "sync"


class Workflow(StrEnum):
    """Assets included in the user's selection workflow."""

    ART = "art"
    ART_AND_THEMES = "art_and_themes"
    THEMES = "themes"


class AutoUnmonitor(StrEnum):
    """Completion condition that automatically stops monitoring an item."""

    OFF = "off"
    ART = "art"
    THEME = "theme"
    ART_OR_THEME = "art_or_theme"
    ART_AND_THEME = "art_and_theme"


class AspectRatioTolerance(StrEnum):
    """How strictly artwork aspect ratios are enforced."""

    STRICT = "strict"
    LENIENT = "lenient"
    OFF = "off"

    @property
    def fraction(self) -> float | None:
        """Return how far off its slot's ratio artwork may be, or None to accept any.

        ``strict`` only absorbs fractional-resolution rounding; ``lenient``
        allows slightly off-spec art.
        """
        return {"strict": ASPECT_TOLERANCE, "lenient": 0.05, "off": None}[self.value]


class TmdbLanguageFilter(StrEnum):
    """Which TMDB image languages are offered as candidates."""

    EN_NULL = "en_null"
    ALL = "all"


class ArtBulkSource(StrEnum):
    """Artwork source an Assets run can try."""

    OVERTUREDB = "overturedb"
    LOCAL_ART_MATCHING = "local_art_matching"

    @property
    def catalog(self) -> bool:
        """Whether this source is the curated catalog, which OvertureDB provides."""
        return self is ArtBulkSource.OVERTUREDB

    @property
    def label(self) -> str:
        """Return how the source is named to users."""
        return {"overturedb": "OvertureDB", "local_art_matching": "Local art matching"}[
            self.value
        ]


class ThemeBulkSource(StrEnum):
    """Theme source an Assets run can try."""

    OVERTUREDB = "overturedb"
    THEMERRDB = "themerrdb"
    YOUTUBE_SEARCH = "youtube_search"

    @property
    def catalog(self) -> bool:
        """Whether this source is a curated catalog (OvertureDB or ThemerrDB)."""
        return self is not ThemeBulkSource.YOUTUBE_SEARCH

    @property
    def label(self) -> str:
        """Return how the source is named in job logs."""
        return {
            "overturedb": "OvertureDB",
            "themerrdb": "ThemerrDB",
            "youtube_search": "YouTube search",
        }[self.value]


class IncrementalThemeOrder(StrEnum):
    """Theme sources, in priority order, queued for media found by incremental sync."""

    OFF = "off"
    OVERTUREDB_THEMERRDB = "overturedb_themerrdb"
    THEMERRDB_OVERTUREDB = "themerrdb_overturedb"

    @property
    def sources(self) -> tuple[ThemeBulkSource, ...]:
        """Return the catalogs this order asks, first to last."""
        return tuple(
            ThemeBulkSource(name) for name in self.value.split("_") if name != "off"
        )


class RecentUnit(StrEnum):
    """Unit of the "skip recently checked" window."""

    HOURS = "hours"
    DAYS = "days"

    @property
    def seconds(self) -> int:
        """Return how many seconds one unit lasts."""
        return 3600 if self is RecentUnit.HOURS else 86400


def guid_int(guids: Mapping[str, str], provider: str) -> int | None:
    """Return a numeric provider GUID, or None when absent or unparseable."""
    raw = guids.get(provider)
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def guid_text(guids: Mapping[str, str], provider: str) -> str | None:
    """Return a textual provider GUID, or None when absent."""
    return guids.get(provider) or None


#: Artwork sources an Assets run tries, in their default order.
DEFAULT_ART_SOURCE_ORDER: tuple[ArtBulkSource, ...] = tuple(ArtBulkSource)
#: Theme sources an Assets run tries, in their default order.
DEFAULT_THEME_SOURCE_ORDER: tuple[ThemeBulkSource, ...] = tuple(ThemeBulkSource)

#: Default and largest pHash distance a local art match accepts.
MATCH_THRESHOLD_DEFAULT = 3
MATCH_THRESHOLD_MAX = 10
#: An Assets-run threshold that accepts byte-identical images only.
PERFECT_MATCH_ONLY = -1
#: Unattended Assets runs adopt only byte-identical local art unless told otherwise.
ASSETS_MATCH_THRESHOLD_DEFAULT = PERFECT_MATCH_ONLY


#: What a bulk operation changes on item records; artwork and themes are removed.
type BulkItemOperationKind = Literal[
    "artwork", "themes", "delete", "monitor", "unmonitor"
]
