"""Check Overture end to end against its media servers, read only.

Point it at one synced Overture instance per media server (Plex, Jellyfin,
Emby), and at those media servers themselves. Overture is asked through its own
API, so every result comes from the code users run; each media server is asked
directly, so Overture's answers are compared with the server's own:

- **Inventory**: the libraries, every item and every collection Overture lists
  are the ones the server holds, with the members the server counts.
- **Fields**: every field and operator previews in every library; on Plex a
  field both evaluators know is previewed by Overture and by Plex, the counts
  must agree, and where they differ the first title they disagree on is shown
  with the values Plex holds for it. On Jellyfin and Emby the fields the server
  filters on are counted by the server as well.
- **Values**: every tag and text field lists its values, and they include every
  value the server lists for its own filters.
- **Orders**: every order previews; where Overture and Plex both sort, their
  first members are compared (ties may legitimately differ).
- **Kinds**: the kind recommended for each field is one that can evaluate it.
- **Sources and sets**: Radarr and Sonarr tags, every TMDB chart, any given
  sources and every set dimension, with the defaults it starts with, preview.
- **Collections**: each managed collection's rule previews to the members the
  server holds; each unmanaged one plans an adoption whose criteria the editor
  offers and that selects what the server holds; every poster and background
  Overture serves loads.
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
  summary and Home visibility, upload a poster and delete them, reading the
  server back after each step. Everything they make is titled "zz Overture
  verify" and deleted at the end, whatever fails; one left by a run that was
  killed is deleted first. No item, library or other collection is changed.

Create an Overture key per instance under API keys in the menu and pass
them in the order of the addresses; give each media server's address and its
token or API key:

    Single Overture instance, one media server:
    OVERTURE_API_KEY=plex-key \
        PLEX_TOKEN=... \
        RADARR_API_KEY=... \
        SONARR_API_KEY=... \
        uv run python -m scripts.verify \
        https://plex.local:32400 \
        --plex https://localhost:32400 --insecure \
        --radarr http://localhost:7878 \
        --sonarr http://localhost:8989 \
        --report verify.md

    Multiple Overture instances, one per media server:
    OVERTURE_API_KEY=plex-key,jellyfin-key,emby-key \
        PLEX_TOKEN=... \
        JELLYFIN_API_KEY=... \
        EMBY_API_KEY=... \
        RADARR_API_KEY=... \
        SONARR_API_KEY=... \
        uv run python -m scripts.verify \
        https://plex.local:32400 \
        https://jellyfin.local:8096 \
        https://emby.local:8095 \
        --plex https://localhost:32400 --insecure \
        --jellyfin http://localhost:8096 \
        --emby http://localhost:8095 \
        --radarr http://localhost:7878 \
        --sonarr http://localhost:8989 \
        --report verify.md

Set TMDB_API_KEY and MDBLIST_API_KEY to probe those APIs too, and pass
--radarr and --sonarr with RADARR_API_KEY and SONARR_API_KEY to compare them.

One Overture key without commas is used for every instance. An instance whose
media server is not given is checked through Overture alone. Pass --sources
with a JSON file of source objects (as the API takes them) to test TMDB,
MDBList and person sources, and --insecure to skip TLS certificate
verification.
"""

lazy import argparse
lazy import asyncio
lazy import json
lazy import os
lazy import sys
lazy from collections.abc import Iterator
lazy from dataclasses import dataclass, field
lazy from pathlib import Path
lazy from typing import Any
lazy from urllib.parse import parse_qs, urlsplit

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
lazy from overture.media_servers.adapters import ServerCollection
lazy from overture.media_servers.base import BaseMediaServerProvider
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.registry import ProviderRegistry
lazy from overture.schemas.collections import CollectionRuleWrite, FilterGroup
lazy from overture.services.collections.plex_query import (
    compile_plex_query,
    plex_field_keys,
    plex_operators,
    plex_sort,
)
lazy from overture.utils.generated_art import render_art
lazy from overture.utils.http_security import API_KEY_HEADER

#: Operands for operators that compare numbers, days or dates.
NUMBER_VALUE = 5
DAYS_VALUE = 365
DATE_VALUE = "2000-01-01"
#: A condition every dated item meets, to preview orders over a whole library.
EVERYTHING = {"kind": "field", "field": "year", "operator": "gt", "value": 0}
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
#: Fields whose regular evaluation reads play state as of the last library sync.
PLAY_STATE = frozenset({"in_progress", "unplayed", "plays", "last_played"})
#: Plex's metadata type numbers, and the scope its fields take in a section.
PLEX_SCOPES = {"1": "movie", "2": "show", "3": "season", "4": "episode"}
PLEX_TYPES = {"movie": 1, "show": 2}
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
    message = body.get("detail") if isinstance(body, dict) else None
    return str(message or f"HTTP {response.status_code}")


def named(values: set[str] | list[str]) -> str:
    """Name a few of *values*, and how many there are."""
    shown = sorted(values)[:NAMED]
    more = len(values) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


class Overture:
    """A client of one Overture instance, holding a read-only API key."""

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
        """Return the status and content type a GET answers with."""
        response = await self.client.get(path)
        return response.status_code, response.headers.get("content-type", "")

    async def post(self, path: str, body: dict[str, Any]) -> Any:
        if path not in OVERTURE_READS:
            raise WriteRefusedError(f"POST {path} is not a read")
        response = await self.client.post(path, json=body)
        if response.status_code >= 400:
            raise ApiError(detail(response))
        return response.json()

    async def preview(self, rule: dict[str, Any]) -> dict[str, Any]:
        """What the rule's only library previews to."""
        found = await self.post("/api/collections/preview", {"rule": rule})
        return found["libraries"][0]


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
        """The only request a media server is sent."""
        response = await self.client.get(path, params=params)
        response.raise_for_status()
        return response.json()


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


class Library:
    """The checks of one library on one instance, and on its server."""

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
    ) -> None:
        self.overture = overture
        self.server = server
        self.capabilities = capabilities
        self.media_type = media_type
        self.id: str = library["id"]
        self.name = f"{library['title']} ({media_type})"
        self.plex_smart = bool(capabilities["smart"])
        self.fields = {entry["field"]: entry for entry in capabilities["fields"]}
        #: Regular collections' titles: Plex tests membership of these only.
        self.regular = regular
        self.items = items
        self.collections = collections
        self.direct = direct
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

    async def preview(self, case: Case, rule: dict[str, Any]) -> list[str]:
        """Record what a rule previews to: Overture's count, or Plex's if smart."""
        try:
            result = await self.overture.preview(rule)
        except ApiError as exc:
            case.error = str(exc)
            return []
        if rule.get("smart"):
            case.smart_count = result["member_count"]
        else:
            case.count = result["member_count"]
        case.members = result["members"][:ORDER_DEPTH]
        return result["members"]

    async def check(self, extra_sources: list[dict[str, Any]]) -> list[Case]:
        await self.check_fields()
        await self.check_orders()
        await self.check_sources(extra_sources)
        await self.check_sets()
        await self.check_issues()
        if self.direct is not None:
            await self.direct.check_library(self)
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
            local = entry["operators"] if entry["local"] else []
            smart = entry["smart_operators"] if self.plex_smart else []
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
                    condition, local=operator in local, smart=operator in smart
                )
                if operator not in smart:
                    await self.preview(case, single(self.id, condition))
                    continue
                case.differs = PLEX_DIFFERS.get((entry["field"], operator), "")
                if operator not in local:
                    await self.preview(case, single(self.id, condition, smart=True))
                    continue
                # Both in one order, so the first title they disagree on shows why.
                ordered = {"order_type": CollectionOrder.TITLE_ASC.value}
                ours = await self.preview(case, single(self.id, condition, **ordered))
                theirs = await self.preview(
                    case, single(self.id, condition, smart=True, **ordered)
                )
                if case.mismatch and case.differs:
                    case.note = case.differs
                elif case.mismatch and isinstance(self.direct, PlexServer):
                    case.note = await self.direct.explain(
                        self,
                        entry["field"],
                        first_difference(
                            ours,
                            theirs,
                            complete=(
                                len(ours) == case.count,
                                len(theirs) == case.smart_count,
                            ),
                        ),
                    )
                if case.mismatch and entry["field"] in PLAY_STATE:
                    case.note = (
                        "Overture reads play state as of the last library sync; "
                        "sync and run again. " + case.note
                    ).strip()

    async def check_recommendation(
        self, condition: dict[str, Any], *, local: bool, smart: bool
    ) -> None:
        """The kind recommended for a condition must be one that can test it."""
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
        expected = "smart" if smart else "regular" if local else None
        case.note = advice["reason"] if advice else "no recommendation"
        if kind != expected:
            case.error = f"recommends {kind or 'nothing'}, expected {expected}"

    async def check_orders(self) -> None:
        """Preview every order; compare Overture's and Plex's first members."""
        regular = set(self.capabilities["orders"]) - {"custom"}
        smart = set(self.capabilities["smart_orders"]) if self.plex_smart else set()
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
            query = parse_qs(urlsplit(issue["url"]).query)
            if query.get("template") != [ISSUE_FORMS[self.media_type]]:
                case.error = f"opens {query.get('template')}"
            elif query.get("item_title") != [item["title"]]:
                case.error = "the form's title is not the item's"
            case.note = "; ".join(issue["notes"])

    async def check_collection(self, collection: dict[str, Any]) -> None:
        """Preview a collection's rule, or its adoption, against what it holds."""
        managed = collection["managed"]
        case = self.case(
            "collection" if managed else "adoption",
            f"{collection['title']} ({collection['kind']})",
        )
        if collection["withheld"] or collection["unsynced"]:
            case.note = "not on the server"
            return
        await self.check_images(collection)
        case.held = collection["child_count"]
        path = f"/api/collections/{collection['id']}"
        try:
            if managed:
                saved = (await self.overture.get(path, media_type=self.media_type))[
                    "rule"
                ]
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
        await self.preview(case, rule)
        if managed and collection["below_minimum"]:
            case.held = None

    async def check_images(self, collection: dict[str, Any]) -> None:
        """Every image Overture links a collection to must load."""
        for art, url in (
            ("poster", collection.get("thumb_url")),
            ("background", collection.get("art_url")),
        ):
            if not url:
                continue
            case = self.case("image", f"{collection['title']} {art}")
            status, kind = await self.overture.status(url)
            if status != 200 or not kind.startswith("image/"):
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


def inventory(case: Case, overture: set[str], server: set[str], *, noun: str) -> None:
    """Report what one side holds that the other does not."""
    case.count, case.held = len(overture), len(server)
    problems = []
    if missing := server - overture:
        problems.append(f"Overture lacks {noun} {named(missing)}")
    if extra := overture - server:
        problems.append(f"the server lacks {noun} {named(extra)}")
    case.error = "; ".join(problems)


class PlexServer(Server):
    """Plex, asked directly with its token."""

    server = "plex"

    def __init__(self, base_url: str, token: str, *, verify: bool = True) -> None:
        super().__init__(base_url, {"X-Plex-Token": token}, verify=verify)

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
            await self.container(f"/library/sections/{library_id}/collections")
        ).get("Metadata", [])
        return {str(row["ratingKey"]): row for row in rows}

    async def check_library(self, library: Library) -> None:
        """Compare what Overture lists and offers with what Plex holds and offers."""
        await self.check_inventory(library)
        meta = (
            await self.container(
                f"/library/sections/{library.id}/all",
                type=PLEX_TYPES[library.media_type],
                includeMeta=1,
                **{"X-Plex-Container-Start": 0, "X-Plex-Container-Size": 0},
            )
        ).get("Meta", {})
        self.check_offers(library, meta)
        await self.check_values(library, meta)

    async def check_inventory(self, library: Library) -> None:
        held = await self.item_ids(library.id, library.media_type)
        inventory(
            library.case("inventory", "items"),
            {str(item["server_item_id"]) for item in library.items},
            held,
            noun="items",
        )
        listed = await self.collections(library.id)
        mine = {
            str(row["server_item_id"]): row
            for row in library.collections
            if row.get("server_item_id")
        }
        inventory(
            library.case("inventory", "collections"),
            set(mine),
            set(listed),
            noun="collections",
        )
        for key, row in listed.items():
            if (ours := mine.get(key)) is None:
                continue
            case = library.case("inventory", f"{row['title']} members")
            case.count, case.held = ours["child_count"], int(row.get("childCount", 0))
            if bool(int(row.get("smart", 0))) != (ours["kind"] == "smart"):
                case.error = (
                    f"Plex says smart={row.get('smart')}, Overture {ours['kind']}"
                )
            if row["title"] != ours["title"]:
                case.error = f"Plex names it {row['title']!r}"

    def check_offers(self, library: Library, meta: dict[str, Any]) -> None:
        """Each Plex filter, field, sort and operator must be one Overture uses."""
        media_type = MediaType(library.media_type)
        known = set(plex_field_keys(media_type))
        sorts = _plex_sorts()
        for kind in meta.get("Type", []):
            scope = PLEX_SCOPES.get(str(kind.get("type")))
            if scope is None:
                continue
            prefix = "" if scope == library.media_type else f"{scope}."
            offered = {
                *(entry["filter"] for entry in kind.get("Filter", [])),
                *(entry["key"] for entry in kind.get("Field", [])),
            }
            for key in sorted(offered):
                scoped = (key if "." in key else f"{prefix}{key}").removeprefix(
                    f"{library.media_type}."
                )
                if scoped not in known:
                    library.case(
                        "plex field", scoped
                    ).error = "Overture cannot test this Plex field"
            if prefix:
                continue
            for entry in kind.get("Sort", []):
                if entry["key"] not in sorts:
                    library.case(
                        "plex sort", entry["key"]
                    ).error = "Overture cannot order by this Plex sort"
        for field_type in meta.get("FieldType", []):
            kind = field_type.get("type")
            if kind not in {"string", "tag", "integer", "float", "date", "boolean"}:
                library.case(
                    "plex operator", str(kind)
                ).error = "Overture has no Plex field of this type"
                continue
            written = plex_operators(kind)
            for operator in field_type.get("Operator", []):
                if operator["key"] not in written:
                    library.case(
                        "plex operator",
                        f"{kind} {operator['key']} ({operator['title']})",
                    ).error = "Overture never writes this Plex operator"

    async def check_values(self, library: Library, meta: dict[str, Any]) -> None:
        """Each value Plex lists for a filter must be one Overture offers."""
        keys = plex_field_keys(MediaType(library.media_type))
        own = next(
            (
                kind
                for kind in meta.get("Type", [])
                if PLEX_SCOPES.get(str(kind.get("type"))) == library.media_type
            ),
            {},
        )
        for entry in own.get("Filter", []):
            field_name = keys.get(entry["filter"])
            spec = library.fields.get(str(field_name)) if field_name else None
            if spec is None or spec["kind"] != "tag" or not entry.get("key"):
                continue
            plex = {
                str(row.get("title", "")).casefold()
                for row in (await self.container(entry["key"])).get("Directory", [])
            } - {""}
            try:
                await library.values(spec["field"])
            except ApiError:
                continue
            case = library.case("plex values", spec["label"])
            case.count, case.held = (
                len(library.offered_values(spec["field"])),
                len(plex),
            )
            if missing := plex - library.offered_values(spec["field"]):
                case.error = f"Overture does not offer {named(missing)}"

    async def explain(
        self, library: Library, field_name: str, difference: tuple[str, bool] | None
    ) -> str:
        """Name the first title the evaluators disagree on, with Plex's values."""
        if difference is None:
            return "the first members agree; the titles that differ sort later"
        title, plex_holds = difference
        item = next((row for row in library.items if row["title"] == title), None)
        side = "only Plex selects" if plex_holds else "only Overture selects"
        if item is None or not item.get("server_item_id"):
            return f"{side} {title}"
        rows = (
            await self.container(f"/library/metadata/{item['server_item_id']}")
        ).get("Metadata", [{}])
        key = next(
            (
                plex
                for plex, ours in plex_field_keys(MediaType(library.media_type)).items()
                if str(ours) == field_name
            ),
            field_name,
        )
        tag = PLEX_TAGS.get(key, key.capitalize())
        raw = rows[0].get(tag, rows[0].get(key)) if rows else None
        shown = (
            ", ".join(str(tag.get("tag")) for tag in raw)
            if isinstance(raw, list)
            else raw
        )
        return f"{side} {title}; Plex holds {key}={shown!r}"


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

    async def libraries(self, media_type: str) -> dict[str, str]:
        wanted = {"movie": "movies", "show": "tvshows"}[media_type]
        found = await self.get(
            "/Library/VirtualFolders/Query"
            if self.server == "emby"
            else "/Library/VirtualFolders"
        )
        rows = found["Items"] if isinstance(found, dict) else found
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
            **params,
        )

    async def check_library(self, library: Library) -> None:
        """Compare what Overture lists and counts with what the server does."""
        found = await self.items(library.id, library.media_type, Fields="")
        inventory(
            library.case("inventory", "items"),
            {str(item["server_item_id"]) for item in library.items},
            {str(row["Id"]) for row in found["Items"]},
            noun="items",
        )
        filters = await self.get(
            "/Items/Filters",
            ParentId=library.id,
            IncludeItemTypes=MEDIA_BROWSER_TYPES[library.media_type],
        )
        for field_name, (param, listed) in MEDIA_BROWSER_FILTERS.items():
            spec = library.fields.get(field_name)
            values = [str(value) for value in filters.get(listed) or []]
            if spec is None:
                if values:
                    library.case(
                        f"{self.server} filter", param
                    ).error = "Overture does not offer this filter"
                continue
            if spec["kind"] == "tag":
                try:
                    await library.values(field_name)
                except ApiError:
                    continue
                case = library.case(f"{self.server} values", spec["label"])
                offered = library.offered_values(field_name)
                case.count, case.held = len(offered), len(values)
                if missing := {value.casefold() for value in values} - offered:
                    case.error = f"Overture does not offer {named(missing)}"
            if not values:
                continue
            value = values[0]
            case = library.case(f"{self.server} count", f"{spec['label']} is {value!r}")
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
                library.id, library.media_type, Limit=0, **{param: value}
            )
            case.held = counted["TotalRecordCount"]

    async def collection_ids(self) -> dict[str, dict[str, Any]]:
        found = await self.get(
            "/Items", IncludeItemTypes="BoxSet", Recursive="true", Fields="ChildCount"
        )
        return {str(row["Id"]): row for row in found["Items"]}


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
    direct: MediaBrowserServer, collections: list[dict[str, Any]]
) -> list[Case]:
    """BoxSets live outside libraries, so they are compared once per server."""
    listed = await direct.collection_ids()
    mine = {
        str(row["server_item_id"]): row
        for row in collections
        if row.get("server_item_id")
    }
    case = Case(direct.server, "", "inventory", "collections")
    inventory(case, set(mine), set(listed), noun="collections")
    cases = [case]
    for key, row in listed.items():
        if (ours := mine.get(key)) is None:
            continue
        members = await direct.get("/Items", ParentId=key, Limit=0)
        found = Case(direct.server, "", "inventory", f"{row['Name']} members")
        found.count, found.held = ours["child_count"], members["TotalRecordCount"]
        cases.append(found)
    return cases


async def verify_instance(
    url: str,
    api_key: str,
    extra_sources: list[dict[str, Any]],
    direct: PlexServer | MediaBrowserServer | None,
    *,
    verify: bool = True,
) -> list[Case]:
    """Run every check against one Overture instance and its server."""
    overture = Overture(url, api_key, verify=verify)
    cases: list[Case] = []
    listed: list[dict[str, Any]] = []
    try:
        items = (await overture.get("/api/library/items"))["items"]
        everything = await overture.get("/api/collections")
        for media_type in ("movie", "show"):
            capabilities = await overture.get(
                "/api/collections/capabilities", media_type=media_type
            )
            server = capabilities["server_type"]
            if direct is not None and direct.server != server:
                raise SystemExit(f"{url} uses {server}, not {direct.server}")
            collections = [
                row for row in everything if row["media_types"][0] == media_type
            ]
            listed.extend(collections)
            found = await overture.get("/api/library/libraries", media_type=media_type)
            if direct is not None:
                case = Case(server, "", "inventory", f"{media_type} libraries")
                inventory(
                    case,
                    {str(row["id"]) for row in found},
                    set(await direct.libraries(media_type)),
                    noun="libraries",
                )
                cases.append(case)
            libraries = {
                library["id"]: Library(
                    overture,
                    server,
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
                        if item["library_id"] == library["id"]
                        and item["media_type"] == media_type
                        and item["server_removed_at"] is None
                    ],
                    [row for row in collections if library["id"] in row["library_ids"]],
                    direct,
                )
                for library in found
            }
            for library in libraries.values():
                print(f"Checking {server}: {library.name}...", flush=True)
                await library.check(extra_sources)
            for collection in collections:
                if (library := libraries.get(collection["library_ids"][0])) is not None:
                    await library.check_collection(collection)
            for library in libraries.values():
                cases.extend(library.cases)
        if isinstance(direct, MediaBrowserServer):
            cases.extend(await check_media_browser_collections(direct, listed))
    except ApiError as exc:
        cases.append(Case(url, "", "instance", "reach the API", error=str(exc)))
    except httpx2.HTTPError as exc:
        cases.append(
            Case(url, "", "instance", "reach the media server", error=str(exc))
        )
    finally:
        await overture.client.aclose()
    return cases


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
    if isinstance(value, list):
        value = value[0] if value else {}
    return ", ".join(sorted(value)) if isinstance(value, dict) else type(value).__name__


async def check_tmdb(key: str, overture: Overture | None, verify: bool) -> list[Case]:
    """What TMDB serves: every chart, collection search and a title's details."""
    tmdb = Server("https://api.themoviedb.org/3", {}, verify=verify)
    tmdb.client.params = tmdb.client.params.set("api_key", key)
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
        "MEDIA_SERVER": server,
        "MEDIA_SERVER_URL": url,
        "MEDIA_SERVER_API_KEY": secret,
        "MEDIA_SERVER_VERIFY_TLS": verify,
    }
    registry = ProviderRegistry(app_config=Settings(**values))
    return registry, registry.provider


class WriteCheck:
    """Make, change and delete temporary collections with Overture's own client.

    Each step reads the server back. Only collections titled ``WRITE_PREFIX``
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

    def case(self, label: str) -> Case:
        found = Case(self.direct.server, "", "writes", label)
        self.cases.append(found)
        return found

    async def listed(self, collection_id: str) -> ServerCollection | None:
        return next(
            (
                row
                for row in await self.provider.list_collections()
                if row.id == collection_id
            ),
            None,
        )

    async def run(self) -> list[Case]:
        try:
            for stale in await self.provider.list_collections():
                if stale.title.startswith(WRITE_PREFIX):
                    await self.provider.delete_collection(stale.id)
            if (found := await self.movies()) is not None:
                library, items = found
                collection_id = await self.members(library, items)
                await self.details(library, collection_id)
                await self.poster(collection_id)
                if isinstance(self.direct, PlexServer):
                    await self.smart(library)
                await self.delete()
        except (MediaServerError, httpx2.HTTPError) as exc:
            self.case("write to the media server").error = str(exc)
        finally:
            for collection_id in self.made:
                try:
                    await self.provider.delete_collection(collection_id)
                except (MediaServerError, httpx2.HTTPError) as exc:
                    self.case(
                        f"delete {collection_id}"
                    ).error = f"left on the server, delete it by hand: {exc}"
            await self.registry.close()
        return self.cases

    async def movies(self) -> tuple[str, list[str]] | None:
        """A movie library and three of its movies, or ``None`` with why not."""
        library = next(
            (
                row.key
                for row in await self.provider.get_sections()
                if row.media_type is MediaType.MOVIE
            ),
            None,
        )
        if library is None:
            self.case("find a movie library").error = "the server has no movie library"
            return None
        if isinstance(self.direct, PlexServer):
            items = sorted(await self.direct.item_ids(library, "movie"))[:3]
        else:
            found = await self.direct.items(library, "movie", Limit=3)
            items = [str(row["Id"]) for row in found["Items"]]
        if len(items) < 3:
            self.case("find three movies").error = "the library holds fewer than three"
            return None
        return library, items

    async def members(self, library: str, items: list[str]) -> str:
        """Create a collection, then replace and order its members."""
        first, second, third = items
        check = self.case("create a collection with two members")
        created = await self.provider.create_collection(
            library, f"{WRITE_PREFIX} regular", MediaType.MOVIE, [first, second]
        )
        self.made.append(created.id)
        held = await self.provider.get_collection_member_ids(created.id)
        check.count, check.held = 2, len(set(held) & {first, second})

        check = self.case("replace a member and keep a custom order")
        await self.provider.set_collection_members(
            created.id, [third, first], order=CollectionOrder.CUSTOM
        )
        order = await self.provider.get_collection_member_ids(created.id)
        if order != [third, first]:
            check.error = f"the server holds {order}, not [{third}, {first}]"
        return created.id

    async def details(self, library: str, collection_id: str) -> None:
        """Edit what a sync sends, and read it back."""
        check = self.case("edit the title, sort title, summary and Home visibility")
        wanted = {
            "title": f"{WRITE_PREFIX} edited",
            "sort title": f"{WRITE_PREFIX} sort",
            "summary": "Made by Overture's verify script",
        }
        await self.provider.update_collection_details(
            collection_id,
            library_id=library,
            title=wanted["title"],
            summary=wanted["summary"],
            sort_title=wanted["sort title"],
            mode=CollectionMode.DEFAULT,
            order=CollectionOrder.CUSTOM,
            smart=False,
            visible_home=True,
        )
        row = await self.listed(collection_id)
        if row is None:
            check.error = "the edited collection is no longer listed"
            return
        kept = {
            "title": row.title,
            "sort title": row.sort_title,
            "summary": row.summary,
        }
        wrong = [
            name
            for name, value in kept.items()
            if value is not None and value != wanted[name]
        ]
        if isinstance(self.direct, PlexServer) and not row.visible_home:
            wrong.append("Home visibility")
        if wrong:
            check.error = f"the server kept another {', '.join(wrong)}"

    async def poster(self, collection_id: str) -> None:
        check = self.case("upload a poster")
        before = await self.listed(collection_id)
        await self.provider.upload_collection_art(
            collection_id,
            ArtType.POSTER,
            render_art(ArtType.POSTER, ArtStyle.DARK, WRITE_PREFIX),
            "image/png",
        )
        after = await self.listed(collection_id)
        if (
            after is None
            or not after.thumb_url
            or (before is not None and after.thumb_url == before.thumb_url)
        ):
            check.note = "the server lists the same poster address after the upload"

    async def smart(self, library: str) -> None:
        """Create a smart collection from Overture's query; Plex fills it."""
        check = self.case("create a smart collection Plex fills itself")
        query = compile_plex_query(
            FilterGroup.model_validate({"conditions": [EVERYTHING]}),
            media_type=MediaType.MOVIE,
            order=CollectionOrder.TITLE_ASC,
            limit=None,
            choices={},
            labels={},
        )
        created = await self.provider.create_smart_collection(
            library, f"{WRITE_PREFIX} smart", MediaType.MOVIE, query
        )
        self.made.append(created.id)
        matching, _ = await self.provider.find_matching(
            library, MediaType.MOVIE, query, 0
        )
        held = await self.provider.get_collection_member_ids(created.id)
        check.count, check.held = matching, len(held)
        kept = await self.provider.smart_collection_filter(created.id)
        if "year" not in kept:
            check.note = f"Plex keeps the filter as {kept}"

    async def delete(self) -> None:
        check = self.case("delete the collections it made")
        for collection_id in list(self.made):
            await self.provider.delete_collection(collection_id)
            self.made.remove(collection_id)
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


def api_keys(count: int) -> list[str]:
    """One key per instance, from OVERTURE_API_KEY."""
    keys = [key.strip() for key in os.environ.get("OVERTURE_API_KEY", "").split(",")]
    if not any(keys):
        raise SystemExit("Set OVERTURE_API_KEY to keys from API keys in the menu")
    if len(keys) == 1:
        return keys * count
    if len(keys) != count:
        raise SystemExit("Give OVERTURE_API_KEY one key, or one per address")
    return keys


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
        url = getattr(args, name, None)
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


async def server_of(url: str, key: str, verify: bool) -> str | None:
    """The media server an instance uses, as it says."""
    overture = Overture(url, key, verify=verify)
    try:
        return (
            await overture.get("/api/collections/capabilities", media_type="movie")
        )["server_type"]
    except ApiError, httpx2.HTTPError:
        return None
    finally:
        await overture.client.aclose()


async def check_services(args: argparse.Namespace, verify: bool) -> list[Case]:
    """Probe each service whose credential is set, beside the first instance."""
    keys = api_keys(len(args.urls))
    overture = Overture(args.urls[0], keys[0], verify=verify)
    cases: list[Case] = []
    try:
        if key := os.environ.get("TMDB_API_KEY"):
            print("Checking TMDB...", flush=True)
            cases.extend(await check_tmdb(key, overture, verify))
        if key := os.environ.get("MDBLIST_API_KEY"):
            print("Checking MDBList...", flush=True)
            cases.extend(await check_mdblist(key, SAMPLE_TMDB_MOVIE, verify))
        for kind in ("radarr", "sonarr"):
            url = getattr(args, kind, None)
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
    extra = json.loads(args.sources.read_text()) if args.sources else []
    cases: list[Case] = []
    verify = not getattr(args, "insecure", False)
    given = servers(args, verify)
    direct = {server.server: server for server, _, _ in given}
    try:
        for url, key in zip(args.urls, api_keys(len(args.urls)), strict=True):
            server = await server_of(url, key, verify)
            cases.extend(
                await verify_instance(
                    url, key, extra, direct.get(server or ""), verify=verify
                )
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
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "urls",
        nargs="+",
        metavar="url",
        help="Each Overture instance's address, such as http://localhost:5885",
    )
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
