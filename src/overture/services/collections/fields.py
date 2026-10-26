"""The metadata collection criteria test, and where each server can test it.

Overture evaluates criteria against the metadata item sync stores, so a field
works for regular collections only where the server supplies that metadata.
Plex smart collections are evaluated by Plex, which tests its own fields.
"""

lazy from dataclasses import dataclass
lazy from typing import Literal

lazy from ...domain import (
    CollectionOrder,
    FieldKind,
    FilterField,
    FilterOperator,
    MediaType,
    ServerType,
    SetDimension,
)

type PlexFieldType = Literal["string", "tag", "integer", "float", "date", "boolean"]

_ALL_MEDIA = frozenset(MediaType)
_MOVIES = frozenset({MediaType.MOVIE})
_SHOWS = frozenset({MediaType.SHOW})
_EVERY_SERVER = frozenset(ServerType)
_PLEX = frozenset({ServerType.PLEX})
_NO_SERVER: frozenset[ServerType] = frozenset()


@dataclass(slots=True, frozen=True)
class PlexField:
    """How Plex's media query language names and types a field.

    ``tag`` fields take the keys Plex lists for the section's values, such as
    tag IDs or language codes, rather than their names. ``scale`` converts
    Overture's unit into Plex's (minutes into milliseconds).
    """

    key: str
    type: PlexFieldType
    scale: int = 1


@dataclass(slots=True, frozen=True)
class FieldSpec:
    """One criteria field: its value kind, media types and evaluators."""

    label: str
    kind: FieldKind
    media_types: frozenset[MediaType]
    #: Servers whose synced metadata lets Overture evaluate the field.
    local: frozenset[ServerType]
    plex: PlexField | None
    #: Whole numbers, which Plex compares without a fractional margin.
    integer: bool = False


FIELDS: frozendict[FilterField, FieldSpec] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        FilterField.TITLE: FieldSpec(
            "Title",
            FieldKind.TEXT,
            _ALL_MEDIA,
            _EVERY_SERVER,
            PlexField("title", "string"),
        ),
        FilterField.STUDIO: FieldSpec(
            "Studio",
            FieldKind.TEXT,
            _ALL_MEDIA,
            _EVERY_SERVER,
            PlexField("studio", "string"),
        ),
        FilterField.EDITION: FieldSpec(
            "Edition",
            FieldKind.TEXT,
            _MOVIES,
            _PLEX,
            PlexField("editionTitle", "string"),
        ),
        FilterField.GENRE: FieldSpec(
            "Genre", FieldKind.TAG, _ALL_MEDIA, _EVERY_SERVER, PlexField("genre", "tag")
        ),
        FilterField.ACTOR: FieldSpec(
            "Actor", FieldKind.TAG, _ALL_MEDIA, _EVERY_SERVER, PlexField("actor", "tag")
        ),
        FilterField.DIRECTOR: FieldSpec(
            "Director",
            FieldKind.TAG,
            _MOVIES,
            _EVERY_SERVER,
            PlexField("director", "tag"),
        ),
        FilterField.WRITER: FieldSpec(
            "Writer", FieldKind.TAG, _MOVIES, _EVERY_SERVER, PlexField("writer", "tag")
        ),
        FilterField.PRODUCER: FieldSpec(
            "Producer",
            FieldKind.TAG,
            _MOVIES,
            _EVERY_SERVER,
            PlexField("producer", "tag"),
        ),
        FilterField.COUNTRY: FieldSpec(
            "Country",
            FieldKind.TAG,
            _ALL_MEDIA,
            _EVERY_SERVER,
            PlexField("country", "tag"),
        ),
        FilterField.LABEL: FieldSpec(
            "Label", FieldKind.TAG, _ALL_MEDIA, _EVERY_SERVER, PlexField("label", "tag")
        ),
        FilterField.COLLECTION: FieldSpec(
            "Collection",
            FieldKind.TAG,
            _ALL_MEDIA,
            _EVERY_SERVER,
            PlexField("collection", "tag"),
        ),
        FilterField.CONTENT_RATING: FieldSpec(
            "Content rating",
            FieldKind.TAG,
            _ALL_MEDIA,
            _EVERY_SERVER,
            PlexField("contentRating", "tag"),
        ),
        FilterField.NETWORK: FieldSpec(
            "Network", FieldKind.TAG, _SHOWS, _NO_SERVER, PlexField("network", "tag")
        ),
        FilterField.RESOLUTION: FieldSpec(
            "Resolution",
            FieldKind.TAG,
            _MOVIES,
            _EVERY_SERVER,
            PlexField("resolution", "tag"),
        ),
        FilterField.AUDIO_LANGUAGE: FieldSpec(
            "Audio language",
            FieldKind.TAG,
            _MOVIES,
            _NO_SERVER,
            PlexField("audioLanguage", "tag"),
        ),
        FilterField.SUBTITLE_LANGUAGE: FieldSpec(
            "Subtitle language",
            FieldKind.TAG,
            _MOVIES,
            _NO_SERVER,
            PlexField("subtitleLanguage", "tag"),
        ),
        FilterField.HDR: FieldSpec(
            "HDR", FieldKind.BOOLEAN, _MOVIES, _NO_SERVER, PlexField("hdr", "boolean")
        ),
        FilterField.YEAR: FieldSpec(
            "Year",
            FieldKind.NUMBER,
            _ALL_MEDIA,
            _EVERY_SERVER,
            PlexField("year", "integer"),
            integer=True,
        ),
        FilterField.DECADE: FieldSpec(
            "Decade",
            FieldKind.NUMBER,
            _ALL_MEDIA,
            _EVERY_SERVER,
            PlexField("decade", "integer"),
            integer=True,
        ),
        FilterField.CRITIC_RATING: FieldSpec(
            "Critic rating",
            FieldKind.NUMBER,
            _ALL_MEDIA,
            _EVERY_SERVER,
            PlexField("rating", "float"),
        ),
        FilterField.AUDIENCE_RATING: FieldSpec(
            "Audience rating",
            FieldKind.NUMBER,
            _ALL_MEDIA,
            _EVERY_SERVER,
            PlexField("audienceRating", "float"),
        ),
        FilterField.USER_RATING: FieldSpec(
            "User rating",
            FieldKind.NUMBER,
            _ALL_MEDIA,
            _PLEX,
            PlexField("userRating", "float"),
        ),
        FilterField.DURATION: FieldSpec(
            "Duration (minutes)",
            FieldKind.NUMBER,
            _MOVIES,
            _EVERY_SERVER,
            PlexField("duration", "integer", scale=60_000),
            integer=True,
        ),
        FilterField.PLAYS: FieldSpec(
            "Plays",
            FieldKind.NUMBER,
            _MOVIES,
            _PLEX,
            PlexField("viewCount", "integer"),
            integer=True,
        ),
        FilterField.ADDED: FieldSpec(
            "Date added",
            FieldKind.DATE,
            _ALL_MEDIA,
            _EVERY_SERVER,
            PlexField("addedAt", "date"),
        ),
        FilterField.RELEASED: FieldSpec(
            "Release date",
            FieldKind.DATE,
            _ALL_MEDIA,
            _EVERY_SERVER,
            PlexField("originallyAvailableAt", "date"),
        ),
        FilterField.LAST_PLAYED: FieldSpec(
            "Last played",
            FieldKind.DATE,
            _ALL_MEDIA,
            _PLEX,
            PlexField("lastViewedAt", "date"),
        ),
        FilterField.UNPLAYED: FieldSpec(
            "Unplayed",
            FieldKind.BOOLEAN,
            _ALL_MEDIA,
            _PLEX,
            PlexField("unwatched", "boolean"),
        ),
        FilterField.IN_PROGRESS: FieldSpec(
            "In progress",
            FieldKind.BOOLEAN,
            _ALL_MEDIA,
            _PLEX,
            PlexField("inProgress", "boolean"),
        ),
    }
)

OPERATORS: frozendict[FieldKind, tuple[FilterOperator, ...]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        FieldKind.TEXT: (
            FilterOperator.IS,
            FilterOperator.IS_NOT,
            FilterOperator.CONTAINS,
            FilterOperator.DOES_NOT_CONTAIN,
            FilterOperator.STARTS_WITH,
            FilterOperator.ENDS_WITH,
        ),
        FieldKind.TAG: (FilterOperator.IS, FilterOperator.IS_NOT),
        FieldKind.NUMBER: (
            FilterOperator.IS,
            FilterOperator.IS_NOT,
            FilterOperator.GT,
            FilterOperator.GTE,
            FilterOperator.LT,
            FilterOperator.LTE,
        ),
        FieldKind.DATE: (
            FilterOperator.IN_LAST,
            FilterOperator.NOT_IN_LAST,
            FilterOperator.BEFORE,
            FilterOperator.AFTER,
        ),
        FieldKind.BOOLEAN: (FilterOperator.IS, FilterOperator.IS_NOT),
    }
)

#: Jellyfin and Emby call Plex's labels tags.
_SERVER_LABELS: frozendict[tuple[ServerType, FilterField], str] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        (ServerType.JELLYFIN, FilterField.LABEL): "Tag",
        (ServerType.EMBY, FilterField.LABEL): "Tag",
    }
)


def field_label(field: FilterField, server: ServerType) -> str:
    """Name a field as the media server names it."""
    return _SERVER_LABELS.get((server, field), FIELDS[field].label)


def field_available(
    field: FilterField, server: ServerType, media_type: MediaType, *, smart: bool
) -> bool:
    """Whether a collection evaluated by Overture, or by Plex if smart, can test it."""
    spec = FIELDS[field]
    if media_type not in spec.media_types:
        return False
    if smart:
        return server is ServerType.PLEX and spec.plex is not None
    return server in spec.local


@dataclass(slots=True, frozen=True)
class DimensionSpec:
    """What a collection set enumerates, and how it titles each collection."""

    label: str
    #: The field each collection tests; franchises test a TMDB source instead.
    field: FilterField | None
    title_format: str = "{value}"
    #: Order values as numbers, newest first, rather than alphabetically.
    numeric: bool = False


DIMENSIONS: frozendict[SetDimension, DimensionSpec] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        SetDimension.DECADE: DimensionSpec(
            "Decades", FilterField.DECADE, "{value}s", numeric=True
        ),
        SetDimension.YEAR: DimensionSpec("Years", FilterField.YEAR, numeric=True),
        SetDimension.GENRE: DimensionSpec("Genres", FilterField.GENRE),
        SetDimension.STUDIO: DimensionSpec("Studios", FilterField.STUDIO),
        SetDimension.COUNTRY: DimensionSpec("Countries", FilterField.COUNTRY),
        SetDimension.CONTENT_RATING: DimensionSpec(
            "Content ratings", FilterField.CONTENT_RATING
        ),
        SetDimension.RESOLUTION: DimensionSpec("Resolutions", FilterField.RESOLUTION),
        SetDimension.LABEL: DimensionSpec("Labels", FilterField.LABEL),
        SetDimension.ACTOR: DimensionSpec("Actors", FilterField.ACTOR),
        SetDimension.DIRECTOR: DimensionSpec("Directors", FilterField.DIRECTOR),
        SetDimension.WRITER: DimensionSpec("Writers", FilterField.WRITER),
        SetDimension.PRODUCER: DimensionSpec("Producers", FilterField.PRODUCER),
        SetDimension.FRANCHISE: DimensionSpec("TMDB franchises", None),
    }
)


def dimension_available(
    dimension: SetDimension, server: ServerType, media_type: MediaType
) -> bool:
    """Sets enumerate values from synced metadata, so the field must be local."""
    field = DIMENSIONS[dimension].field
    if field is None:
        return media_type is MediaType.MOVIE
    return field_available(field, server, media_type, smart=False)


#: Orders Overture computes from synced metadata for regular collections.
_LOCAL_ORDER_FIELDS: frozendict[str, FilterField | None] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "release": FilterField.RELEASED,
        "title": FilterField.TITLE,
        "added": FilterField.ADDED,
        "critic_rating": FilterField.CRITIC_RATING,
        "audience_rating": FilterField.AUDIENCE_RATING,
        "user_rating": FilterField.USER_RATING,
        "duration": FilterField.DURATION,
        "plays": FilterField.PLAYS,
        "last_played": FilterField.LAST_PLAYED,
        "random": None,
    }
)

#: The orders Jellyfin and Emby store on a collection, as their DisplayOrder.
SERVER_NATIVE_ORDERS: frozendict[ServerType, frozenset[CollectionOrder]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        ServerType.JELLYFIN: frozenset(
            {CollectionOrder.RELEASE_ASC, CollectionOrder.TITLE_ASC}
        ),
        ServerType.EMBY: frozenset(
            {CollectionOrder.RELEASE_ASC, CollectionOrder.TITLE_ASC}
        ),
    }
)


def order_field(order: CollectionOrder) -> FilterField | None:
    """The field an order sorts by; ``None`` for custom and random orders."""
    return _LOCAL_ORDER_FIELDS.get(order.value.partition(".")[0])


def available_orders(
    server: ServerType, media_type: MediaType, *, smart: bool
) -> list[CollectionOrder]:
    """Orders a collection can use on the server.

    Plex keeps any order Overture computes as a custom order and sorts smart
    collections itself; Jellyfin and Emby offer only their display orders.
    """
    if server in SERVER_NATIVE_ORDERS:
        return [
            order for order in CollectionOrder if order in SERVER_NATIVE_ORDERS[server]
        ]
    return [
        order
        for order in CollectionOrder
        if (order is CollectionOrder.CUSTOM and not smart)
        or (
            order is not CollectionOrder.CUSTOM
            and (
                (field := order_field(order)) is None
                or field_available(field, server, media_type, smart=smart)
            )
        )
    ]
