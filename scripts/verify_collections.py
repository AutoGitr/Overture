"""Preview every collection criterion against a running Overture, read only.

Builds one condition per field and operator, and one per list source, for
each library, and asks the running instance to preview it. On Plex, a field
both evaluators know is previewed twice, by Overture and as a Plex smart
filter, and the two member counts are compared: a difference points at the
criteria builder or the filter compiler rather than at preview.

The script cannot change anything. Its HTTP client refuses every request
except reads, the sign-in and the two preview endpoints, which only read on
the server, and it never sends a request before that check. Run it against a
synced instance:

    uv run python -m scripts.verify_collections http://localhost:5885 \\
        --report collections.md

The password comes from OVERTURE_PASSWORD, or is asked for; with
AUTH_MODE=none none is needed. Pass --sources
with a JSON file of source objects (as the API takes them) to test TMDB,
MDBList and person sources; Radarr and Sonarr tags and TMDB charts are found
by themselves.
"""

lazy import argparse
lazy import asyncio
lazy import getpass
lazy import json
lazy import os
lazy import sys
lazy from dataclasses import dataclass, field
lazy from pathlib import Path
lazy from typing import Any

lazy import httpx2

#: The only writes the script may send; each of them only reads on the server.
ALLOWED_WRITES = frozenset(
    {
        ("POST", "/api/auth/login"),
        ("POST", "/api/collections/preview"),
        ("POST", "/api/collections/sets/preview"),
    }
)
#: Operands for operators that compare numbers, days or dates.
NUMBER_VALUE = 5
DAYS_VALUE = 365
DATE_VALUE = "2000-01-01"
#: A smart and a regular count may differ this much before it is reported.
TOLERANCE = 0


class WriteRefusedError(RuntimeError):
    """The script tried to send a request that could change something."""


async def refuse_writes(request: httpx2.Request) -> None:
    """Fail any request that is not a read or an allowed preview."""
    if request.method in {"GET", "HEAD"}:
        return
    if (request.method, request.url.path) not in ALLOWED_WRITES:
        raise WriteRefusedError(f"Refused {request.method} {request.url.path}")


@dataclass(slots=True)
class Case:
    """One previewed condition and what came of it."""

    media_type: str
    library: str
    label: str
    count: int | None = None
    smart_count: int | None = None
    members: list[str] = field(default_factory=list[str])
    error: str = ""

    @property
    def mismatch(self) -> bool:
        return (
            self.count is not None
            and self.smart_count is not None
            and abs(self.count - self.smart_count) > TOLERANCE
        )


def detail(response: httpx2.Response) -> str:
    """Return the API's error message for a failed response."""
    try:
        body = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    message = body.get("detail") if isinstance(body, dict) else None
    return str(message or f"HTTP {response.status_code}")


class Overture:
    """A signed-in, read-only client of one Overture instance."""

    def __init__(self, base_url: str) -> None:
        self.client = httpx2.AsyncClient(
            base_url=base_url,
            timeout=120,
            event_hooks={"request": [refuse_writes]},
        )

    async def signed_in(self) -> bool:
        return bool((await self.get("/api/auth/me"))["authenticated"])

    async def sign_in(self, password: str) -> None:
        response = await self.client.post(
            "/api/auth/login", json={"password": password}
        )
        if response.status_code >= 400:
            raise SystemExit(f"Sign-in failed: {detail(response)}")
        if csrf := self.client.cookies.get("overture_csrf"):
            self.client.headers["X-CSRF-Token"] = csrf

    async def get(self, path: str, **params: Any) -> Any:
        response = await self.client.get(path, params=params)
        if response.status_code >= 400:
            raise RuntimeError(detail(response))
        return response.json()

    async def preview(
        self,
        media_type: str,
        library_id: str,
        condition: dict[str, Any],
        *,
        smart: bool,
    ) -> dict[str, Any]:
        response = await self.client.post(
            "/api/collections/preview",
            json={
                "media_type": media_type,
                "library_id": library_id,
                "rule": {"criteria": {"conditions": [condition]}, "smart": smart},
            },
        )
        if response.status_code >= 400:
            raise RuntimeError(detail(response))
        return response.json()


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


async def source_conditions(
    overture: Overture, media_type: str, extra: list[dict[str, Any]]
) -> list[tuple[str, dict[str, Any]]]:
    """Return the list sources to test: found tags and charts, then the given ones."""
    sources: list[tuple[str, dict[str, Any]]] = []
    arr = "radarr" if media_type == "movie" else "sonarr"
    try:
        tags = await overture.get(f"/api/collections/tags/{arr}")
    except RuntimeError:
        tags = []
    if tags:
        first = tags[0]["label"] if isinstance(tags[0], dict) else tags[0]
        sources.append(
            (f"{arr.capitalize()} tag {first}", {"type": f"{arr}_tag", "tags": [first]})
        )
    sources.append(
        ("TMDB chart popular", {"type": "tmdb_chart", "chart": "popular", "limit": 50})
    )
    sources.extend((f"{source['type']} (given)", source) for source in extra)
    return [
        (label, {"kind": "source", "operator": "is", "source": source})
        for label, source in sources
    ]


async def verify_library(
    overture: Overture,
    media_type: str,
    library: dict[str, Any],
    extra_sources: list[dict[str, Any]],
) -> list[Case]:
    """Preview every field, operator and source in one library."""
    capabilities = await overture.get(
        "/api/collections/capabilities", media_type=media_type
    )
    plex_smart = bool(capabilities["smart"])
    cases: list[Case] = []
    for entry in capabilities["fields"]:
        values: list[dict[str, Any]] = []
        if entry["kind"] in {"tag", "text"}:
            try:
                values = await overture.get(
                    "/api/collections/field-values",
                    media_type=media_type,
                    library_id=library["id"],
                    field=entry["field"],
                )
            except RuntimeError as exc:
                cases.append(
                    Case(media_type, library["title"], entry["label"], error=str(exc))
                )
                continue
        for operator in entry["operators"]:
            case = Case(media_type, library["title"], f"{entry['label']} {operator}")
            cases.append(case)
            value = field_value(entry["kind"], operator, values)
            if value is None:
                case.error = "no value in the library to test"
                continue
            condition = {
                "kind": "field",
                "field": entry["field"],
                "operator": operator,
                "value": value,
            }
            case.label += f" {value!r}"
            try:
                if entry["local"]:
                    result = await overture.preview(
                        media_type, library["id"], condition, smart=False
                    )
                    case.count = result["member_count"]
                    case.members = result["members"][:5]
                if plex_smart and entry["smart"]:
                    result = await overture.preview(
                        media_type, library["id"], condition, smart=True
                    )
                    case.smart_count = result["member_count"]
            except RuntimeError as exc:
                case.error = str(exc)
    for label, condition in await source_conditions(
        overture, media_type, extra_sources
    ):
        case = Case(media_type, library["title"], label)
        cases.append(case)
        try:
            result = await overture.preview(
                media_type, library["id"], condition, smart=False
            )
            case.count = result["member_count"]
            case.members = result["members"][:5]
        except RuntimeError as exc:
            case.error = str(exc)
    return cases


def report(cases: list[Case]) -> str:
    """Render the cases as Markdown, problems first."""
    problems = [case for case in cases if case.error or case.mismatch]
    lines = [
        "# Collection preview check",
        "",
        f"{len(cases)} cases, {len(problems)} problems.",
        "",
        "| Library | Case | Overture | Plex | Members | Problem |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for case in sorted(cases, key=lambda c: not (c.error or c.mismatch)):
        problem = case.error or ("counts differ" if case.mismatch else "")
        lines.append(
            "| {} | {} | {} | {} | {} | {} |".format(
                f"{case.library} ({case.media_type})",
                case.label.replace("|", "\\|"),
                "" if case.count is None else case.count,
                "" if case.smart_count is None else case.smart_count,
                ", ".join(case.members).replace("|", "\\|"),
                problem.replace("|", "\\|"),
            )
        )
    return "\n".join(lines) + "\n"


async def run(args: argparse.Namespace) -> int:
    extra = json.loads(args.sources.read_text()) if args.sources else []
    overture = Overture(args.url)
    try:
        if not await overture.signed_in():
            await overture.sign_in(
                os.environ.get("OVERTURE_PASSWORD")
                or getpass.getpass("Overture password: ")
            )
        cases: list[Case] = []
        for media_type in ("movie", "show"):
            libraries = await overture.get(
                "/api/library/libraries", media_type=media_type
            )
            for library in libraries:
                print(f"Checking {library['title']} ({media_type})...", flush=True)
                cases.extend(await verify_library(overture, media_type, library, extra))
    finally:
        await overture.client.aclose()
    text = report(cases)
    if args.report:
        args.report.write_text(text)
        print(f"Wrote {args.report}")
    else:
        print(text)
    return 1 if any(case.error or case.mismatch for case in cases) else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="Overture's address, such as http://localhost:5885")
    parser.add_argument("--report", type=Path, help="Write the Markdown report here")
    parser.add_argument(
        "--sources", type=Path, help="A JSON list of extra source objects to test"
    )
    sys.exit(asyncio.run(run(parser.parse_args())))


if __name__ == "__main__":
    main()
