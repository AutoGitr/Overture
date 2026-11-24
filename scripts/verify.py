"""Check Overture end to end against its media servers, read only.

Point it at a synced Overture, and at the media servers MEDIA_SERVERS names
(one each of Plex, Jellyfin and Emby). Each server Overture names is checked
on its own, against the given server of its kind. Overture is
asked through its own API, so every result comes from the code users run; each
media server is asked directly, so Overture's answers are compared with the
server's own:

- **Inventory**: the libraries, every item and every collection Overture lists
  are the ones the server holds, with the members, title, kind and theme the
  server holds. A collection the server holds that Overture leaves out is
  named with why: a separator, an empty one, one of other items, or an
  unmanaged one while importing them is off.
- **Fields**: every field and operator previews in every library; on Plex a
  field both evaluators know is previewed by Overture and by Plex, the counts
  must agree, and where they differ the range of years is narrowed until the
  title they disagree on is found, shown with the values Plex holds for it and
  whether Plex lists the value at all. Where Plex refuses a text value, the
  value is sent to Plex directly to show which character it refuses. On
  Jellyfin and Emby the fields the server filters on are counted by the
  server as well.
- **Values**: every tag and text field lists its values, and they include every
  value the server lists for its own filters; on Plex, the values Overture
  offers that Plex does not list, which no smart collection can select, are
  noted.
- **Orders**: every order previews; where Overture and Plex both sort, their
  first members are compared (ties may legitimately differ).
- **Kinds**: the kind recommended for each condition is the one Overture's
  rule names: smart where Plex tests it itself or only Plex can, regular where
  Overture evaluates it, including through labels.
- **Sources and sets**: Radarr and Sonarr tags, every TMDB chart, any given
  sources and every set dimension, with the defaults it starts with, preview.
- **Collections**: in each library, each managed collection's rule previews to
  the members the server's copy holds; each unmanaged one plans an adoption
  whose criteria the editor offers and that selects what the server holds;
  every poster and background Overture serves, from the server or its own
  cache, loads.
- **OvertureDB**: a sample of each library's contribution issues are links to
  the OvertureDB form of their media type.
- **What the server offers**: every Plex filter, field, sort and operator is one
  Overture can use; every Jellyfin and Emby filter is one Overture offers.
- **TMDB, MDBList, Radarr and Sonarr**, each read directly when its key is set:
  every TMDB chart Overture offers or lacks, genres, watch providers,
  collection search and one title's details; MDBList's limits, lists, list
  items, list search and one title's details, including whether it names a
  franchise; Radarr's and Sonarr's tags, quality profiles and root folders
  against those Overture offers, and their import lists.

Where Plex itself answers a condition differently from what it means
elsewhere, the difference is noted with the reason rather than reported.

It changes nothing unless asked. Overture is signed in to with API keys, which
read and preview but never change; media servers and every other service are
only sent GET requests, and any other Overture request is refused before it is
sent.

- **Writes**, only with ``--write``: what reading cannot show, how each media
  server takes Overture's own collection writes. Overture's media server
  clients, the code a sync runs, create a regular collection and on Plex a
  smart one, change and order their members, edit their title, sort title,
  summary and order (and on Plex its Home visibility), upload a poster and a
  background, change the smart one's filter and delete them, reading the
  server itself back after each step. Each step is reported on its own, with
  the request the server refused. Everything they make is titled "zz Overture
  verify" and deleted at the end, whatever fails; one left by a run that was
  killed is deleted first. No item, library or other collection is changed.

Create an Overture key under API keys in the menu, and give each media
server's address and its token or API key. For Overture with Plex, Jellyfin
and Emby in MEDIA_SERVERS:

    OVERTURE_API_KEY=key \
        PLEX_TOKEN=... \
        JELLYFIN_API_KEY=... \
        EMBY_API_KEY=... \
        RADARR_API_KEY=... \
        SONARR_API_KEY=... \
        uv run python -m scripts.verify \
        http://localhost:5885 \
        --plex https://localhost:32400 --insecure \
        --jellyfin http://localhost:8096 \
        --emby http://localhost:8095 \
        --radarr http://localhost:7878 \
        --sonarr http://localhost:8989 \
        --report verify.md

Set TMDB_READ_ACCESS_TOKEN and MDBLIST_API_KEY to probe those APIs too, and pass
--radarr and --sonarr with RADARR_API_KEY and SONARR_API_KEY to compare them.

A server that is not given, or one of several of its kind in MEDIA_SERVERS,
is checked through Overture alone. Pass --sources with a JSON file of source
objects (as the API takes them) to test TMDB, MDBList and person sources, and
--insecure to skip TLS certificate verification.
"""

lazy import argparse
lazy import asyncio
lazy import json
lazy import os
lazy import sys
lazy from collections.abc import Awaitable, Callable, Iterator
lazy from dataclasses import dataclass, field
lazy from pathlib import Path
lazy from typing import Any
lazy from urllib.parse import parse_qs, unquote, urlsplit

lazy import httpx2

lazy from overture.catalog_contract.contract import ISSUE_FORMS
lazy from overture.config import Settings
lazy from overture.domain import (
    ArtStyle,
    ArtType,
    CollectionMode,
    CollectionOrder,
    MediaType,
)
lazy from overture.media_servers.adapters import CollectionDetails
lazy from overture.media_servers.base import BaseMediaServerProvider
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.plex.client import PLEX_CUSTOM_SORT
lazy from overture.media_servers.plex.query import (
    compile_plex_query,
    plex_field_keys,
    plex_operators,
    plex_sort,
)
lazy from overture.media_servers.registry import ProviderRegistry
lazy from overture.schemas.collections import CollectionRuleWrite, FilterGroup
lazy from overture.utils.collection_fields import FIELDS, PlexFieldType
lazy from overture.utils.generated_art import render_art
lazy from overture.utils.http_security import API_KEY_HEADER
lazy from scripts.json_values import is_array, is_object

#: Operands for operators that compare numbers, days or dates.
NUMBER_VALUE = 5
DAYS_VALUE = 365
DATE_VALUE = "2000-01-01"
#: A condition every dated item meets, to preview orders over a whole library.
EVERYTHING = {"kind": "field", "field": "year", "operator": "gt", "value": 0}
#: Art sources whose image Overture keeps itself, not in a media folder or a link.
KEPT_SOURCES = frozenset({"upload", "generated"})
#: Members compared between Overture's and Plex's order.
ORDER_DEPTH = 5
#: Values each set dimension enumerates.
SET_TOP = 3
#: Items per library whose contribution issue is read.
ISSUE_SAMPLE = 10
#: Missing or extra IDs a mismatch names.
NAMED = 5
#: The title every collection the write check makes starts with.
WRITE_PREFIX = "zz Overture verify"
#: Members of the large collection the write check makes: enough that their
#: IDs overflow one request target, so writes must be batched.
LARGE_COLLECTION = 500
#: Plex's page size when listing a section's items.
PLEX_PAGE = 500
#: Conditions Plex answers by rules of its own, which no evaluator can share.
PLEX_DIFFERS: dict[tuple[str, str], str] = {
    ("title", "contains"): (
        "Plex's title contains matches words starting with the text, in the "
        "title and original title, while its does not contain matches any part"
    ),
    ("plays", "is_not"): (
        "Plex keeps no play count for titles never played, rated or resumed, "
        "so is not leaves them out"
    ),
}
#: Plex filters and sorts Overture leaves out by choice, and why; an episode's
#: form of a key without its own entry shares the key's.
_MAINTENANCE = "it tells the library's upkeep, not what a collection holds"
_EPISODE_OF_SHOW = "a show collection tests the show's own value"
PLEX_KNOWN_GAPS: dict[str, str] = {
    "duplicate": _MAINTENANCE,
    "trash": _MAINTENANCE,
    "unmatched": _MAINTENANCE,
    "location": (
        "Plex offers only the library's root folders, and Folder tests any path"
    ),
    "episode.title": _EPISODE_OF_SHOW,
    "episode.year": _EPISODE_OF_SHOW,
    "episode.originallyAvailableAt": _EPISODE_OF_SHOW,
    "episode.userRating": _EPISODE_OF_SHOW,
    "episode.viewCount": _EPISODE_OF_SHOW,
    "episode.collection": _EPISODE_OF_SHOW,
    "episode.unwatched": "Unplayed tests a show's unplayed episodes",
    "mediaHeight": "a collection is rarely wanted in order of resolution",
}
#: Fields whose regular evaluation reads play state as of the last library sync.
PLAY_STATE = frozenset({"in_progress", "unplayed", "plays", "last_played"})
#: The scopes Plex lists a section's filters, fields and sorts under.
PLEX_SCOPES = frozenset({"movie", "show", "season", "episode"})
PLEX_TYPES = {"movie": 1, "show": 2}
PLEX_EPISODE = 4
#: The Plex field types Overture writes; Plex types its media fields by name.
PLEX_FIELD_TYPES: frozenset[PlexFieldType] = frozenset(
    {"string", "tag", "integer", "float", "date", "boolean"}
)
#: Values per field Plex is asked whether any title holds.
VALUE_PROBES = 20
#: Characters Plex may refuse in a text value, each probed on its own.
PLEX_TEXT_PROBES = ("'", "!", "&", '"', "%")
#: Where a title's metadata holds a filter's tags, when not under its name.
PLEX_TAGS = {"actor": "Role", "contentRating": "contentRating"}
#: The overture field each Jellyfin and Emby item filter tests, by the filter's
#: query parameter and the name ``/Items/Filters`` lists its values under.
MEDIA_BROWSER_FILTERS: dict[str, tuple[str, str]] = {
    "genre": ("Genres", "Genres"),
    "label": ("Tags", "Tags"),
    "content_rating": ("OfficialRatings", "OfficialRatings"),
    "year": ("Years", "Years"),
}
MEDIA_BROWSER_TYPES = {"movie": "Movie", "show": "Series"}
#: The filters testing what each server holds of its own copy of a title; the
#: lead server gives the rest of the details of the titles it holds.
PER_COPY = frozenset({"label"})
LEAD_DETAILS = "the lead server gives the details of the titles it holds too"
#: The Overture requests that only read, besides GET.
OVERTURE_READS = frozenset(
    {
        "/api/collections/preview",
        "/api/collections/sets/preview",
        "/api/collections/recommend-kind",
    }
)


@dataclass(slots=True)
class Case:
    """One check and what came of it."""

    server: str
    library: str
    check: str
    label: str
    #: Members Overture counts, Plex counts and the server holds.
    count: int | None = None
    smart_count: int | None = None
    held: int | None = None
    members: list[str] = field(default_factory=list[str])
    error: str = ""
    #: Worth a look, but not necessarily wrong.
    note: str = ""
    #: Why the counts may differ, where Plex answers by rules of its own.
    differs: str = ""

    @property
    def mismatch(self) -> bool:
        counts = {self.count, self.smart_count, self.held} - {None}
        return len(counts) > 1

    @property
    def problem(self) -> str:
        if self.error:
            return self.error
        return "counts differ" if self.mismatch and not self.differs else ""


class ApiError(RuntimeError):
    """A failed request, with the API's message."""


class WriteRefusedError(RuntimeError):
    """An Overture request that could change something, refused before it is sent."""


def detail(response: httpx2.Response) -> str:
    """Return the API's error message for a failed response."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    message = body.get("detail") if is_object(body) else None
    return str(message or f"HTTP {response.status_code}")


def named(values: set[str] | list[str]) -> str:
    """Name a few of *values*, and how many there are."""
    shown = sorted(values)[:NAMED]
    more = len(values) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


class Overture:
    """A client of Overture, holding a read-only API key."""

    def __init__(self, base_url: str, api_key: str, *, verify: bool = True) -> None:
        self.client = httpx2.AsyncClient(
            base_url=base_url,
            timeout=300,
            verify=verify,
            headers={API_KEY_HEADER: api_key},
        )

    async def get(self, path: str, **params: Any) -> Any:
        response = await self.client.get(path, params=params)
        if response.status_code >= 400:
            raise ApiError(detail(response))
        return response.json()

    async def status(self, path: str) -> tuple[int, str]:
        """Return the status a GET answers with, and its content type or error."""
        response = await self.client.get(path)
        kind = response.headers.get("content-type", "")
        if response.status_code >= 400:
            return response.status_code, detail(response)
        return response.status_code, kind

    async def post(self, path: str, body: dict[str, Any]) -> Any:
        if path not in OVERTURE_READS:
            raise WriteRefusedError(f"POST {path} is not a read")
        response = await self.client.post(path, json=body)
        if response.status_code >= 400:
            raise ApiError(detail(response))
        return response.json()

    async def preview(
        self, rule: dict[str, Any], collection_id: int | None = None
    ) -> list[dict[str, Any]]:
        """What each of the rule's libraries previews to.

        A saved collection is named, so it never counts as another collection
        holding its own members.
        """
        found = await self.post(
            "/api/collections/preview", {"rule": rule, "collection_id": collection_id}
        )
        return found["libraries"]


class Server:
    """A media server that is only ever read: it has no way to send anything else."""

    def __init__(
        self, base_url: str, headers: dict[str, str], *, verify: bool = True
    ) -> None:
        self.client = httpx2.AsyncClient(
            base_url=base_url,
            timeout=120,
            verify=verify,
            headers={"Accept": "application/json", **headers},
        )

    async def get(self, path: str, **params: Any) -> Any:
        """The only request a media server is sent.

        Without *params* a query written into *path* is sent as it is.
        """
        response = await self.client.get(path, params=params or None)
        response.raise_for_status()
        return response.json()


def failure(exc: Exception) -> str:
    """Name a failure, with the request a server refused and what it answered."""
    cause = exc.__cause__ if isinstance(exc, MediaServerError) else exc
    if not isinstance(cause, httpx2.HTTPStatusError):
        return str(exc)
    request, response = cause.request, cause.response
    answer = " ".join(response.text.split())[:200]
    return (
        f"{exc if cause is not exc else f'HTTP {response.status_code}'}: "
        f"{request.method} {request.url.path} answered {answer!r}"
    )


def item_copy_id(item: dict[str, Any], library_id: str) -> str:
    """The ID of a title's copy in a library, as its server knows it."""
    return next(
        (
            str(copy["server_item_id"])
            for copy in item["copies"]
            if copy["library_id"] == library_id
        ),
        "",
    )


def collection_copy(row: dict[str, Any], library_id: str) -> dict[str, Any] | None:
    """The server collection holding a collection's members in a library."""
    return next(
        (copy for copy in row["copies"] if library_id in copy["library_ids"]), None
    )


def holds_server_theme(row: dict[str, Any], server_id: int | None) -> bool:
    """Whether Overture records a theme on *server_id*'s copy of *row*."""
    return any(
        delivery["server_id"] == server_id and delivery["present"]
        for delivery in row["assets"]["theme"]["deliveries"]
    )


def single(library_id: str, condition: dict[str, Any], **rule: Any) -> dict[str, Any]:
    """A rule of one condition in one library."""
    criteria = {"conditions": [condition]}
    return {"libraries": [{"library_id": library_id, "criteria": criteria}], **rule}


def field_value(kind: str, operator: str, values: list[dict[str, Any]]) -> Any:
    """Return a value the operator can test, from the library where it can."""
    if operator in {"in_last", "not_in_last"}:
        return DAYS_VALUE
    if operator in {"before", "after"}:
        return DATE_VALUE
    if kind == "boolean":
        return True
    if kind in {"number", "date"}:
        return NUMBER_VALUE
    common = max(values, key=lambda entry: entry["count"], default=None)
    if common is None:
        return None
    text = str(common["value"])
    return text[:3] if operator in {"contains", "does_not_contain"} else text


def expected_kind(entry: dict[str, Any], operator: str) -> str:
    """The kind Overture's rule recommends for one condition on Plex.

    A condition only Plex tests needs a smart collection; one Overture
    evaluates, itself or through a label it keeps, suits a regular one unless
    Plex tests it natively.
    """
    native = operator in entry["smart_operators"] and not entry["labelled"]
    return "smart" if native or operator not in entry["operators"] else "regular"


def described(group: dict[str, Any]) -> str:
    """A criteria group as text: its conditions and nested groups."""
    terms = [
        f"{condition['field']} {condition['operator']} {condition['value']!r}"
        if condition.get("kind", "field") == "field"
        else f"{condition['source']['type']} {condition['operator']}"
        for condition in group.get("conditions", [])
    ]
    terms.extend(f"({described(nested)})" for nested in group.get("groups", []))
    return f" {group.get('mode', 'all')} ".join(terms)


def field_conditions(group: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Every field condition in a criteria group and its nested groups."""
    for condition in group.get("conditions", []):
        if condition.get("kind", "field") == "field":
            yield condition
    for nested in group.get("groups", []):
        yield from field_conditions(nested)


def first_difference(
    ours: list[str], theirs: list[str], *, complete: tuple[bool, bool]
) -> tuple[str, bool] | None:
    """The first title one sorted list holds and the other leaves out.

    Returns the title and whether Plex holds it. A list cut short by the
    preview may hold more titles past its end, so none past it are compared.
    """
    ends = [
        members[-1].casefold()
        for members, whole in ((ours, complete[0]), (theirs, complete[1]))
        if members and not whole
    ]
    last = min(ends, default=None)
    for title in sorted({*ours, *theirs}, key=str.casefold):
        if last is not None and title.casefold() > last:
            return None
        if (title in ours) != (title in theirs):
            return title, title in theirs
    return None


@dataclass(slots=True, frozen=True)
class Members:
    """What one evaluator selects: how many, and the first of them by title."""

    count: int
    names: list[str]

    @property
    def whole(self) -> bool:
        return len(self.names) == self.count


@dataclass(slots=True, frozen=True)
class ServerArt:
    """What one server collection shows."""

    poster: bool
    background: bool
    #: Whether it holds a theme; ``None`` where the server keeps none.
    theme: bool | None


@dataclass(slots=True, frozen=True)
class Listing:
    """Why Overture leaves out a collection the server holds."""

    #: Collection groups, by folded name: Plex holds a separator for some.
    groups: frozenset[str]
    import_unmanaged: bool

    def reason(
        self, title: str, members: int | None, subtype: str | None, media_type: str
    ) -> str:
        """Why the collection is left out, or ``""`` when it should be listed."""
        if members == 0:
            return "a separator" if title.casefold() in self.groups else "empty"
        if subtype and subtype != media_type:
            return f"holds {subtype}s"
        if not self.import_unmanaged:
            return "unmanaged, and importing unmanaged collections is off"
        return ""


class Library:
    """The checks of one library in Overture, and on its server."""

    def __init__(
        self,
        overture: Overture,
        server: str,
        capabilities: dict[str, Any],
        media_type: str,
        library: dict[str, Any],
        regular: set[str],
        items: list[dict[str, Any]],
        collections: list[dict[str, Any]],
        direct: PlexServer | MediaBrowserServer | None,
        listing: Listing,
        *,
        lead: bool,
    ) -> None:
        self.overture = overture
        self.server = server
        self.capabilities = capabilities
        self.media_type = media_type
        self.id: str = library["id"]
        #: The server's own key of the library, which its API takes.
        self.key: str = library["id"].partition(":")[2]
        self.name = f"{library['title']} ({media_type})"
        self.plex_smart = bool(capabilities["smart"])
        self.fields = {entry["field"]: entry for entry in capabilities["fields"]}
        #: Regular collections' titles: Plex tests membership of these only.
        self.regular = regular
        self.items = items
        self.collections = collections
        self.direct = direct
        self.listing = listing
        #: Its server leads, so it gives the details of the titles it holds.
        self.lead = lead
        #: The members the server counts in each of its collections, by its ID.
        self.held: dict[str, int] = {}
        #: What the server shows of each of its collections, by its ID.
        self.shown: dict[str, ServerArt] = {}
        self._values: dict[str, list[dict[str, Any]] | ApiError] = {}
        self.cases: list[Case] = []

    def case(self, check: str, label: str) -> Case:
        case = Case(self.server, self.name, check, label)
        self.cases.append(case)
        return case

    async def values(self, field_name: str) -> list[dict[str, Any]]:
        """The values the editor offers for a field, fetched once."""
        if field_name not in self._values:
            try:
                self._values[field_name] = await self.overture.get(
                    "/api/collections/field-values",
                    media_type=self.media_type,
                    library_id=self.id,
                    field=field_name,
                )
            except ApiError as exc:
                self._values[field_name] = exc
        found = self._values[field_name]
        if isinstance(found, ApiError):
            raise found
        return found

    def record(self, case: Case, rule: dict[str, Any], count: int) -> None:
        """Note a count as Plex's when Plex evaluates the rule, else as Overture's."""
        if rule.get("smart") and self.plex_smart:
            case.smart_count = count
        else:
            case.count = count

    async def preview(self, case: Case, rule: dict[str, Any]) -> list[str]:
        """Record what a rule of this library previews to; return its members."""
        try:
            result = (await self.overture.preview(rule))[0]
        except ApiError as exc:
            case.error = str(exc)
            return []
        self.record(case, rule, result["member_count"])
        case.members = result["members"][:ORDER_DEPTH]
        return result["members"]

    async def check(self, extra_sources: list[dict[str, Any]]) -> list[Case]:
        """Run every check of the library; one that fails leaves the others to run."""
        stages: list[tuple[str, Callable[[], Awaitable[None]]]] = [
            ("fields", self.check_fields),
            ("orders", self.check_orders),
            ("sources", lambda: self.check_sources(extra_sources)),
            ("sets", self.check_sets),
            ("issues", self.check_issues),
            ("kept art", self.check_kept_art),
        ]
        if (direct := self.direct) is not None:
            stages.append((direct.server, lambda: direct.check_library(self)))
        for name, stage in stages:
            try:
                await stage()
            except (ApiError, httpx2.HTTPError) as exc:
                self.case("stage", name).error = failure(exc)
        return self.cases

    async def check_fields(self) -> None:
        """Preview every field and operator, by both evaluators where both can."""
        for entry in self.fields.values():
            values: list[dict[str, Any]] = []
            if entry["kind"] in {"tag", "text"}:
                case = self.case("values", entry["label"])
                try:
                    values = await self.values(entry["field"])
                except ApiError as exc:
                    case.error = str(exc)
                    continue
                case.note = f"{len(values)} values"
            if entry["field"] == "collection" and self.plex_smart and entry["smart"]:
                values = [row for row in values if row["value"] in self.regular]
            local: list[str] = entry["operators"] if entry["local"] else []
            smart: list[str] = entry["smart_operators"] if self.plex_smart else []
            for operator in dict.fromkeys([*local, *smart]):
                value = field_value(entry["kind"], operator, values)
                label = f"{entry['label']} {operator} {value!r}"
                case = self.case("field", label)
                if value is None:
                    case.note = "no value in the library to test"
                    continue
                condition = {
                    "kind": "field",
                    "field": entry["field"],
                    "operator": operator,
                    "value": value,
                }
                await self.check_recommendation(
                    condition, expected_kind(entry, operator)
                )
                if operator in local and operator in smart:
                    await self.compare(entry, condition, case)
                else:
                    await self.preview(
                        case, single(self.id, condition, smart=operator in smart)
                    )
                if (
                    isinstance(self.direct, PlexServer)
                    and entry["kind"] == "text"
                    and "HTTP 500" in case.error
                ):
                    case.note = await self.direct.refused(self, condition)

    async def compare(
        self, entry: dict[str, Any], condition: dict[str, Any], case: Case
    ) -> None:
        """Preview by both evaluators, and name a title they disagree on."""
        case.differs = PLEX_DIFFERS.get((entry["field"], condition["operator"]), "")
        # Both in one order, so the first title they disagree on shows why.
        ordered = {"order_type": CollectionOrder.TITLE_ASC.value}
        ours = await self.preview(case, single(self.id, condition, **ordered))
        theirs = await self.preview(
            case, single(self.id, condition, smart=True, **ordered)
        )
        if not case.mismatch or case.count is None or case.smart_count is None:
            return
        if case.differs:
            case.note = case.differs
        elif isinstance(self.direct, PlexServer):
            case.note = await self.disagreement(
                entry,
                condition,
                Members(case.count, ours),
                Members(case.smart_count, theirs),
            )
        if entry["field"] in PLAY_STATE:
            # A regular collection reads play state as of the last sync, by
            # design, so the two differ until the next one.
            case.differs = "play state"
            case.note = (
                "Overture reads play state as of the last library sync; "
                "sync and run again. " + case.note
            ).strip()

    async def disagreement(
        self,
        entry: dict[str, Any],
        condition: dict[str, Any],
        ours: Members,
        theirs: Members,
    ) -> str:
        """Name the first title the evaluators disagree on, with Plex's values."""
        assert isinstance(self.direct, PlexServer)
        try:
            span, ours, theirs = await self.narrow(condition, ours, theirs)
        except ApiError as exc:
            return f"the years could not be narrowed: {exc}"
        if ours.count == theirs.count:
            return "the titles that differ have no year"
        where = (
            ""
            if span is None
            else f"in {span[0]}: "
            if span[0] == span[1]
            else f"in {span[0]}-{span[1]}: "
        )
        difference = first_difference(
            ours.names, theirs.names, complete=(ours.whole, theirs.whole)
        )
        if difference is None:
            return where + "the first members agree; the titles that differ sort later"
        return where + await self.direct.explain(
            self, entry, condition["value"], difference
        )

    async def members(
        self, condition: dict[str, Any], years: tuple[int, int], *, smart: bool
    ) -> Members:
        """What one evaluator selects of the titles released in *years*."""
        criteria = {
            "conditions": [
                condition,
                {
                    "kind": "field",
                    "field": "year",
                    "operator": "gte",
                    "value": years[0],
                },
                {
                    "kind": "field",
                    "field": "year",
                    "operator": "lte",
                    "value": years[1],
                },
            ]
        }
        rule = {
            "libraries": [{"library_id": self.id, "criteria": criteria}],
            "order_type": CollectionOrder.TITLE_ASC.value,
            "smart": smart,
        }
        found = (await self.overture.preview(rule))[0]
        return Members(found["member_count"], found["members"])

    async def narrow(
        self, condition: dict[str, Any], ours: Members, theirs: Members
    ) -> tuple[tuple[int, int] | None, Members, Members]:
        """The years whose members both evaluators name in full, and those members.

        A preview names only its first members, so the years are halved, to
        the half whose counts differ, until both lists are whole there.
        """
        years = sorted({item["year"] for item in self.items if item.get("year")})
        if not years or (ours.whole and theirs.whole):
            return None, ours, theirs
        span = (years[0], years[-1])
        ours = await self.members(condition, span, smart=False)
        theirs = await self.members(condition, span, smart=True)
        while (
            ours.count != theirs.count
            and not (ours.whole and theirs.whole)
            and span[0] < span[1]
        ):
            middle = (span[0] + span[1]) // 2
            low = (span[0], middle)
            ours = await self.members(condition, low, smart=False)
            theirs = await self.members(condition, low, smart=True)
            if ours.count != theirs.count:
                span = low
                continue
            span = (middle + 1, span[1])
            ours = await self.members(condition, span, smart=False)
            theirs = await self.members(condition, span, smart=True)
        return span, ours, theirs

    async def check_recommendation(
        self, condition: dict[str, Any], expected: str
    ) -> None:
        """The kind recommended for a condition must be the one the rule names."""
        if not self.plex_smart:
            return
        case = self.case("kind", f"{condition['field']} {condition['operator']}")
        try:
            advice = await self.overture.post(
                "/api/collections/recommend-kind",
                {"rule": single(self.id, condition)},
            )
        except ApiError as exc:
            case.error = str(exc)
            return
        kind = advice["kind"] if advice else None
        case.note = advice["reason"] if advice else "no recommendation"
        if kind != expected:
            case.error = f"recommends {kind or 'nothing'}, expected {expected}"

    async def check_orders(self) -> None:
        """Preview every order; compare Overture's and Plex's first members."""
        regular = set(self.capabilities["orders"]) - {"custom"}
        smart: set[str] = (
            set(self.capabilities["smart_orders"]) if self.plex_smart else set()
        )
        for order in sorted(regular | smart):
            case = self.case("order", order)
            members: dict[bool, list[str]] = {}
            for is_smart in (False, True):
                if order in (smart if is_smart else regular):
                    members[is_smart] = (
                        await self.preview(
                            case,
                            single(
                                self.id, EVERYTHING, order_type=order, smart=is_smart
                            ),
                        )
                    )[:ORDER_DEPTH]
            if (
                order != "random"
                and len(members) == 2
                and members[False] != members[True]
            ):
                case.note = "first members differ: Overture {}; Plex {}".format(
                    ", ".join(members[False]), ", ".join(members[True])
                )

    async def check_sources(self, extra: list[dict[str, Any]]) -> None:
        """Preview the tags and charts found, then the sources given."""
        sources: list[tuple[str, dict[str, Any]]] = []
        arr = "radarr" if self.media_type == "movie" else "sonarr"
        if self.capabilities["arr"]:
            tags = await self.overture.get(f"/api/collections/tags/{arr}")
            if tags:
                first = tags[0]["label"]
                sources.append(
                    (f"{arr} tag {first}", {"type": f"{arr}_tag", "tags": [first]})
                )
        sources.extend(
            (
                f"TMDB chart {chart}",
                {"type": "tmdb_chart", "chart": chart, "limit": 50},
            )
            for chart in self.capabilities["charts"]
        )
        sources.extend((f"{source['type']} (given)", source) for source in extra)
        for label, source in sources:
            case = self.case("source", label)
            await self.preview(
                case,
                single(self.id, {"kind": "source", "operator": "is", "source": source}),
            )
            if case.count == 0:
                case.note = "selects nothing in this library"

    async def check_sets(self) -> None:
        """Preview a set of every dimension the library offers."""
        for dimension in self.capabilities["dimensions"]:
            if dimension["dimension"] == "custom":
                continue
            await self.preview_set(
                self.case("set", dimension["label"]),
                {
                    "dimension": dimension["dimension"],
                    "top": SET_TOP,
                    "title_format": dimension["title_format"],
                    "strip_prefix": dimension["strip_prefix"],
                    "strip_suffix": dimension["strip_suffix"],
                    "smart": dimension["smart_only"],
                },
            )

    async def preview_set(self, case: Case, generator: dict[str, Any]) -> None:
        try:
            entries = await self.overture.post(
                "/api/collections/sets/preview",
                {"generator": {**generator, "library_ids": [self.id]}},
            )
        except ApiError as exc:
            case.error = str(exc)
            return
        case.members = [
            f"{entry['title']} ({entry['member_count']})" for entry in entries
        ][:ORDER_DEPTH]
        if not entries:
            case.note = "no collections"

    async def check_kept_art(self) -> None:
        """Every uploaded or generated image a title or collection chose loads.

        Overture holds the only copy of an upload, and draws generated art
        again when the cache lost it.
        """
        targets = [
            (f"/api/library/items/{item['id']}", item) for item in self.items
        ] + [(f"/api/collections/{row['id']}", row) for row in self.collections]
        checked = 0
        lost: list[str] = []
        for base, owner in targets:
            for art in ("poster", "background"):
                asset = owner["assets"][art]
                if asset["source"] not in KEPT_SOURCES:
                    continue
                checked += 1
                file = asset.get("file")
                digest = file["hash"] if file else asset["content_hash"]
                status, kind = (
                    await self.overture.status(f"{base}/local-image/{art}?t={digest}")
                    if digest
                    else (0, "no image recorded")
                )
                if status != 200 or not kind.startswith("image/"):
                    lost.append(f"{owner['title']} {art} ({kind or status})")
        case = self.case("kept art", "uploaded and generated art")
        case.count = checked
        if lost:
            case.error = f"Overture lost {named(lost)}"

    async def check_issues(self) -> None:
        """A sample of contribution issues open the form of their media type."""
        status = await self.overture.get("/api/catalog/status")
        if not status["enabled"]:
            return
        for item in self.items[:ISSUE_SAMPLE]:
            case = self.case("issue", item["title"])
            try:
                issue = await self.overture.get(
                    f"/api/catalog/items/{item['id']}/issue"
                )
            except ApiError as exc:
                case.error = str(exc)
                continue
            if issue["url"] is None:
                case.note = issue["reason"]
                continue
            issue_url: str = issue["url"]
            query = parse_qs(urlsplit(issue_url).query)
            if query.get("template") != [ISSUE_FORMS[self.media_type]]:
                case.error = f"opens {query.get('template')}"
            elif query.get("item_title") != [item["title"]]:
                case.error = "the form's title is not the item's"
            case.note = "; ".join(issue["notes"])

    async def check_collection(self, collection: dict[str, Any]) -> None:
        """Preview a collection's rule, or its adoption, against what it holds here.

        Each server collection is compared on its own: the collection's count
        is of its members on every server, which one server's copy need not
        hold.
        """
        managed = collection["managed"]
        case = self.case(
            "collection" if managed else "adoption",
            f"{collection['title']} ({collection['kind']})",
        )
        copy = collection_copy(collection, self.id)
        if collection["withheld"] or collection["unsynced"] or copy is None:
            case.note = "not on the server"
            return
        path = f"/api/collections/{collection['id']}"
        try:
            if managed:
                saved = (await self.overture.get(path, media_type=self.media_type))[
                    "rule"
                ]
                if saved and saved.get("last_error"):
                    self.case("last sync", collection["title"]).error = saved[
                        "last_error"
                    ]
                self.check_assets(collection, str(copy["server_item_id"]))
                rule = saved and {
                    key: value
                    for key, value in saved.items()
                    if key in CollectionRuleWrite.model_fields
                }
            else:
                plan = await self.overture.get(f"{path}/adopt")
                rule = plan["rule"]
                if plan["tmdb_collection_id"]:
                    case.note = f"TMDB collection {plan['tmdb_collection_id']}"
                await self.check_offered(case, rule["libraries"][0]["criteria"])
        except ApiError as exc:
            case.error = str(exc)
            return
        if rule is None:
            case.error = "managed without a rule"
            return
        if case.error:
            return
        parts = [
            part
            for part in rule["libraries"]
            if part["library_id"] in copy["library_ids"]
        ]
        if not parts:
            case.error = "its rule holds no criteria for this library"
            return
        try:
            found = await self.overture.preview(
                {**rule, "libraries": parts}, collection["id"] if managed else None
            )
        except ApiError as exc:
            case.error = str(exc)
            return
        self.record(case, rule, sum(row["member_count"] for row in found))
        case.members = found[0]["members"][:ORDER_DEPTH]
        if managed and collection["below_minimum"]:
            return
        server_id = str(copy["server_item_id"])
        case.held = self.held.get(
            server_id,
            collection["child_count"] if len(collection["copies"]) == 1 else None,
        )
        if case.mismatch:
            case.note = "; ".join(
                f"{'smart' if rule.get('smart') else 'regular'}: "
                + described(part["criteria"])
                for part in parts
            )

    def check_assets(self, collection: dict[str, Any], server_id: str) -> None:
        """Overture holds what it chose as sent, and the server shows it.

        A choice whose status is not complete is one Overture no longer
        records as on the server, such as one a sync forgot.
        """
        case = self.case("assets", collection["title"])
        problems: list[str] = []
        notes: list[str] = []
        shown = self.shown.get(server_id)
        for art in ("poster", "background"):
            asset = collection["assets"][art]
            if not asset["needed"] or not asset["selected"]:
                continue
            if asset["status"] != "complete":
                problems.append(
                    f"Overture chose a {art} but holds no record of sending it"
                )
            elif shown is not None and not getattr(shown, art):
                problems.append(f"the server shows no {art} Overture sent")
        copy = collection_copy(collection, self.id)
        theme_asset = collection["assets"]["theme"]
        theme = bool(
            theme_asset["selected"]
            or holds_server_theme(collection, copy["server_id"] if copy else None)
        )
        if shown is not None and shown.theme is not None:
            if theme and not shown.theme:
                problems.append("the server holds none of the theme Overture holds")
            elif shown.theme and not theme:
                notes.append("the server holds a theme Overture does not know")
        case.error = "; ".join(problems)
        case.note = "; ".join(notes)

    async def check_images(self, collection: dict[str, Any]) -> None:
        """Every image Overture links a collection to must load."""
        base = f"/api/collections/{collection['id']}"
        for art in ("poster", "background"):
            for label, url in (
                (
                    "from the server",
                    (version := collection[f"server_{art}_version"])
                    and f"{base}/image/{art}?t={version}",
                ),
                (
                    "Overture uploaded",
                    (digest := collection["assets"][art]["content_hash"])
                    and f"{base}/local-image/{art}?t={digest}",
                ),
            ):
                if not url:
                    continue
                case = self.case("image", f"{collection['title']} {art} {label}")
                status, kind = await self.overture.status(url)
                if status == 200 and kind.startswith("image/"):
                    continue
                # A sync between the listing and the image can change the image.
                now = await self.overture.get(base, media_type=self.media_type)
                if (
                    now[f"server_{art}_version"],
                    now["assets"][art]["content_hash"],
                ) != (
                    version,
                    digest,
                ):
                    case.note = f"the {art} changed since the collection was listed"
                else:
                    case.error = f"HTTP {status} {kind}".strip()

    async def check_offered(self, case: Case, criteria: dict[str, Any]) -> None:
        """Every tag and text value must be one the editor offers as it is spelt."""
        for condition in field_conditions(criteria):
            entry = self.fields.get(condition["field"])
            if entry is None:
                case.error = f"{condition['field']} is not offered here"
                return
            if entry["kind"] != "tag" or condition["operator"] not in {"is", "is_not"}:
                continue
            offered = {str(row["value"]) for row in await self.values(entry["field"])}
            value = str(condition["value"])
            if value in offered:
                continue
            spelt = [known for known in offered if known.casefold() == value.casefold()]
            if spelt:
                case.error = f"{entry['label']} {value!r} is offered as {spelt[0]!r}"
                return
            case.note = f"{entry['label']} {value!r} is not in this library"

    def offered_values(self, field_name: str) -> set[str]:
        """The values already fetched for a field, folded."""
        found = self._values.get(field_name)
        return (
            set()
            if found is None or isinstance(found, ApiError)
            else {str(row["value"]).casefold() for row in found}
        )


def inventory(
    case: Case,
    overture: set[str],
    server: set[str],
    *,
    noun: str,
    names: dict[str, str] | None = None,
) -> None:
    """Report what one side holds that the other does not, by *names* if given."""
    case.count, case.held = len(overture), len(server)
    problems: list[str] = []
    shown = names or {}
    if missing := server - overture:
        problems.append(
            f"Overture lacks {noun} {named([shown.get(key, key) for key in missing])}"
        )
    if extra := overture - server:
        problems.append(
            f"the server lacks {noun} {named([shown.get(key, key) for key in extra])}"
        )
    case.error = "; ".join(problems)


def collection_inventory(
    case: Case,
    listing: Listing,
    media_type: str,
    mine: dict[str, dict[str, Any]],
    held: dict[str, tuple[str, int | None, str | None]],
) -> set[str]:
    """Report the collections one side holds that the other does not.

    *mine* is Overture's collection of each server collection, by its ID;
    *held* is as :func:`left_out` takes it. Returns the collections Overture
    leaves out by design.
    """
    skipped = left_out(case, listing, media_type, held, set(mine))
    inventory(
        case,
        set(mine),
        set(held) - skipped,
        noun="collections",
        names={
            **{key: f"{row['title']} ({key})" for key, row in mine.items()},
            **{
                key: f"{title} ({key}"
                + (f", {count} members)" if count is not None else ")")
                for key, (title, count, _) in held.items()
            },
        },
    )
    return skipped


def left_out(
    case: Case,
    listing: Listing,
    media_type: str,
    held: dict[str, tuple[str, int | None, str | None]],
    mine: set[str],
) -> set[str]:
    """Note the collections Overture leaves out by design; return their IDs.

    *held* names each server collection's title, member count and the kind of
    item it holds.
    """
    reasons = {
        key: reason
        for key, (title, members, subtype) in held.items()
        if key not in mine
        and (reason := listing.reason(title, members, subtype, media_type))
    }
    if reasons:
        case.note = "left out by design: " + named(
            [f"{held[key][0]} ({reason})" for key, reason in reasons.items()]
        )
    return set(reasons)


class PlexServer(Server):
    """Plex, asked directly with its token."""

    server = "plex"

    def __init__(self, base_url: str, token: str, *, verify: bool = True) -> None:
        super().__init__(base_url, {"X-Plex-Token": token}, verify=verify)
        self._directories: dict[tuple[str, int | None], dict[str, str]] = {}

    async def container(self, path: str, **params: Any) -> dict[str, Any]:
        return (await self.get(path, **params))["MediaContainer"]

    async def libraries(self, media_type: str) -> dict[str, str]:
        sections = (await self.container("/library/sections")).get("Directory", [])
        return {
            str(row["key"]): row["title"]
            for row in sections
            if row["type"] == media_type
        }

    async def item_ids(self, library_id: str, media_type: str) -> set[str]:
        ids: set[str] = set()
        while True:
            page = await self.container(
                f"/library/sections/{library_id}/all",
                type=PLEX_TYPES[media_type],
                **{
                    "X-Plex-Container-Start": len(ids),
                    "X-Plex-Container-Size": PLEX_PAGE,
                },
            )
            rows = page.get("Metadata", [])
            ids.update(str(row["ratingKey"]) for row in rows)
            if len(rows) < PLEX_PAGE:
                return ids

    async def collections(self, library_id: str) -> dict[str, dict[str, Any]]:
        rows = (
            await self.container(
                f"/library/sections/{library_id}/collections", includeFields="theme"
            )
        ).get("Metadata", [])
        return {str(row["ratingKey"]): row for row in rows}

    async def directory(
        self, path: str, item_type: int | None = None
    ) -> dict[str, str]:
        """The keys Plex lists a filter's values under, by folded name, fetched once."""
        key = (path, item_type)
        if key not in self._directories:
            params = {} if item_type is None else {"type": item_type}
            self._directories[key] = {
                str(row["title"]).casefold(): unquote(str(row["key"]))
                for row in (await self.container(path, **params)).get("Directory", [])
                if row.get("title") and row.get("key")
            }
        return self._directories[key]

    async def unheld(
        self, library: Library, filter_name: str, values: dict[str, str]
    ) -> set[str]:
        """Which of *values* no title of the library holds, asked of Plex.

        Plex keeps listing a value after the last title holding it loses it,
        and lists labels only collections hold.
        """
        found: set[str] = set()
        for name, key in list(values.items())[:VALUE_PROBES]:
            page = await self.container(
                f"/library/sections/{library.key}/all",
                type=PLEX_TYPES[library.media_type],
                **{
                    filter_name: key,
                    "X-Plex-Container-Start": 0,
                    "X-Plex-Container-Size": 0,
                },
            )
            if not int(page.get("totalSize", page.get("size", 0))):
                found.add(name)
        return found

    async def count(self, library: Library, condition: dict[str, Any]) -> int | None:
        """How many titles Plex selects by a condition, or ``None`` if it refuses it."""
        query = compile_plex_query(
            FilterGroup.model_validate({"conditions": [condition]}),
            media_type=MediaType(library.media_type),
            order=CollectionOrder.TITLE_ASC,
            limit=None,
            choices={},
            labels={},
        )
        try:
            page = await self.container(
                f"/library/sections/{library.key}/all?"
                f"type={PLEX_TYPES[library.media_type]}"
                f"&X-Plex-Container-Start=0&X-Plex-Container-Size=0&{query}"
            )
        except httpx2.HTTPStatusError:
            return None
        return int(page.get("totalSize", page.get("size", 0)))

    async def refused(self, library: Library, condition: dict[str, Any]) -> str:
        """Which character of a text value Plex refuses, asked of Plex directly."""
        value = str(condition["value"])
        culprits = [
            char
            for char in PLEX_TEXT_PROBES
            if char in value
            and await self.count(
                library, {**condition, "value": value.replace(char, "")}
            )
            is not None
        ]
        if not culprits:
            return "Plex refuses the value whichever character is left out"
        note = "Plex answers once {} is left out of the value".format(
            " or ".join(repr(char) for char in culprits)
        )
        if "'" in culprits:
            doubled = await self.count(
                library, {**condition, "value": value.replace("'", "''")}
            )
            note += "; with ' doubled " + (
                "it refuses it too" if doubled is None else f"it selects {doubled}"
            )
        return note

    async def check_library(self, library: Library) -> None:
        """Compare what Overture lists and offers with what Plex holds and offers."""
        await self.check_inventory(library)
        meta = (
            await self.container(
                f"/library/sections/{library.key}/all",
                type=PLEX_TYPES[library.media_type],
                includeMeta=1,
                **{"X-Plex-Container-Start": 0, "X-Plex-Container-Size": 0},
            )
        ).get("Meta", {})
        self.check_offers(library, meta)
        await self.check_values(library, meta)

    async def check_inventory(self, library: Library) -> None:
        held = await self.item_ids(library.key, library.media_type)
        inventory(
            library.case("inventory", "items"),
            {item_copy_id(item, library.id) for item in library.items},
            held,
            noun="items",
        )
        listed = await self.collections(library.key)
        mine = {
            str(copy["server_item_id"]): row
            for row in library.collections
            if (copy := collection_copy(row, library.id))
        }
        collection_inventory(
            library.case("inventory", "collections"),
            library.listing,
            library.media_type,
            mine,
            {
                key: (row["title"], int(row.get("childCount", 0)), row.get("subtype"))
                for key, row in listed.items()
            },
        )
        for key, row in listed.items():
            if (ours := mine.get(key)) is None:
                continue
            library.held[key] = int(row.get("childCount", 0))
            thumb = str(row.get("thumb") or "")
            # Plex composes a poster from the members of a collection without one.
            library.shown[key] = ServerArt(
                poster=bool(thumb) and "/composite/" not in thumb,
                background=bool(row.get("art")),
                theme=bool(row.get("theme")),
            )
            case = library.case("inventory", f"{row['title']} members")
            case.held = library.held[key]
            # Overture counts the members on every server holding a copy.
            if len(ours["copies"]) == 1:
                case.count = ours["child_count"]
            else:
                case.note = (
                    f"Overture counts its members on {len(ours['copies'])} servers"
                )
            problems: list[str] = []
            if bool(int(row.get("smart", 0))) != (ours["kind"] == "smart"):
                problems.append(
                    f"Plex says smart={row.get('smart')}, Overture {ours['kind']}"
                )
            if row["title"] != ours["title"]:
                problems.append(f"Plex names it {row['title']!r}")
            ours_copy = collection_copy(ours, library.id)
            has_theme = holds_server_theme(
                ours, ours_copy["server_id"] if ours_copy else None
            )
            if bool(row.get("theme")) != has_theme:
                problems.append(
                    "Plex holds a theme Overture does not know"
                    if row.get("theme")
                    else "Overture lists a theme Plex does not hold"
                )
            case.error = "; ".join(problems)

    def check_offers(self, library: Library, meta: dict[str, Any]) -> None:
        """Each Plex filter, field, sort and operator must be one Overture uses."""
        # Plex types media fields by name (``resolution``); Overture writes
        # each as one of its own types, found through the fields of the type.
        written_as: dict[str, set[PlexFieldType]] = {
            kind: {kind} for kind in PLEX_FIELD_TYPES
        }
        for kind in meta.get("Type", []):
            if kind.get("type") in PLEX_SCOPES:
                self.check_scope(library, kind, written_as)
        for field_type in meta.get("FieldType", []):
            kind = str(field_type.get("type"))
            ours = written_as.get(kind)
            if not ours:
                library.case(
                    "plex operator", kind
                ).error = "Overture has no Plex field of this type"
                continue
            written = frozenset[str]().union(*map(plex_operators, ours))
            for operator in field_type.get("Operator", []):
                if operator["key"] not in written:
                    library.case(
                        "plex operator",
                        f"{kind} {operator['key']} ({operator['title']})",
                    ).error = "Overture never writes this Plex operator"

    @staticmethod
    def check_scope(
        library: Library,
        kind: dict[str, Any],
        written_as: dict[str, set[PlexFieldType]],
    ) -> None:
        """Check the filters, fields and sorts Plex lists for one item type.

        Adds the Overture type each Plex field type is written as to
        *written_as*.
        """
        known = plex_field_keys(MediaType(library.media_type))
        prefix = "" if kind["type"] == library.media_type else f"{kind['type']}."

        def scoped(key: str) -> str:
            return (key if "." in key else f"{prefix}{key}").removeprefix(
                f"{library.media_type}."
            )

        for entry in kind.get("Field", []):
            field_name = known.get(scoped(entry["key"]))
            plex = FIELDS[field_name].plex if field_name else None
            if plex is not None and entry.get("type"):
                written_as.setdefault(entry["type"], set()).add(plex.type)
        # Plex lists some keys both bare and with their scope (``show.title``).
        offered = {
            *(scoped(entry["filter"]) for entry in kind.get("Filter", [])),
            *(scoped(entry["key"]) for entry in kind.get("Field", [])),
        }
        for key in sorted(offered - set(known)):
            gap(library.case("plex field", key), key, "test this Plex field")
        if prefix:
            return
        sorts = _plex_sorts()
        for entry in kind.get("Sort", []):
            if entry["key"] not in sorts:
                gap(
                    library.case("plex sort", entry["key"]),
                    entry["key"],
                    "order by this Plex sort",
                )

    async def check_values(self, library: Library, meta: dict[str, Any]) -> None:
        """Each value a title holds by Plex's list must be one Overture offers."""
        keys = plex_field_keys(MediaType(library.media_type))
        types: list[dict[str, Any]] = meta.get("Type", [])
        own = next(
            (kind for kind in types if kind.get("type") == library.media_type), None
        )
        filters: list[dict[str, Any]] = own.get("Filter", []) if own else []
        for entry in filters:
            field_name = keys.get(entry["filter"])
            spec = library.fields.get(str(field_name)) if field_name else None
            plex = FIELDS[field_name].plex if field_name else None
            if spec is None or plex is None or spec["kind"] != "tag":
                continue
            if not entry.get("key"):
                continue
            listed = await self.directory(entry["key"])
            # A keyed field's values are Plex's keys (``1080``), not its names.
            held = (
                {key.casefold(): key for key in listed.values()}
                if plex.keyed
                else listed
            )
            try:
                await library.values(spec["field"])
            except ApiError:
                continue
            offered = library.offered_values(spec["field"])
            case = library.case("plex values", spec["label"])
            notes = [f"Overture offers {len(offered)}, Plex lists {len(held)}"]
            missing = {name: key for name, key in held.items() if name not in offered}
            if unheld := await self.unheld(library, entry["filter"], missing):
                notes.append(f"no title holds {named(unheld)}")
            real = set(missing) - unheld
            # Plex lists the titles without a rating under "None".
            if spec["field"] == "content_rating" and "none" in real:
                real.discard("none")
                notes.append("Plex lists the titles without a rating as None")
            if spec["field"] == "collection" and real:
                renamed = await self.renamed(
                    library, {name: held[name] for name in real}
                )
                real -= set(renamed)
                notes.extend(
                    f"Plex's list names {new!r} by its old title {old!r}"
                    for old, new in renamed.items()
                )
            if real:
                problem = f"Overture does not offer {named(real)}"
                if FIELDS[spec["field"]].tmdb:
                    notes.append(f"{problem}: Overture offers TMDB's, Plex its own")
                else:
                    case.error = problem
            if unlisted := offered - set(held):
                notes.append(
                    f"Plex's list leaves out {named(unlisted)}; Overture finds "
                    "them through the titles holding them"
                )
            case.note = "; ".join(notes)

    async def renamed(self, library: Library, listed: dict[str, str]) -> dict[str, str]:
        """The collections Plex's list still names by an old title, by that title.

        Plex keeps a collection's filter value under the title it was made
        with; the collection's ``index`` is that value's key.
        """
        titles = {
            str(row["index"]): row["title"]
            for row in (await self.collections(library.key)).values()
            if row.get("index") is not None
        }
        return {
            name: titles[key]
            for name, key in listed.items()
            if key in titles and titles[key].casefold() != name
        }

    async def explain(
        self,
        library: Library,
        entry: dict[str, Any],
        value: Any,
        difference: tuple[str, bool],
    ) -> str:
        """Name the title the evaluators disagree on, with what Plex holds for it."""
        title, plex_holds = difference
        side = "only Plex selects" if plex_holds else "only Overture selects"
        plex = FIELDS[entry["field"]].plex
        if plex is None:
            return f"{side} {title}"
        key = plex.key_for(MediaType(library.media_type))
        found = f"{side} {title}"
        item = next((row for row in library.items if row["title"] == title), None)
        if item is not None and (rating_key := item_copy_id(item, library.id)):
            rows = (await self.container(f"/library/metadata/{rating_key}")).get(
                "Metadata", [{}]
            )
            tag = PLEX_TAGS.get(key, key.capitalize())
            raw = rows[0].get(tag, rows[0].get(key)) if rows else None
            shown = (
                ", ".join(str(tag.get("tag")) for tag in raw) if is_array(raw) else raw
            )
            found += f"; Plex holds {key}={shown!r}"
        if plex.type == "tag" and not plex.keyed:
            episode = key.startswith("episode.")
            listed = await self.directory(
                f"/library/sections/{library.key}/{key.removeprefix('episode.')}",
                PLEX_EPISODE if episode else PLEX_TYPES[library.media_type],
            )
            if str(value).casefold() not in listed:
                found += f"; Plex's {key} list does not name {value!r}"
        return found


class MediaBrowserServer(Server):
    """Jellyfin or Emby, asked directly with an API key."""

    def __init__(
        self, server: str, base_url: str, api_key: str, *, verify: bool = True
    ) -> None:
        self.server = server
        headers = (
            {"X-Emby-Token": api_key}
            if server == "emby"
            else {"Authorization": f'MediaBrowser Token="{api_key}"'}
        )
        root = f"{base_url.rstrip('/')}/emby" if server == "emby" else base_url
        super().__init__(root, headers, verify=verify)
        #: An administrator, once asked for; empty when the server has none.
        self._administrator: dict[str, Any] | None = None

    async def libraries(self, media_type: str) -> dict[str, str]:
        wanted = {"movie": "movies", "show": "tvshows"}[media_type]
        found = await self.get(
            "/Library/VirtualFolders/Query"
            if self.server == "emby"
            else "/Library/VirtualFolders"
        )
        rows = found["Items"] if is_object(found) else found
        return {
            str(row.get("ItemId") or row.get("Id")): row["Name"]
            for row in rows
            if row.get("CollectionType") == wanted
        }

    async def items(self, library_id: str, media_type: str, **params: Any) -> Any:
        return await self.get(
            "/Items",
            ParentId=library_id,
            Recursive="true",
            IncludeItemTypes=MEDIA_BROWSER_TYPES[media_type],
            EnableImages="false",
            EnableUserData="false",
            # Grouping into collections lists a collection in place of its
            # titles, as Overture's sync must not see them either.
            **(
                {"CollapseBoxSetItems": "false"}
                if self.server == "jellyfin"
                else {"GroupItemsIntoCollections": "false"}
            ),
            **params,
        )

    async def item(self, item_id: str) -> dict[str, Any]:
        """One item as the server holds it.

        Asked as a query by ID: Jellyfin 12 refuses ``/Items/{id}`` without a
        user, which an API key has none of.
        """
        found = await self.get("/Items", Ids=item_id, Fields="SortName,Overview")
        rows: list[dict[str, Any]] = found["Items"]
        return rows[0] if rows else {}

    async def filter_values(self, library: Library) -> dict[str, list[Any]]:
        """The values the server lists for each of its item filters in a library."""
        kind = MEDIA_BROWSER_TYPES[library.media_type]
        if self.server == "jellyfin":
            return await self.get(
                "/Items/Filters", ParentId=library.key, IncludeItemTypes=kind
            )
        # Emby lists each filter's values on its own.
        found: dict[str, list[Any]] = {}
        for _, listed in MEDIA_BROWSER_FILTERS.values():
            try:
                rows = await self.get(
                    f"/{listed}",
                    ParentId=library.key,
                    IncludeItemTypes=kind,
                    Recursive="true",
                )
            except httpx2.HTTPError as exc:
                library.case(f"{self.server} filter", listed).error = failure(exc)
                continue
            found[listed] = [row["Name"] for row in rows["Items"]]
        return found

    async def check_library(self, library: Library) -> None:
        """Compare what Overture lists and counts with what the server does."""
        found = await self.items(library.key, library.media_type, Fields="")
        ours = {item_copy_id(item, library.id) for item in library.items}
        theirs = {str(row["Id"]) for row in found["Items"]}
        case = library.case("inventory", "items")
        inventory(case, ours, theirs, noun="items")
        if extra := sorted(ours - theirs):
            case.note = await self.unlisted(extra[0])
        filters = await self.filter_values(library)
        for field_name, (param, listed) in MEDIA_BROWSER_FILTERS.items():
            spec = library.fields.get(field_name)
            values = [str(value) for value in filters.get(listed) or []]
            if spec is None:
                if values:
                    library.case(
                        f"{self.server} filter", param
                    ).error = "Overture does not offer this filter"
                continue
            differs = "" if library.lead or field_name in PER_COPY else LEAD_DETAILS
            if spec["kind"] == "tag":
                try:
                    await library.values(field_name)
                except ApiError:
                    continue
                case = library.case(f"{self.server} values", spec["label"])
                offered = library.offered_values(field_name)
                case.note = (
                    f"Overture offers {len(offered)}, {self.server} lists {len(values)}"
                )
                spelt = {value.casefold(): value for value in values}
                if missing := set(spelt) - offered:
                    problem = f"Overture does not offer {named(missing)}"
                    if differs:
                        case.note += f"; {problem}: {differs}"
                    else:
                        case.error = problem
                        first = spelt[min(missing)]
                        case.note += await self.held_by(library, param, first)
            if not values:
                continue
            value = values[0]
            case = library.case(f"{self.server} count", f"{spec['label']} is {value!r}")
            case.differs = differs
            await library.preview(
                case,
                single(
                    library.id,
                    {
                        "kind": "field",
                        "field": field_name,
                        "operator": "is",
                        "value": int(value) if spec["kind"] == "number" else value,
                    },
                ),
            )
            counted = await self.items(
                library.key, library.media_type, Limit=0, **{param: value}
            )
            case.held = counted["TotalRecordCount"]
            if case.mismatch and differs:
                case.note = differs

    async def seen_by_a_user(self, item_id: str) -> str:
        """Name the title an administrator sees, beside what the API key lists.

        A difference shows the API key's listing lags a saved edit; the same
        title shows the server did not save it.
        """
        admin = await self.administrator()
        if admin is None:
            return "the server has no administrator to ask"
        row = await self.get(f"/Users/{admin['Id']}/Items/{item_id}")
        return f"an administrator sees the title {row.get('Name')!r}"

    async def editor_item(self, item_id: str) -> dict[str, Any]:
        """One item with every field, as the server's metadata editor reads it."""
        admin = await self.administrator()
        if admin is None:
            return {}
        if self.server == "jellyfin":
            return await self.get(f"/Items/{item_id}", userId=admin["Id"])
        return await self.get(f"/Users/{admin['Id']}/Items/{item_id}")

    async def administrator(self) -> dict[str, Any] | None:
        """A user who sees every library, fetched once."""
        if self._administrator is None:
            users: list[dict[str, Any]] = await self.get("/Users")
            policies: list[dict[str, Any]] = [
                user.get("Policy") or {} for user in users
            ]
            self._administrator = next(
                (
                    user
                    for user, policy in zip(users, policies, strict=True)
                    if policy.get("IsAdministrator")
                ),
                dict[str, Any](),
            )
        return self._administrator or None

    async def has_theme(self, collection_id: str) -> bool:
        """Whether the server plays a theme for the collection, asked as a user."""
        admin = await self.administrator()
        found = await self.get(
            f"/Items/{collection_id}/ThemeSongs",
            InheritFromParent="false",
            **({"UserId": admin["Id"]} if admin else {}),
        )
        return bool(found["TotalRecordCount"])

    async def member_count(self, collection_id: str) -> int:
        """The members of a collection, as Overture lists them.

        Jellyfin lists them only to a user, so Overture asks as an
        administrator; Emby lists them to the API key.
        """
        admin = await self.administrator() if self.server == "jellyfin" else None
        found = await self.get(
            "/Items",
            ParentId=collection_id,
            Limit=0,
            **({"UserId": admin["Id"]} if admin else {}),
        )
        return found["TotalRecordCount"]

    async def unlisted(self, item_id: str) -> str:
        """What the server holds under an ID its library listing leaves out."""
        found = await self.get("/Items", Ids=item_id, Fields="Path")
        admin = await self.administrator()
        seen: list[dict[str, Any]] = (
            (await self.get("/Items", Ids=item_id, UserId=admin["Id"], Fields="Path"))[
                "Items"
            ]
            if admin
            else []
        )
        rows: list[dict[str, Any]] = found["Items"] or seen
        if not rows:
            return f"{self.server} holds no item {item_id}, to the API key or a user"
        row = rows[0]
        to_whom = "the API key" if found["Items"] else "a user only"
        return (
            f"{self.server} answers {item_id} as {row.get('Name')} "
            f"({row.get('Type')}) at {row.get('Path')}, to {to_whom}"
        )

    async def members_to_a_user(self, collection_id: str) -> str:
        """How many members the server lists in a collection to an administrator.

        Told apart from the none it lists to the API key alone, this shows
        whether the server lists a collection's members only to a user.
        """
        admin = await self.administrator()
        if admin is None:
            return f"{self.server} has no administrator to ask as"
        found = await self.get(
            "/Items", ParentId=collection_id, UserId=admin["Id"], Limit=0
        )
        return (
            f"{self.server} lists {found['TotalRecordCount']} members to "
            f"{admin['Name']}, and none to the API key alone"
        )

    async def held_by(self, library: Library, param: str, value: str) -> str:
        """Name a title the server says holds a value, and what Overture keeps of it.

        Overture's copy of the title holds the labels its last sync of it read,
        so a label added on the server since then is not there yet.
        """
        found = await self.items(
            library.key,
            library.media_type,
            Limit=1,
            Fields="DateLastSaved",
            **{param: value},
        )
        if not found["Items"]:
            return ""
        row = found["Items"][0]
        note = f"; {self.server} says {row['Name']} holds {value!r}"
        item = next(
            (
                item
                for item in library.items
                if item_copy_id(item, library.id) == str(row["Id"])
            ),
            None,
        )
        if item is None:
            return f"{note}, as item {row['Id']}, which no title Overture lists holds"
        record = await library.overture.get(f"/api/library/items/{item['id']}/record")
        copy = next(
            (
                stored["values"]
                for stored in record["stored"]
                if stored["table"] == "media_item_copies"
                and stored["values"].get("server_item_id") == str(row["Id"])
            ),
            None,
        )
        if copy is None:
            return note + ", whose copy Overture does not hold"
        labels: list[str] = copy.get("labels") or []
        return (
            f"{note}; {self.server} saved it at {row.get('DateLastSaved')}, and "
            f"Overture last read it at {copy.get('verified_at')}, holding "
            f"{len(labels)} label{'' if len(labels) == 1 else 's'}"
        )

    async def collection_ids(self) -> dict[str, dict[str, Any]]:
        found = await self.get(
            "/Items", IncludeItemTypes="BoxSet", Recursive="true", Fields="ChildCount"
        )
        return {str(row["Id"]): row for row in found["Items"]}


def gap(case: Case, key: str, what: str) -> None:
    """Note a Plex feature Overture leaves out by choice; report any other."""
    reason = PLEX_KNOWN_GAPS.get(key) or PLEX_KNOWN_GAPS.get(
        key.removeprefix("episode.")
    )
    if reason:
        case.note = f"left out by choice: {reason}"
    else:
        case.error = f"Overture cannot {what}"


def _plex_sorts() -> set[str]:
    """The Plex sort keys Overture's orders use."""
    keys: set[str] = set()
    for order in CollectionOrder:
        try:
            keys.add(plex_sort(order).removesuffix(":desc"))
        except ValueError:
            continue
    return keys


async def check_media_browser_collections(
    direct: MediaBrowserServer,
    server_id: int,
    collections: list[dict[str, Any]],
    listing: Listing,
) -> tuple[list[Case], dict[str, int], dict[str, ServerArt]]:
    """BoxSets live outside libraries, so they are compared once per server.

    Returns the cases, and the members the server counts in and the art it
    shows of each BoxSet Overture lists.
    """
    listed = await direct.collection_ids()
    mine = {
        str(copy["server_item_id"]): row
        for row in collections
        for copy in row["copies"]
        if copy["server_id"] == server_id
    }
    case = Case(direct.server, "", "inventory", "collections")
    # A BoxSet holds movies and shows alike, so what it holds is not told apart.
    skipped = collection_inventory(
        case,
        listing,
        "",
        mine,
        {
            key: (row["Name"], row.get("ChildCount"), None)
            for key, row in listed.items()
        },
    )
    # Sync leaves out a collection whose members it cannot place in a library.
    if lacking := sorted(set(listed) - set(mine) - skipped):
        members = await direct.get("/Items", ParentId=lacking[0], Limit=0)
        if not members["TotalRecordCount"]:
            case.note = "; ".join(
                part
                for part in (
                    case.note,
                    f"{listed[lacking[0]]['Name']}: "
                    + await direct.members_to_a_user(lacking[0]),
                )
                if part
            )
    cases = [case]
    held: dict[str, int] = {}
    shown: dict[str, ServerArt] = {}
    for key, row in listed.items():
        if (ours := mine.get(key)) is None:
            continue
        held[key] = await direct.member_count(key)
        tags: dict[str, Any] = row.get("ImageTags") or {}
        shown[key] = ServerArt(
            poster="Primary" in tags,
            background=bool(row.get("BackdropImageTags")),
            theme=await direct.has_theme(key) if direct.server == "jellyfin" else None,
        )
        found = Case(direct.server, "", "inventory", f"{row['Name']} members")
        found.held = held[key]
        if len(ours["copies"]) == 1:
            found.count = ours["child_count"]
        if row["Name"] != ours["title"]:
            found.error = f"{direct.server} names it {row['Name']!r}"
        cases.append(found)
    return cases, held, shown


async def verify_overture(
    url: str,
    api_key: str,
    extra_sources: list[dict[str, Any]],
    direct: dict[str, PlexServer | MediaBrowserServer],
    *,
    verify: bool = True,
) -> list[Case]:
    """Run every check against Overture and each of its servers.

    Each server Overture names is checked on its own, and compared with the
    server of its kind given in *direct*, read directly. Where it names
    several of one kind, which one is given cannot be told, so those are
    checked through Overture alone.
    """
    overture = Overture(url, api_key, verify=verify)
    cases: list[Case] = []
    try:
        settings = await overture.get("/api/settings")
        servers = settings["media_servers"]
        kinds = [server["type"] for server in servers]
        items = (await overture.get("/api/library/items"))["items"]
        everything = await overture.get("/api/collections")
        listing = Listing(
            frozenset(
                name.casefold()
                for name in await overture.get("/api/collections/groups")
            ),
            settings["collection_import_unmanaged"],
        )
    except (ApiError, httpx2.HTTPError) as exc:
        await overture.client.aclose()
        return [Case(url, "", "Overture", "reach the API", error=failure(exc))]
    try:
        for server in servers:
            paired = (
                direct.get(server["type"]) if kinds.count(server["type"]) == 1 else None
            )
            try:
                cases.extend(
                    await verify_server(
                        overture,
                        server,
                        items,
                        everything,
                        extra_sources,
                        paired,
                        listing,
                        servers[0],
                    )
                )
            except (ApiError, httpx2.HTTPError) as exc:
                cases.append(
                    Case(server["title"], "", "server", "check", error=failure(exc))
                )
    finally:
        await overture.client.aclose()
    return cases


async def verify_server(
    overture: Overture,
    server: dict[str, Any],
    items: list[dict[str, Any]],
    everything: list[dict[str, Any]],
    extra_sources: list[dict[str, Any]],
    direct: PlexServer | MediaBrowserServer | None,
    listing: Listing,
    lead: dict[str, Any],
) -> list[Case]:
    """Check the libraries and collections one of Overture's servers holds.

    *lead* is Overture's lead server.
    """
    title = server["title"]
    cases: list[Case] = []
    held: list[dict[str, Any]] = []
    checked: list[tuple[dict[str, Library], list[dict[str, Any]]]] = []
    for media_type in ("movie", "show"):
        found = [
            library
            for library in await overture.get(
                "/api/library/libraries", media_type=media_type
            )
            if library["server_id"] == server["id"]
        ]
        if direct is not None:
            case = Case(title, "", "inventory", f"{media_type} libraries")
            inventory(
                case,
                {row["id"].partition(":")[2] for row in found},
                set(await direct.libraries(media_type)),
                noun="libraries",
            )
            cases.append(case)
        if not found:
            continue
        capabilities = await overture.get(
            "/api/collections/capabilities",
            media_type=media_type,
            library_ids=[library["id"] for library in found],
        )
        ids = {library["id"] for library in found}
        collections = [
            row
            for row in everything
            if media_type in row["media_types"] and ids & set(row["library_ids"])
        ]
        held.extend(collections)
        libraries = {
            library["id"]: Library(
                overture,
                title,
                capabilities,
                media_type,
                library,
                {
                    collection["title"]
                    for collection in collections
                    if library["id"] in collection["library_ids"]
                    and collection["kind"] == "regular"
                },
                [
                    item
                    for item in items
                    if item_copy_id(item, library["id"])
                    and item["media_type"] == media_type
                    and item["server_removed_at"] is None
                ],
                [row for row in collections if library["id"] in row["library_ids"]],
                direct,
                listing,
                lead=server is lead,
            )
            for library in found
        }
        for library in libraries.values():
            print(f"Checking {title}: {library.name}...", flush=True)
            await library.check(extra_sources)
        checked.append((libraries, collections))
    if isinstance(direct, MediaBrowserServer):
        found_cases, counts, shown = await check_media_browser_collections(
            direct, server["id"], held, listing
        )
        cases.extend(found_cases)
        for libraries, _ in checked:
            for library in libraries.values():
                library.held = counts
                library.shown = shown
    for libraries, collections in checked:
        for collection in collections:
            await check_collection(libraries, collection)
        for library in libraries.values():
            cases.extend(library.cases)
    return cases


async def check_collection(
    libraries: dict[str, Library], collection: dict[str, Any]
) -> None:
    """Check each of a collection's server collections, and its images once.

    Each server collection is checked in the first library it holds;
    Jellyfin's and Emby's span several.
    """
    here = [lid for lid in collection["library_ids"] if lid in libraries]
    seen: set[str] = set()
    for library_id in here:
        copy = collection_copy(collection, library_id)
        key = str(copy["server_item_id"]) if copy else library_id
        if key not in seen:
            seen.add(key)
            await libraries[library_id].check_collection(collection)
    if here:
        await libraries[here[0]].check_images(collection)


#: What a TMDB chart is called in TMDB's API, per media type.
TMDB_CHARTS = {
    "movie": {
        "popular": "/movie/popular",
        "top_rated": "/movie/top_rated",
        "now_playing": "/movie/now_playing",
        "upcoming": "/movie/upcoming",
        "trending_day": "/trending/movie/day",
        "trending_week": "/trending/movie/week",
    },
    "show": {
        "popular": "/tv/popular",
        "top_rated": "/tv/top_rated",
        "airing_today": "/tv/airing_today",
        "on_the_air": "/tv/on_the_air",
        "trending_day": "/trending/tv/day",
        "trending_week": "/trending/tv/week",
    },
}
#: A title every catalog knows, to read what each API says about one movie.
SAMPLE_TMDB_MOVIE = 1726
#: Queries whose MDBList list search shows whether lists mirror its franchises.
MDBLIST_QUERIES = ("marvel cinematic universe", "star wars", "wizarding world")


async def probe(service: Server, case: Case, path: str, **params: Any) -> Any:
    """Read *path*, recording a failure by its status alone.

    Errors name no URL, since TMDB and MDBList take their keys as parameters.
    """
    try:
        return await service.get(path, **params)
    except httpx2.HTTPStatusError as exc:
        case.error = f"HTTP {exc.response.status_code}"
    except httpx2.HTTPError as exc:
        case.error = type(exc).__name__
    return None


def shape(value: Any) -> str:
    """The keys a response holds, which show what an API offers."""
    if is_array(value):
        value = value[0] if value else {}
    return ", ".join(sorted(value)) if is_object(value) else type(value).__name__


async def check_tmdb(key: str, overture: Overture | None, verify: bool) -> list[Case]:
    """What TMDB serves: every chart, collection search and a title's details."""
    tmdb = Server("https://api.themoviedb.org/3", {}, verify=verify)
    tmdb.client.headers["Authorization"] = f"Bearer {key}"
    cases: list[Case] = []

    def case(label: str) -> Case:
        cases.append(found := Case("tmdb", "", "tmdb", label))
        return found

    try:
        await probe(tmdb, case("configuration"), "/configuration")
        for media_type, charts in TMDB_CHARTS.items():
            offered = (
                set(
                    (
                        await overture.get(
                            "/api/collections/capabilities", media_type=media_type
                        )
                    )["charts"]
                )
                if overture is not None
                else None
            )
            for chart, path in charts.items():
                found = case(f"{media_type} chart {chart}")
                page = await probe(tmdb, found, path)
                if page is None:
                    continue
                found.held = page.get("total_results")
                if offered is not None and chart not in offered:
                    found.error = "Overture does not offer this TMDB chart"
        for kind in ("movie", "tv"):
            found = case(f"{kind} genres")
            genres = await probe(tmdb, found, f"/genre/{kind}/list")
            if genres is not None:
                found.held = len(genres["genres"])
        found = case("movie watch providers")
        providers = await probe(tmdb, found, "/watch/providers/movie")
        if providers is not None:
            found.held = len(providers["results"])
        found = case("collection search")
        results = await probe(tmdb, found, "/search/collection", query="marvel")
        if results is not None:
            found.held = results["total_results"]
            found.members = [row["name"] for row in results["results"][:ORDER_DEPTH]]
        found = case(f"movie {SAMPLE_TMDB_MOVIE}")
        movie = await probe(
            tmdb,
            found,
            f"/movie/{SAMPLE_TMDB_MOVIE}",
            append_to_response="keywords,release_dates,watch/providers,credits",
        )
        if movie is not None:
            found.note = shape(movie)
    finally:
        await tmdb.client.aclose()
    return cases


async def check_mdblist(key: str, tmdb_id: int, verify: bool) -> list[Case]:
    """What MDBList serves: the account's limits, lists, list items and a title."""
    mdblist = Server("https://api.mdblist.com", {}, verify=verify)
    mdblist.client.params = mdblist.client.params.set("apikey", key)
    cases: list[Case] = []

    def case(label: str) -> Case:
        cases.append(found := Case("mdblist", "", "mdblist", label))
        return found

    try:
        found = case("account limits")
        user = await probe(mdblist, found, "/user")
        if user is not None:
            # Only the limits: the account's name and email stay out of the report.
            found.note = ", ".join(
                f"{name}={user[name]}"
                for name in sorted(user)
                if "request" in name or "limit" in name or "patron" in name
            )
        for label, path in (
            ("own lists", "/lists/user"),
            ("top lists", "/lists/top"),
            ("external lists", "/external/lists/user"),
        ):
            found = case(label)
            lists = await probe(mdblist, found, path)
            if lists is None:
                continue
            found.held = len(lists)
            found.members = [str(row.get("name")) for row in lists[:ORDER_DEPTH]]
            found.note = shape(lists)
            if label == "top lists" and lists:
                items = case(f"items of {lists[0].get('name')}")
                page = await probe(
                    mdblist, items, f"/lists/{lists[0]['id']}/items", limit=5
                )
                if page is not None:
                    rows = [*page.get("movies", []), *page.get("shows", [])]
                    items.held = len(rows)
                    items.note = shape(rows)
        for query in MDBLIST_QUERIES:
            found = case(f"list search {query!r}")
            lists = await probe(mdblist, found, "/lists/search", query=query)
            if lists is not None:
                found.held = len(lists)
                found.members = [
                    f"{row.get('user_name')}/{row.get('slug')} ({row.get('items')})"
                    for row in lists[:ORDER_DEPTH]
                ]
        found = case(f"movie {tmdb_id}")
        movie = await probe(mdblist, found, f"/tmdb/movie/{tmdb_id}")
        if movie is not None:
            found.note = shape(movie)
            franchise = [
                name for name in movie if "franchise" in name or "collection" in name
            ]
            found.members = franchise or ["no franchise or collection field"]
    finally:
        await mdblist.client.aclose()
    return cases


async def check_arr(
    kind: str, url: str, key: str, overture: Overture | None, verify: bool
) -> list[Case]:
    """What Radarr or Sonarr holds, against what Overture offers from it."""
    arr = Server(url, {"X-Api-Key": key}, verify=verify)
    media_type = "movie" if kind == "radarr" else "show"
    cases: list[Case] = []

    def case(label: str) -> Case:
        cases.append(found := Case(kind, "", kind, label))
        return found

    try:
        found = case("system status")
        status = await probe(arr, found, "/api/v3/system/status")
        if status is not None:
            found.note = f"version {status.get('version')}"
        tags = await probe(arr, found := case("tags"), "/api/v3/tag")
        profiles = await probe(
            arr, profile_case := case("quality profiles"), "/api/v3/qualityprofile"
        )
        folders = await probe(
            arr, folder_case := case("root folders"), "/api/v3/rootfolder"
        )
        lists = await probe(
            arr, list_case := case("import lists"), "/api/v3/importlist"
        )
        if lists is not None:
            list_case.held = len(lists)
            list_case.members = [str(row.get("name")) for row in lists[:ORDER_DEPTH]]
        if overture is None:
            return cases
        if tags is not None:
            ours = {
                row["label"]
                for row in await overture.get(f"/api/collections/tags/{kind}")
            }
            inventory(found, ours, {row["label"] for row in tags}, noun="tags")
        options = await overture.get(
            "/api/collections/arr-options", media_type=media_type
        )
        if profiles is not None:
            inventory(
                profile_case,
                {row["label"] for row in options["quality_profiles"]},
                {row["name"] for row in profiles},
                noun="profiles",
            )
        if folders is not None:
            inventory(
                folder_case,
                set(options["root_folders"]),
                {row["path"] for row in folders},
                noun="folders",
            )
    except ApiError as exc:
        cases.append(Case(kind, "", kind, "Overture's options", error=str(exc)))
    finally:
        await arr.client.aclose()
    return cases


def write_provider(
    server: str, url: str, secret: str, *, verify: bool
) -> tuple[ProviderRegistry, BaseMediaServerProvider[Any]]:
    """Overture's own client of one media server, as a sync builds it."""
    values: dict[str, Any] = {
        name: spec.default for name, spec in Settings.model_fields.items()
    }
    values |= {
        "AUTH_MODE": "none",
        "MEDIA_SERVERS": "Verify",
        "MEDIA_SERVER_VERIFY_TYPE": server,
        "MEDIA_SERVER_VERIFY_URL": url,
        "MEDIA_SERVER_VERIFY_API_KEY": secret,
        "MEDIA_SERVER_VERIFY_VERIFY_TLS": verify,
    }
    settings = Settings(**values)
    registry = ProviderRegistry(app_config=settings)
    # One server, numbered as a fresh database numbers its first.
    registry.attach({server.key: 1 for server in settings.MEDIA_SERVERS})
    return registry, registry.get(1)


class WriteCheck:
    """Make, change and delete temporary collections with Overture's own client.

    Each step reads the server itself back, and is reported on its own with
    the request the server refused. Only collections titled ``WRITE_PREFIX``
    are touched, and every one made is deleted at the end, whatever failed.
    """

    def __init__(
        self,
        direct: PlexServer | MediaBrowserServer,
        url: str,
        secret: str,
        *,
        verify: bool,
    ) -> None:
        self.direct = direct
        self.registry, self.provider = write_provider(
            direct.server, url, secret, verify=verify
        )
        self.cases: list[Case] = []
        self.made: list[str] = []
        #: Each regular Plex collection made, by its section and its key in filters.
        self.filed: dict[str, tuple[str, str]] = {}

    def case(self, label: str) -> Case:
        found = Case(self.direct.server, "", "writes", label)
        self.cases.append(found)
        return found

    async def step[T](
        self, label: str, action: Callable[[Case], Awaitable[T]]
    ) -> T | None:
        """Run one step as its own case; ``None`` when the server refused it."""
        case = self.case(label)
        try:
            return await action(case)
        except (MediaServerError, httpx2.HTTPError) as exc:
            case.error = failure(exc)
            return None

    async def held(self, collection_id: str) -> dict[str, Any]:
        """The collection as the server itself holds it."""
        if isinstance(self.direct, PlexServer):
            rows = (
                await self.direct.container(f"/library/metadata/{collection_id}")
            ).get("Metadata", [{}])
            return rows[0]
        return await self.direct.editor_item(collection_id)

    async def art(self, collection_id: str) -> tuple[Any, Any]:
        """What the server names the collection's poster and background by."""
        row = await self.held(collection_id)
        if isinstance(self.direct, PlexServer):
            return row.get("thumb"), row.get("art")
        tags: dict[str, Any] = row.get("ImageTags") or {}
        backdrops: list[Any] = row.get("BackdropImageTags") or []
        return tags.get("Primary"), next(iter(backdrops), None)

    async def run(self) -> list[Case]:
        try:
            # A collection found here outlived the run that deleted it, which
            # the keys and titles that run deleted show.
            if left := await self.sweep():
                self.case("delete what an earlier run left").note = named(left)
            if (found := await self.movies()) is not None:
                library, items = found
                made = await self.step(
                    "create a collection with two members",
                    lambda case: self.create(case, library, items),
                )
                if made is not None:
                    await self.step(
                        "replace a member"
                        + (
                            " and keep a custom order"
                            if isinstance(self.direct, PlexServer)
                            else ""
                        ),
                        lambda case: self.members(case, made, items),
                    )
                    await self.step(
                        "edit the title, sort title, summary and order"
                        + (
                            " and Home visibility"
                            if isinstance(self.direct, PlexServer)
                            else ""
                        ),
                        lambda case: self.details(case, library, made),
                    )
                    await self.step(
                        "upload a poster and a background",
                        lambda case: self.artwork(case, made),
                    )
                    await self.step(
                        "keep the images' names through an edit",
                        lambda case: self.steady(case, library, made),
                    )
                await self.step(
                    f"create a collection of up to {LARGE_COLLECTION} members",
                    lambda case: self.large(case, library, items),
                )
                if isinstance(self.direct, PlexServer):
                    smart = await self.step(
                        "create a smart collection Plex fills itself",
                        lambda case: self.smart(case, library),
                    )
                    if smart is not None:
                        await self.step(
                            "change the smart collection's filter",
                            lambda case: self.refilter(case, library, smart),
                        )
                await self.step("delete the collections it made", self.delete)
        except (MediaServerError, httpx2.HTTPError) as exc:
            self.case("write to the media server").error = failure(exc)
        finally:
            for collection_id in self.made:
                try:
                    await self.provider.delete_collection(collection_id)
                except (MediaServerError, httpx2.HTTPError) as exc:
                    self.case(
                        f"delete {collection_id}"
                    ).error = f"left on the server, delete it by hand: {failure(exc)}"
            await self.registry.close()
        return self.cases

    async def movies(self) -> tuple[str, list[str]] | None:
        """A movie library's ID and up to ``LARGE_COLLECTION`` of its movies.

        ``None``, with why, when the library holds fewer than three.

        The server is asked by its own key of the library; Overture's client
        takes Overture's ID of it.
        """
        section = next(
            (
                row
                for row in await self.provider.get_sections()
                if row.media_type is MediaType.MOVIE
            ),
            None,
        )
        if section is None:
            self.case("find a movie library").error = "the server has no movie library"
            return None
        if isinstance(self.direct, PlexServer):
            items = sorted(await self.direct.item_ids(section.key, "movie"))[
                :LARGE_COLLECTION
            ]
        else:
            found = await self.direct.items(
                section.key, "movie", Limit=LARGE_COLLECTION
            )
            items = [str(row["Id"]) for row in found["Items"]]
        if len(items) < 3:
            self.case("find three movies").error = "the library holds fewer than three"
            return None
        return section.library_id, items

    async def create(self, check: Case, library: str, items: list[str]) -> str:
        """Create a regular collection of the first two movies."""
        first, second, *_ = items
        created = await self.provider.create_collection(
            library, f"{WRITE_PREFIX} regular", MediaType.MOVIE, [first, second]
        )
        self.made.append(created.id)
        if isinstance(self.direct, PlexServer):
            row = await self.held(created.id)
            self.filed[created.id] = (library.partition(":")[2], str(row.get("index")))
        held = await self.provider.get_collection_member_ids(created.id)
        check.count, check.held = 2, len(set(held) & {first, second})
        if not held and isinstance(self.direct, MediaBrowserServer):
            check.note = await self.direct.members_to_a_user(created.id)
        return created.id

    async def members(self, check: Case, collection_id: str, items: list[str]) -> None:
        """Replace a member; Plex keeps the order given, the others their own."""
        first, _, third, *_ = items
        await self.provider.set_collection_members(
            collection_id, [third, first], order=CollectionOrder.CUSTOM
        )
        held = await self.provider.get_collection_member_ids(collection_id)
        if isinstance(self.direct, PlexServer):
            if held != [third, first]:
                check.error = f"the server holds {held}, not [{third}, {first}]"
        elif set(held) != {third, first}:
            check.error = (
                f"the server holds {sorted(held)}, not {sorted([third, first])}"
            )

    async def large(self, check: Case, library: str, items: list[str]) -> None:
        """Create a collection of every movie found, then hold them all.

        As a sync does, the membership write that follows the creation adds
        the members its request could not hold.
        """
        created = await self.provider.create_collection(
            library, f"{WRITE_PREFIX} large", MediaType.MOVIE, items
        )
        self.made.append(created.id)
        await self.provider.set_collection_members(
            created.id, items, order=CollectionOrder.CUSTOM
        )
        held = await self.provider.get_collection_member_ids(created.id)
        check.count, check.held = len(items), len(set(held) & set(items))

    async def details(self, check: Case, library: str, collection_id: str) -> None:
        """Edit what a sync sends, and read the server itself back.

        Plex keeps a custom order; Jellyfin and Emby sort a collection by
        one of their display orders.
        """
        plex = isinstance(self.direct, PlexServer)
        order = CollectionOrder.CUSTOM if plex else CollectionOrder.TITLE_ASC
        locks = await self.locks(collection_id)
        wanted = {
            "title": f"{WRITE_PREFIX} edited",
            "sort title": f"{WRITE_PREFIX} sort",
            "summary": "Made by Overture's verify script",
        }
        await self.provider.update_collection_details(
            collection_id,
            library,
            CollectionDetails(
                title=wanted["title"],
                summary=wanted["summary"],
                sort_title=wanted["sort title"],
                mode=CollectionMode.DEFAULT,
                order=order,
                smart=False,
                visible_home=True,
            ),
        )
        row = await self.held(collection_id)
        if plex:
            kept = {
                "title": row.get("title"),
                "sort title": row.get("titleSort"),
                "summary": row.get("summary"),
                "order": str(row.get("collectionSort")),
            }
            wanted["order"] = str(PLEX_CUSTOM_SORT)
        else:
            kept = {
                "title": row.get("Name"),
                "sort title": row.get("ForcedSortName") or row.get("SortName"),
                "summary": row.get("Overview"),
                "order": row.get("DisplayOrder"),
            }
            wanted["order"] = "SortName"
            # Jellyfin answers with the sort name it derives, in lower case.
            kept["sort title"] = str(kept["sort title"] or "").casefold()
            wanted["sort title"] = wanted["sort title"].casefold()
        wrong = [name for name, value in kept.items() if value != wanted[name]]
        if plex and not await self.on_home(library, collection_id):
            wrong.append("Home visibility")
        # Changing a BoxSet's own lock changes every member's: an edit keeps both.
        if await self.locks(collection_id) != locks:
            wrong.append("lock of the collection or its members")
        if wrong:
            check.error = "the server holds another " + ", ".join(
                f"{name} ({kept.get(name)!r})" if name in kept else name
                for name in wrong
            )
            if isinstance(self.direct, MediaBrowserServer):
                check.note = await self.direct.seen_by_a_user(collection_id)

    async def locks(self, collection_id: str) -> dict[str, object]:
        """Whether Jellyfin or Emby locks the collection and each member, by ID."""
        if not isinstance(self.direct, MediaBrowserServer):
            return {}
        ids = [
            collection_id,
            *await self.provider.get_collection_member_ids(collection_id),
        ]
        return {
            item_id: (await self.direct.editor_item(item_id)).get("LockData")
            for item_id in ids
        }

    async def on_home(self, library: str, collection_id: str) -> bool:
        """Whether Plex promotes the collection's hub to its owner's Home."""
        assert isinstance(self.direct, PlexServer)
        section = library.partition(":")[2]
        hubs: list[dict[str, Any]] = (
            await self.direct.container(
                f"/hubs/sections/{section}/manage", metadataItemId=collection_id
            )
        ).get("Hub", [])
        return any(
            hub.get("identifier") == f"custom.collection.{section}.{collection_id}"
            and bool(hub.get("promotedToOwnHome"))
            for hub in hubs
        )

    async def artwork(self, check: Case, collection_id: str) -> None:
        before = await self.art(collection_id)
        for art_type in (ArtType.POSTER, ArtType.BACKGROUND):
            await self.provider.upload_collection_art(
                collection_id,
                art_type,
                render_art(art_type, ArtStyle.DARK, WRITE_PREFIX),
                "image/png",
            )
        after = await self.art(collection_id)
        unchanged = [
            name
            for name, old, new in zip(
                ("poster", "background"), before, after, strict=True
            )
            if not new or new == old
        ]
        if unchanged:
            check.error = f"the server names the same {' and '.join(unchanged)}"

    async def steady(self, check: Case, library: str, collection_id: str) -> None:
        """Edit the collection as a sync does; the images must keep their names.

        A sync takes an image named otherwise than when Overture sent it for
        one Overture did not send, and forgets it sent one.
        """
        plex = isinstance(self.direct, PlexServer)
        before = await self.art(collection_id)
        await self.provider.update_collection_details(
            collection_id,
            library,
            CollectionDetails(
                title=f"{WRITE_PREFIX} edited",
                summary="Made by Overture's verify script",
                sort_title=f"{WRITE_PREFIX} sort",
                mode=CollectionMode.DEFAULT,
                order=CollectionOrder.CUSTOM if plex else CollectionOrder.TITLE_ASC,
                smart=False,
                visible_home=True,
            ),
        )
        members = await self.provider.get_collection_member_ids(collection_id)
        await self.provider.set_collection_members(
            collection_id, members[::-1], order=CollectionOrder.CUSTOM
        )
        after = await self.art(collection_id)
        if after != before:
            check.error = (
                f"the server names its poster and background {after}, not "
                f"{before}, after an edit"
            )

    def everything_since(self, year: int) -> str:
        """Overture's Plex query for the movies released after *year*."""
        return compile_plex_query(
            FilterGroup.model_validate(
                {
                    "conditions": [
                        {
                            "kind": "field",
                            "field": "year",
                            "operator": "gt",
                            "value": year,
                        }
                    ]
                }
            ),
            media_type=MediaType.MOVIE,
            order=CollectionOrder.TITLE_ASC,
            limit=None,
            choices={},
            labels={},
        )

    async def filled(
        self, check: Case, library: str, collection_id: str, query: str
    ) -> None:
        """Plex holds what its own query selects, and keeps the query."""
        matching, _ = await self.provider.find_matching(
            library, MediaType.MOVIE, query, 0
        )
        held = await self.provider.get_collection_member_ids(collection_id)
        check.count, check.held = matching, len(held)
        kept = await self.provider.smart_collection_filter(collection_id)
        if kept != query:
            check.note = f"Plex keeps the filter as {kept}"

    async def smart(self, check: Case, library: str) -> str:
        """Create a smart collection from Overture's query; Plex fills it."""
        query = self.everything_since(0)
        created = await self.provider.create_smart_collection(
            library, f"{WRITE_PREFIX} smart", MediaType.MOVIE, query
        )
        self.made.append(created.id)
        await self.filled(check, library, created.id, query)
        return created.id

    async def refilter(self, check: Case, library: str, collection_id: str) -> None:
        """Change a smart collection's query, as a sync of an edited rule does."""
        query = self.everything_since(2000)
        await self.provider.update_smart_collection_filter(
            collection_id, library, MediaType.MOVIE, query
        )
        await self.filled(check, library, collection_id, query)

    async def sweep(self) -> list[str]:
        """Delete every collection a run made, recorded or not; name each one.

        A server can make a collection and then fail the request, so the one
        it made is found by its title.
        """
        swept: list[str] = []
        for row in await self.provider.list_collections():
            if row.title.startswith(WRITE_PREFIX):
                swept.append(f"{row.title!r} ({row.id}, {len(row.member_ids)} members)")
                await self.provider.delete_collection(row.id)
                if row.id in self.made:
                    self.made.remove(row.id)
        return swept

    async def delete(self, check: Case) -> None:
        deleted: list[str] = []
        for collection_id in list(self.made):
            row = await self.held(collection_id)
            title = row.get("title") or row.get("Name")
            deleted.append(f"{title!r} ({collection_id})")
            await self.provider.delete_collection(collection_id)
            self.made.remove(collection_id)
        deleted.extend(await self.sweep())
        check.note = f"deleted {named(deleted)}"
        if isinstance(self.direct, PlexServer):
            for section, key in self.filed.values():
                page = await self.direct.container(
                    f"/library/sections/{section}/all",
                    type=PLEX_TYPES["movie"],
                    collection=key,
                    **{"X-Plex-Container-Start": 0, "X-Plex-Container-Size": 0},
                )
                if left := int(page.get("totalSize", page.get("size", 0))):
                    check.note += (
                        f"; Plex still files {left} titles under the deleted "
                        f"collection's filter key {key}"
                    )
        left = [
            row.title
            for row in await self.provider.list_collections()
            if row.title.startswith(WRITE_PREFIX)
        ]
        if left:
            check.error = f"the server still lists {named(left)}"


def cell(value: object) -> str:
    return "" if value is None else str(value).replace("|", "\\|")


def report(cases: list[Case]) -> str:
    """Render the cases as Markdown, per server, problems first."""
    problems = [case for case in cases if case.problem]
    lines = [
        "# Overture check",
        "",
        (
            f"{len(cases)} checks, {len(problems)} problems, "
            f"{sum(bool(case.note) for case in cases)} notes."
        ),
    ]
    for server in dict.fromkeys(case.server for case in cases):
        own = [case for case in cases if case.server == server]
        lines += [
            "",
            f"## {server}",
            "",
            (
                "| Library | Check | Case | Overture | Plex | Server | Members | "
                "Problem | Note |"
            ),
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        lines.extend(
            "| "
            + " | ".join(
                cell(value)
                for value in (
                    case.library,
                    case.check,
                    case.label,
                    case.count,
                    case.smart_count,
                    case.held,
                    ", ".join(case.members),
                    case.problem,
                    case.note,
                )
            )
            + " |"
            for case in sorted(own, key=lambda c: (not c.problem, not c.note))
        )
    return "\n".join(lines) + "\n"


def api_key() -> str:
    """Overture's API key, from OVERTURE_API_KEY."""
    key = os.environ.get("OVERTURE_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set OVERTURE_API_KEY to a key from API keys in the menu")
    return key


def servers(
    args: argparse.Namespace, verify: bool
) -> list[tuple[PlexServer | MediaBrowserServer, str, str]]:
    """The media servers given, with the address and credential of each."""
    found: list[tuple[PlexServer | MediaBrowserServer, str, str]] = []
    for name, variable in (
        ("plex", "PLEX_TOKEN"),
        ("jellyfin", "JELLYFIN_API_KEY"),
        ("emby", "EMBY_API_KEY"),
    ):
        url = getattr(args, name)
        if not url:
            continue
        secret = os.environ.get(variable, "")
        if not secret:
            raise SystemExit(f"Set {variable} to read {name} with --{name}")
        found.append(
            (
                PlexServer(url, secret, verify=verify)
                if name == "plex"
                else MediaBrowserServer(name, url, secret, verify=verify),
                url,
                secret,
            )
        )
    return found


async def check_services(args: argparse.Namespace, verify: bool) -> list[Case]:
    """Probe each service whose credential is set, beside Overture."""
    overture = Overture(args.url, api_key(), verify=verify)
    cases: list[Case] = []
    try:
        if key := os.environ.get("TMDB_READ_ACCESS_TOKEN"):
            print("Checking TMDB...", flush=True)
            cases.extend(await check_tmdb(key, overture, verify))
        if key := os.environ.get("MDBLIST_API_KEY"):
            print("Checking MDBList...", flush=True)
            cases.extend(await check_mdblist(key, SAMPLE_TMDB_MOVIE, verify))
        for kind in ("radarr", "sonarr"):
            url = getattr(args, kind)
            key = os.environ.get(f"{kind.upper()}_API_KEY", "")
            if url and not key:
                raise SystemExit(
                    f"Set {kind.upper()}_API_KEY to read {kind} with --{kind}"
                )
            if url:
                print(f"Checking {kind}...", flush=True)
                cases.extend(await check_arr(kind, url, key, overture, verify))
    finally:
        await overture.client.aclose()
    return cases


async def run(args: argparse.Namespace) -> int:
    extra: list[dict[str, Any]] = (
        json.loads(args.sources.read_text()) if args.sources else []
    )
    cases: list[Case] = []
    verify = not args.insecure
    given = servers(args, verify)
    direct = {server.server: server for server, _, _ in given}
    try:
        cases.extend(
            await verify_overture(args.url, api_key(), extra, direct, verify=verify)
        )
        cases.extend(await check_services(args, verify))
        if args.write:
            for server, url, secret in given:
                print(f"Writing to {server.server}...", flush=True)
                cases.extend(await WriteCheck(server, url, secret, verify=verify).run())
    finally:
        for server in direct.values():
            await server.client.aclose()
    text = report(cases)
    if args.report:
        args.report.write_text(text)
        print(f"Wrote {args.report}")
    else:
        print(text)
    return 1 if any(case.problem for case in cases) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", help="Overture's address, such as http://localhost:5885")
    parser.add_argument("--report", type=Path, help="Write the Markdown report here")
    parser.add_argument(
        "--sources", type=Path, help="A JSON list of extra source objects to test"
    )
    parser.add_argument("--plex", help="Plex's address; PLEX_TOKEN holds its token")
    parser.add_argument(
        "--jellyfin", help="Jellyfin's address; JELLYFIN_API_KEY holds its key"
    )
    parser.add_argument("--emby", help="Emby's address; EMBY_API_KEY holds its key")
    parser.add_argument(
        "--radarr", help="Radarr's address; RADARR_API_KEY holds its key"
    )
    parser.add_argument(
        "--sonarr", help="Sonarr's address; SONARR_API_KEY holds its key"
    )
    parser.add_argument(
        "--insecure", action="store_true", help="Skip TLS certificate verification"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            'Also make, change and delete temporary "zz Overture verify" '
            "collections on each media server given"
        ),
    )
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
