"""Consumed provider fields, validated before library reconciliation.

Unknown fields belong to the provider and are ignored. Optional fields allow
partial metadata responses.
"""

lazy from dataclasses import dataclass
lazy from typing import Annotated, Any, Required, TypedDict

lazy from pydantic import Field, TypeAdapter, ValidationError

lazy from .errors import MediaServerError

type Identifier = Annotated[str, Field(min_length=1)]
type Count = Annotated[int, Field(ge=0)]


@dataclass(slots=True, frozen=True)
class Page[T]:
    items: list[T]
    total: int | None = None
    offset: int | None = None


def parse_wire[T](adapter: TypeAdapter[T], payload: object) -> T:
    try:
        return adapter.validate_python(payload, strict=True)
    except ValidationError as exc:
        raise MediaServerError("Media server returned malformed metadata") from exc


_OBJECT = TypeAdapter(dict[str, Any])


def wire_object(payload: object) -> dict[str, Any]:
    return parse_wire(_OBJECT, payload)


class PlexPart(TypedDict, total=False):
    file: str


class PlexMedia(TypedDict, total=False):
    Part: list[PlexPart] | None
    videoResolution: str | None
    audioCodec: str | None


class PlexLocation(TypedDict, total=False):
    path: str


class PlexGuid(TypedDict, total=False):
    id: str


class PlexDirector(TypedDict, total=False):
    tag: str


class PlexMetadata(TypedDict, total=False):
    ratingKey: Required[Identifier | int]
    title: str
    titleSort: str | None
    smart: bool | str | int | None
    collectionMode: int | str | None
    collectionSort: int | str | None
    collectionFilterBasedOnUser: int | str | None
    year: int | None
    index: int
    thumb: str | None
    art: str | None
    theme: str | None
    summary: str | None
    contentRating: str | None
    rating: float | int | None
    audienceRating: float | int | None
    userRating: float | int | None
    editionTitle: str | None
    duration: int | None
    viewCount: int | None
    viewOffset: int | None
    lastViewedAt: int | None
    originallyAvailableAt: str | None
    childCount: int | None
    leafCount: int | None
    viewedLeafCount: int | None
    studio: str | None
    Genre: list[PlexDirector] | None
    Role: list[PlexDirector] | None
    Writer: list[PlexDirector] | None
    Producer: list[PlexDirector] | None
    Country: list[PlexDirector] | None
    Label: list[PlexDirector] | None
    librarySectionID: str | int
    addedAt: int | None
    updatedAt: int | None
    Guid: list[PlexGuid] | None
    Director: list[PlexDirector] | None
    Location: list[PlexLocation] | None
    Media: list[PlexMedia] | None
    Children: PlexChildren | None


class PlexChildren(TypedDict, total=False):
    Metadata: list[PlexMetadata]


class MediaBrowserPerson(TypedDict, total=False):
    Name: str | None
    Type: str | None


class MediaBrowserStudio(TypedDict, total=False):
    Name: str | None


class MediaBrowserItem(TypedDict, total=False):
    Id: Required[Identifier]
    Name: str | None
    Overview: str | None
    Path: str | None
    IsFolder: bool
    ProductionYear: int | None
    ProviderIds: dict[str, str] | None
    ImageTags: dict[str, str] | None
    BackdropImageTags: list[str] | None
    People: list[MediaBrowserPerson] | None
    Studios: list[MediaBrowserStudio] | None
    Genres: list[str] | None
    Tags: list[str] | None
    ProductionLocations: list[str] | None
    OfficialRating: str | None
    CommunityRating: float | int | None
    CriticRating: float | int | None
    Width: int | None
    PremiereDate: str | None
    DateCreated: str | None
    DateLastMediaAdded: str | None
    DateModified: str | None
    Etag: str | None
    SeriesId: str | None
    SeasonId: str | None
    IndexNumber: int | None
    RunTimeTicks: int | None


class PlexSection(TypedDict, total=False):
    key: Required[Identifier | int]
    type: Required[Identifier]
    title: str


class MediaBrowserSection(TypedDict, total=False):
    ItemId: Required[Identifier]
    Name: str | None
    CollectionType: str | None


class RemoteImage(TypedDict, total=False):
    Url: Required[str]
    ThumbnailUrl: str | None
    Width: int | None
    Height: int | None


class RemoteImages(TypedDict, total=False):
    Images: Required[list[RemoteImage] | None]
    TotalRecordCount: Count


class PlexContainer(TypedDict, total=False):
    Metadata: list[PlexMetadata]
    totalSize: Count
    offset: Count
    size: int | str


class PlexSectionsContainer(TypedDict, total=False):
    Directory: list[PlexSection]
    totalSize: Count
    offset: Count
    size: int | str


class PlexArtwork(TypedDict, total=False):
    key: str
    thumb: str
    width: int | None
    height: int | None


class PlexArtworkContainer(TypedDict, total=False):
    Metadata: list[PlexArtwork]
    totalSize: Count
    offset: Count
    size: int | str


class PlexArtworkResponse(TypedDict):
    MediaContainer: PlexArtworkContainer


class MediaBrowserIdentity(TypedDict):
    Id: Identifier


class PlexIdentityContainer(TypedDict):
    machineIdentifier: Identifier


class PlexIdentity(TypedDict):
    MediaContainer: PlexIdentityContainer


class PlexConnection(TypedDict, total=False):
    uri: str
    address: str
    port: int
    local: bool


class PlexResource(TypedDict, total=False):
    provides: str
    clientIdentifier: str
    owned: bool
    connections: list[PlexConnection] | None


class PlexResponse(TypedDict):
    MediaContainer: PlexContainer


class PlexSectionsResponse(TypedDict):
    MediaContainer: PlexSectionsContainer


class MediaBrowserResponse(TypedDict, total=False):
    Items: Required[list[MediaBrowserItem] | None]
    TotalRecordCount: Count
    StartIndex: Count


class MediaBrowserSections(TypedDict, total=False):
    Items: Required[list[MediaBrowserSection]]
    TotalRecordCount: Count


_PLEX_RESPONSE = TypeAdapter(PlexResponse)
_PLEX_SECTIONS_RESPONSE = TypeAdapter(PlexSectionsResponse)
_MEDIA_BROWSER_RESPONSE = TypeAdapter(MediaBrowserResponse)
_MEDIA_BROWSER_SECTIONS = TypeAdapter(MediaBrowserSections)
MEDIA_BROWSER_SECTION_LIST = TypeAdapter(list[MediaBrowserSection])
_REMOTE_IMAGES = TypeAdapter(RemoteImages)
_PLEX_ARTWORK = TypeAdapter(PlexArtworkResponse)
_MEDIA_BROWSER_IDENTITY = TypeAdapter(MediaBrowserIdentity)
_PLEX_IDENTITY = TypeAdapter(PlexIdentity)
_PLEX_RESOURCES = TypeAdapter(list[PlexResource])


def plex_items(payload: object) -> list[PlexMetadata]:
    return plex_page(payload).items


def _plex_container_page(
    adapter: TypeAdapter[Any], payload: object, key: str, malformed: str
) -> Page[Any]:
    """Return one page of a Plex ``MediaContainer`` listing under *key*.

    Plex leaves the list out of an empty page, so a missing list is only
    accepted alongside an explicit zero size.
    """
    container = parse_wire(adapter, payload)["MediaContainer"]
    if key not in container and container.get("size") not in {0, "0"}:
        raise MediaServerError(malformed)
    return Page(
        container.get(key, []), container.get("totalSize"), container.get("offset")
    )


def plex_page(payload: object) -> Page[PlexMetadata]:
    return _plex_container_page(
        _PLEX_RESPONSE,
        payload,
        "Metadata",
        "Plex returned no metadata listing or explicit empty count",
    )


def plex_sections_page(payload: object) -> Page[PlexSection]:
    return _plex_container_page(
        _PLEX_SECTIONS_RESPONSE,
        payload,
        "Directory",
        "Media server returned malformed library sections",
    )


def plex_artwork_page(payload: object) -> Page[PlexArtwork]:
    return _plex_container_page(
        _PLEX_ARTWORK, payload, "Metadata", "Plex returned malformed artwork metadata"
    )


def plex_machine_identifier(payload: object) -> str:
    return parse_wire(_PLEX_IDENTITY, payload)["MediaContainer"]["machineIdentifier"]


def plex_resources(payload: object) -> list[PlexResource]:
    return parse_wire(_PLEX_RESOURCES, payload)


def media_browser_server_id(payload: object) -> str:
    return parse_wire(_MEDIA_BROWSER_IDENTITY, payload)["Id"]


def media_browser_items(payload: object) -> list[MediaBrowserItem]:
    page = media_browser_page(payload)
    if page.offset not in {None, 0} or page.total not in {None, len(page.items)}:
        raise MediaServerError("Media server returned an incomplete listing")
    return page.items


def media_browser_page(payload: object) -> Page[MediaBrowserItem]:
    response = parse_wire(_MEDIA_BROWSER_RESPONSE, payload)
    return Page(
        response["Items"] or [],
        response.get("TotalRecordCount"),
        response.get("StartIndex"),
    )


def media_browser_sections_page(payload: object) -> Page[MediaBrowserSection]:
    response = parse_wire(_MEDIA_BROWSER_SECTIONS, payload)
    return Page(response["Items"], response.get("TotalRecordCount"))


def remote_images_page(payload: object) -> Page[RemoteImage]:
    response = parse_wire(_REMOTE_IMAGES, payload)
    return Page(response["Images"] or [], response.get("TotalRecordCount"))
