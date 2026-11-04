"""The collection check runs every check on each instance with read-only API keys."""

lazy import json
lazy from pathlib import Path
lazy from typing import Any

lazy import httpx2
lazy import pytest

lazy from overture.utils.http_security import API_KEY_HEADER
lazy from scripts import verify_collections as module

_GENRE = {
    "field": "genre",
    "label": "Genre",
    "kind": "tag",
    "operators": ["is"],
    "smart_operators": ["is"],
    "local": True,
    "smart": True,
}


def _capabilities(server: str) -> dict[str, Any]:
    return {
        "server_type": server,
        "smart": server == "plex",
        "arr": False,
        "orders": ["title.asc", "custom"],
        "smart_orders": ["title.asc"],
        "fields": [_GENRE],
        "dimensions": [
            {"dimension": "genre", "label": "Genres", "smart_only": False},
            {"dimension": "custom", "label": "Custom", "smart_only": False},
        ],
        "charts": ["popular"],
    }


def _collection(identity: int, title: str, *, managed: bool) -> dict[str, Any]:
    return {
        "id": identity,
        "title": title,
        "kind": "smart" if not managed else "regular",
        "managed": managed,
        "withheld": False,
        "unsynced": False,
        "below_minimum": False,
        "child_count": 3,
        "library_id": "1",
    }


type Requests = list[tuple[str, str, dict[str, Any]]]

#: What each instance answers for its movies, where the answer never varies.
_MOVIES: dict[str, Any] = {
    "/api/library/libraries": [{"id": "1", "title": "Movies"}],
    "/api/collections/field-values": [{"value": "Horror", "count": 1}],
    "/api/collections/presets": [],
    "/api/collections/sets/preview": [{"title": "Horror", "member_count": 1}],
    "/api/collections": [
        _collection(5, "Scary", managed=True),
        _collection(6, "Frights", managed=False),
    ],
    # The detail reports the rule's outcome, which a preview does not take.
    "/api/collections/5": {
        "rule": {
            "criteria": {"conditions": [{"kind": "field"}]},
            "last_synced_at": None,
            "source_summary": None,
        }
    },
    # Plex names the genre as it lists it, not as the editor offers it.
    "/api/collections/6/adopt": {
        "rule": {
            "criteria": {
                "conditions": [{"field": "genre", "operator": "is", "value": "horror"}]
            },
            "smart": True,
        },
        "tmdb_collection_id": None,
    },
}


def _preview(body: dict[str, Any]) -> httpx2.Response:
    if body["rule"]["criteria"]["conditions"][0].get("kind") == "source":
        return httpx2.Response(422, json={"detail": "Set TMDB_API_KEY"})
    # Plex counts two where Overture counts one.
    count = 2 if body["rule"].get("smart") else 1
    return httpx2.Response(200, json={"member_count": count, "members": ["Alien"]})


def fake_overture(requests: Requests) -> httpx2.MockTransport:
    """Plex at plex.test and Jellyfin at jellyfin.test, each with a movie library."""

    def handler(request: httpx2.Request) -> httpx2.Response:
        host = request.url.host.removesuffix(".test")
        path = request.url.path
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        requests.append((host, path, body))
        if request.headers.get(API_KEY_HEADER) != f"{host}-key":
            return httpx2.Response(401, json={"detail": "Invalid API key"})
        if path == "/api/collections/capabilities":
            return httpx2.Response(200, json=_capabilities(host))
        if path == "/api/collections/preview":
            return _preview(body)
        if path not in _MOVIES:
            return httpx2.Response(404)
        movies = request.url.params.get("media_type") == "movie"
        return httpx2.Response(200, json=_MOVIES[path] if movies else [])

    return httpx2.MockTransport(handler)


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> Requests:
    seen: Requests = []
    transport = fake_overture(seen)
    original = httpx2.AsyncClient

    def client(**kwargs: Any) -> httpx2.AsyncClient:
        return original(transport=transport, **kwargs)

    monkeypatch.setattr(module.httpx2, "AsyncClient", client)
    return seen


def _args(report: Path | None, *urls: str) -> Any:
    return module.argparse.Namespace(
        urls=list(urls), report=report, sources=None, plex=None
    )


async def test_a_run_checks_each_instance_in_turn_and_reports_the_problems(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    requests: Requests,
) -> None:
    monkeypatch.setenv("OVERTURE_API_KEY", "plex-key, jellyfin-key")
    report = tmp_path / "report.md"

    urls = ("http://plex.test", "http://jellyfin.test")
    assert await module.run(_args(report, *urls)) == 1

    hosts = list(dict.fromkeys(host for host, _, _ in requests))
    assert hosts == ["plex", "jellyfin"]
    plex_previews = [
        body["rule"].get("smart", False)
        for host, path, body in requests
        if host == "plex" and path == "/api/collections/preview"
    ]
    jellyfin_previews = [
        body["rule"].get("smart", False)
        for host, path, body in requests
        if host == "jellyfin" and path == "/api/collections/preview"
    ]
    # Plex previews a field and an order both ways; Jellyfin only by Overture.
    assert plex_previews.count(True) == 2
    assert True not in jellyfin_previews
    text = report.read_text()
    assert "## plex" in text
    assert "## jellyfin" in text
    assert "| Movies (movie) | field | Genre is 'Horror' | 1 | 2 |" in text
    assert "Genre 'horror' is offered as 'Horror'" in text
    # A managed collection previews to fewer members than the server holds.
    assert "| collection | Scary (regular) | 1 |  | 3 |" in text
    saved = [
        body["rule"]
        for _, path, body in requests
        if path == "/api/collections/preview" and "kind" in str(body)
    ]
    assert all("last_synced_at" not in rule for rule in saved)
    assert "Set TMDB_API_KEY" in text
    assert "| set | Genres |" in text
    assert "Custom" not in text


async def test_one_key_is_sent_to_every_instance(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    requests: Requests,
) -> None:
    monkeypatch.setenv("OVERTURE_API_KEY", "plex-key")
    report = tmp_path / "report.md"

    await module.run(_args(report, "http://plex.test", "http://jellyfin.test"))

    assert list(dict.fromkeys(host for host, _, _ in requests)) == ["plex", "jellyfin"]
    # Jellyfin refuses Plex's key, which the report names as a problem.
    assert "| reach the API |" in report.read_text()


async def test_a_run_needs_an_api_key_for_each_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OVERTURE_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="OVERTURE_API_KEY"):
        await module.run(_args(None, "http://plex.test"))

    monkeypatch.setenv("OVERTURE_API_KEY", "a,b,c")
    with pytest.raises(SystemExit, match="one per address"):
        await module.run(_args(None, "http://plex.test", "http://jellyfin.test"))


async def test_plex_fields_overture_lacks_are_problems(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def plex(request: httpx2.Request) -> httpx2.Response:
        assert request.headers["X-Plex-Token"] == "token"
        if request.url.path == "/library/sections":
            directories = [{"key": "1", "type": "show", "title": "TV"}]
            return httpx2.Response(
                200, json={"MediaContainer": {"Directory": directories}}
            )
        types = [
            {
                "type": "2",
                "Filter": [{"filter": "genre"}, {"filter": "unwatchedLeaves"}],
                "Field": [{"key": "show.title"}, {"key": "show.originalTitle"}],
                "Sort": [{"key": "titleSort"}, {"key": "episode.addedAt"}],
            },
            {"type": "4", "Field": [{"key": "episode.resolution"}, {"key": "year"}]},
        ]
        return httpx2.Response(200, json={"MediaContainer": {"Directory": types}})

    original = httpx2.AsyncClient

    def client(**kwargs: Any) -> httpx2.AsyncClient:
        return original(transport=httpx2.MockTransport(plex), **kwargs)

    monkeypatch.setattr(module.httpx2, "AsyncClient", client)

    cases = await module.verify_plex_fields("http://plex.test", "token")

    assert [(case.check, case.label) for case in cases] == [
        ("plex field", "originalTitle"),
        ("plex sort", "episode.addedAt"),
        ("plex field", "episode.year"),
    ]


async def test_insecure_skips_tls_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    verified: list[bool] = []
    seen: Requests = []
    overture_transport = fake_overture(seen)
    original = httpx2.AsyncClient

    def plex(request: httpx2.Request) -> httpx2.Response:
        return httpx2.Response(200, json={"MediaContainer": {"Directory": []}})

    def client(**kwargs: Any) -> httpx2.AsyncClient:
        verified.append(kwargs.get("verify", True))
        transport = (
            httpx2.MockTransport(plex)
            if kwargs.get("base_url") == "https://plex.test"
            else overture_transport
        )
        return original(transport=transport, **kwargs)

    monkeypatch.setattr(module.httpx2, "AsyncClient", client)
    monkeypatch.setenv("OVERTURE_API_KEY", "plex-key")
    monkeypatch.setenv("PLEX_TOKEN", "token")

    args = module.argparse.Namespace(
        urls=["http://plex.test"],
        report=None,
        sources=None,
        plex="https://plex.test",
        insecure=True,
    )
    await module.run(args)
    assert verified == [False, False]
