"""Check collections end to end against running Overture instances, read only.

Point it at one synced instance per media server (Plex, Jellyfin, Emby) and it
checks each in turn through Overture's own API, so every result comes from the
code users run:

- **Fields**: every field and operator in every library previews; on Plex, a
  field both evaluators know is previewed by Overture and by Plex as a smart
  filter, and the counts must agree.
- **Values**: every tag and text field lists its values.
- **Orders**: every order previews; where Overture and Plex both sort, their
  first members are compared (ties may legitimately differ).
- **Sources**: Radarr and Sonarr tags, a TMDB chart and any given sources.
- **Presets and sets**: every collection preset and set dimension previews.
- **Collections**: each managed collection's rule previews to the members the
  server holds; each unmanaged one is planned for adoption, which must read
  back into criteria whose values the editor offers and that select the
  members the server holds.

The script cannot change anything: it signs in with API keys, which Overture
lets read and preview but never change. Create one per instance under API keys
in the menu and pass them in the same order as the addresses:

    OVERTURE_API_KEY=plex-key,jellyfin-key,emby-key \\
        uv run python -m scripts.verify_collections \\
        http://localhost:5885 http://localhost:5886 http://localhost:5887 \\
        --report collections.md

One key without commas is used for every instance. Pass --sources with a JSON
file of source objects (as the API takes them) to test TMDB, MDBList and
person sources.
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

lazy import httpx2

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

    @property
    def mismatch(self) -> bool:
        counts = {self.count, self.smart_count, self.held} - {None}
        return len(counts) > 1

    @property
    def problem(self) -> str:
        return self.error or ("counts differ" if self.mismatch else "")


class ApiError(RuntimeError):
    """A failed request, with the API's message."""


def detail(response: httpx2.Response) -> str:
    """Return the API's error message for a failed response."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    message = body.get("detail") if isinstance(body, dict) else None
    return str(message or f"HTTP {response.status_code}")


class Overture:
    """A client of one Overture instance, holding a read-only API key."""

    def __init__(self, base_url: str, api_key: str) -> None:
        self.client = httpx2.AsyncClient(
            base_url=base_url, timeout=300, headers={API_KEY_HEADER: api_key}
        )

    async def get(self, path: str, **params: Any) -> Any:
        response = await self.client.get(path, params=params)
        if response.status_code >= 400:
            raise ApiError(detail(response))
        return response.json()

    async def post(self, path: str, body: dict[str, Any]) -> Any:
        response = await self.client.post(path, json=body)
        if response.status_code >= 400:
            raise ApiError(detail(response))
        return response.json()

    async def preview(
        self, media_type: str, library_id: str, rule: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.post(
            "/api/collections/preview",
            {"media_type": media_type, "library_id": library_id, "rule": rule},
        )


def single(condition: dict[str, Any], **rule: Any) -> dict[str, Any]:
    """A rule of one condition."""
    return {"criteria": {"conditions": [condition]}, **rule}


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


class Library:
    """The checks of one library on one instance."""

    def __init__(
        self,
        overture: Overture,
        server: str,
        capabilities: dict[str, Any],
        media_type: str,
        library: dict[str, Any],
    ) -> None:
        self.overture = overture
        self.server = server
        self.capabilities = capabilities
        self.media_type = media_type
        self.id: str = library["id"]
        self.name = f"{library['title']} ({media_type})"
        self.plex_smart = bool(capabilities["smart"])
        self.fields = {entry["field"]: entry for entry in capabilities["fields"]}
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

    async def preview(self, case: Case, rule: dict[str, Any]) -> None:
        """Record what a rule previews to: Overture's count, or Plex's if smart."""
        try:
            result = await self.overture.preview(self.media_type, self.id, rule)
        except ApiError as exc:
            case.error = str(exc)
            return
        if rule.get("smart"):
            case.smart_count = result["member_count"]
        else:
            case.count = result["member_count"]
        case.members = result["members"][:ORDER_DEPTH]

    async def check(self, extra_sources: list[dict[str, Any]]) -> list[Case]:
        await self.check_fields()
        await self.check_orders()
        await self.check_sources(extra_sources)
        await self.check_presets()
        await self.check_sets()
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
            for operator in entry["operators"]:
                value = field_value(entry["kind"], operator, values)
                case = self.case("field", f"{entry['label']} {operator} {value!r}")
                if value is None:
                    case.note = "no value in the library to test"
                    continue
                condition = {
                    "kind": "field",
                    "field": entry["field"],
                    "operator": operator,
                    "value": value,
                }
                if entry["local"]:
                    await self.preview(case, single(condition))
                if self.plex_smart and entry["smart"]:
                    await self.preview(case, single(condition, smart=True))

    async def check_orders(self) -> None:
        """Preview every order; compare Overture's and Plex's first members."""
        regular = set(self.capabilities["orders"]) - {"custom"}
        smart = set(self.capabilities["smart_orders"]) if self.plex_smart else set()
        for order in sorted(regular | smart):
            case = self.case("order", order)
            members: dict[bool, list[str]] = {}
            for is_smart in (False, True):
                if order in (smart if is_smart else regular):
                    await self.preview(
                        case, single(EVERYTHING, order_type=order, smart=is_smart)
                    )
                    members[is_smart] = case.members
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
            await self.preview(
                self.case("source", label),
                single({"kind": "source", "operator": "is", "source": source}),
            )

    async def check_presets(self) -> None:
        """Preview each collection preset's rule and each set preset."""
        presets = await self.overture.get(
            "/api/collections/presets", media_type=self.media_type
        )
        for preset in presets:
            case = self.case("preset", preset["label"])
            if preset["collection"] is not None:
                await self.preview(case, preset["collection"]["rule"])
            elif preset["set"] is not None:
                await self.preview_set(case, preset["set"]["generator"])

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
                    "smart": dimension["smart_only"],
                },
            )

    async def preview_set(self, case: Case, generator: dict[str, Any]) -> None:
        try:
            entries = await self.overture.post(
                "/api/collections/sets/preview",
                {
                    "media_type": self.media_type,
                    "generator": {**generator, "library_ids": [self.id]},
                },
            )
        except ApiError as exc:
            case.error = str(exc)
            return
        case.members = [
            f"{entry['title']} ({entry['member_count']})" for entry in entries
        ][:ORDER_DEPTH]
        if not entries:
            case.note = "no collections"

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
        case.held = collection["child_count"]
        path = f"/api/collections/{collection['id']}"
        try:
            if managed:
                rule = (await self.overture.get(path, media_type=self.media_type))[
                    "rule"
                ]
            else:
                plan = await self.overture.get(
                    f"{path}/adopt", media_type=self.media_type
                )
                rule = plan["rule"]
                if plan["tmdb_collection_id"]:
                    case.note = f"TMDB collection {plan['tmdb_collection_id']}"
                await self.check_offered(case, rule["criteria"])
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


async def verify_instance(
    url: str, api_key: str, extra_sources: list[dict[str, Any]]
) -> list[Case]:
    """Run every check against one Overture instance."""
    overture = Overture(url, api_key)
    cases: list[Case] = []
    try:
        for media_type in ("movie", "show"):
            capabilities = await overture.get(
                "/api/collections/capabilities", media_type=media_type
            )
            server = capabilities["server_type"]
            libraries = {
                library["id"]: Library(
                    overture, server, capabilities, media_type, library
                )
                for library in await overture.get(
                    "/api/library/libraries", media_type=media_type
                )
            }
            for library in libraries.values():
                print(f"Checking {server}: {library.name}...", flush=True)
                await library.check(extra_sources)
            collections = await overture.get("/api/collections", media_type=media_type)
            for collection in collections:
                if (library := libraries.get(collection["library_id"])) is not None:
                    await library.check_collection(collection)
            for library in libraries.values():
                cases.extend(library.cases)
    except ApiError as exc:
        cases.append(Case(url, "", "instance", "reach the API", error=str(exc)))
    finally:
        await overture.client.aclose()
    return cases


def cell(value: object) -> str:
    return "" if value is None else str(value).replace("|", "\\|")


def report(cases: list[Case]) -> str:
    """Render the cases as Markdown, per server, problems first."""
    problems = [case for case in cases if case.problem]
    lines = [
        "# Collection check",
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


async def run(args: argparse.Namespace) -> int:
    extra = json.loads(args.sources.read_text()) if args.sources else []
    cases: list[Case] = []
    for url, key in zip(args.urls, api_keys(len(args.urls)), strict=True):
        cases.extend(await verify_instance(url, key, extra))
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
        help="Each instance's address, such as http://localhost:5885",
    )
    parser.add_argument("--report", type=Path, help="Write the Markdown report here")
    parser.add_argument(
        "--sources", type=Path, help="A JSON list of extra source objects to test"
    )
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
