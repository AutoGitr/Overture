"""The clients, cases and helpers every verify check shares."""

lazy import os
lazy from collections.abc import Iterator
lazy from dataclasses import dataclass, field
lazy from typing import Any

lazy import httpx2

lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.http_client import server_answer
lazy from overture.utils.http_security import API_KEY_HEADER
lazy from scripts.json_values import is_object

#: Operands for operators that compare numbers, days or dates.
NUMBER_VALUE = 5


DAYS_VALUE = 365


DATE_VALUE = "2000-01-01"


#: Members compared between Overture's and Plex's order.
ORDER_DEPTH = 5


#: Missing or extra IDs a mismatch names.
NAMED = 5


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
    answer = server_answer(response)
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
class HeldFields:
    """A server collection's title, sort title and summary, and which it locks."""

    title: str
    sort_title: str
    summary: str
    #: Of "title", "sort title" and "summary".
    locked: frozenset[str]

    def against(self, title: str, sort_title: str, summary: str) -> list[str]:
        """How it differs from what Overture says a sync wrote.

        A field Overture has a value for holds it, locked; one without is the
        server's, unlocked.
        """
        problems: list[str] = []
        for name, held, wanted in (
            ("title", self.title, title),
            ("sort title", self.sort_title, sort_title),
            ("summary", self.summary, summary),
        ):
            if wanted and held != wanted:
                problems.append(f"{name} {held!r}, not {wanted!r}")
            if bool(wanted) != (name in self.locked):
                problems.append(
                    f"{name} {'unlocked' if wanted else 'locked'}"
                    f"{'' if wanted else ' with no value from Overture'}"
                )
        return problems


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


def api_key() -> str:
    """Overture's API key, from OVERTURE_API_KEY."""
    key = os.environ.get("OVERTURE_API_KEY", "").strip()
    if not key:
        raise SystemExit("Set OVERTURE_API_KEY to a key from API keys in the menu")
    return key
