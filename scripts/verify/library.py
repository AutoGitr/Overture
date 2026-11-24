"""The checks of one library in Overture and on its server."""

lazy from collections.abc import Awaitable, Callable
lazy from typing import Any
lazy from urllib.parse import parse_qs, urlsplit

lazy import httpx2

lazy from overture.catalog_contract.contract import ISSUE_FORMS
lazy from overture.domain import (
    CollectionOrder,
)
lazy from overture.schemas.collections import CollectionRuleWrite

lazy from .common import (
    ORDER_DEPTH,
    ApiError,
    Case,
    Listing,
    Members,
    Overture,
    ServerArt,
    collection_copy,
    described,
    expected_kind,
    failure,
    field_conditions,
    field_value,
    first_difference,
    holds_server_theme,
    named,
    single,
)
lazy from .media_browser import MediaBrowserServer
lazy from .plex import PlexServer

#: A condition every dated item meets, to preview orders over a whole library.
EVERYTHING = {"kind": "field", "field": "year", "operator": "gt", "value": 0}


#: Art sources whose image Overture keeps itself, not in a media folder or a link.
KEPT_SOURCES = frozenset({"upload", "generated"})


#: Values each set dimension enumerates.
SET_TOP = 3


#: Items per library whose contribution issue is read.
ISSUE_SAMPLE = 10


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
