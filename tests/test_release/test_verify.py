"""The verify script checks Overture and its media servers without changing either."""

lazy import json
lazy from pathlib import Path
lazy from typing import Any

lazy import httpx2
lazy import pytest

lazy from overture.utils.http_security import API_KEY_HEADER
lazy from scripts import verify as module

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
            {
                "dimension": "genre",
                "label": "Genres",
                "title_format": "{value}",
                "smart_only": False,
                "top": None,
                "strip_prefix": "",
                "strip_suffix": "",
            },
            {"dimension": "custom", "label": "Custom", "smart_only": False},
        ],
        "charts": [],
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
        "library_ids": ["1"],
        "media_types": ["movie"],
        "server_item_id": f"c{identity}",
        "thumb_url": f"/api/collections/{identity}/image/poster?t=1",
        "art_url": None,
    }


def _item(identity: int, title: str) -> dict[str, Any]:
    return {
        "id": identity,
        "title": title,
        "media_type": "movie",
        "library_id": "1",
        "server_item_id": f"m{identity}",
        "server_removed_at": None,
    }


type Requests = list[tuple[str, str, str, dict[str, Any]]]

#: What each instance answers for its movies, where the answer never varies.
_MOVIES: dict[str, Any] = {
    "/api/library/libraries": [{"id": "1", "title": "Movies"}],
    "/api/collections/field-values": [{"value": "Horror", "count": 1}],
    "/api/collections/sets/preview": [{"title": "Horror", "member_count": 1}],
    "/api/collections": [
        _collection(5, "Scary", managed=True),
        _collection(6, "Frights", managed=False),
    ],
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
            "libraries": [
                {
                    "library_id": "1",
                    "criteria": {
                        "conditions": [
                            {"field": "genre", "operator": "is", "value": "horror"}
                        ]
                    },
                }
            ],
            "smart": True,
        },
        "tmdb_collection_id": None,
    },
}


def _preview(body: dict[str, Any]) -> httpx2.Response:
    # Plex counts and lists Aliens as well, where Overture does not.
    if body["rule"].get("smart"):
        return httpx2.Response(
            200,
            json={"libraries": [{"member_count": 2, "members": ["Alien", "Aliens"]}]},
        )
    return httpx2.Response(
        200, json={"libraries": [{"member_count": 1, "members": ["Alien"]}]}
    )


def _issue(template: str, title: str) -> dict[str, Any]:
    url = f"https://github.com/o/r/issues/new?template={template}&item_title={title}"
    return {"url": url, "reason": None, "notes": []}


#: What an instance answers whatever the media type.
_FIXED: dict[str, Any] = {
    "/api/library/items": {
        "items": [_item(1, "Alien"), _item(2, "Aliens")],
        "total": 2,
    },
    # A field both evaluate is recommended to the wrong kind.
    "/api/collections/recommend-kind": {"kind": "regular", "reason": "Why."},
    "/api/public-dataset/status": {"enabled": True},
    "/api/public-dataset/items/1/issue": _issue("movie.yml", "Alien"),
    "/api/public-dataset/items/2/issue": _issue("show.yml", "Aliens"),
    "/api/collections/tags/radarr": [{"id": 1, "label": "requests"}],
    "/api/collections/arr-options": {"root_folders": [], "quality_profiles": []},
}


def _overture(
    host: str, request: httpx2.Request, body: dict[str, Any]
) -> httpx2.Response:
    path = request.url.path
    if request.headers.get(API_KEY_HEADER) != f"{host}-key":
        return httpx2.Response(401, json={"detail": "Invalid API key"})
    movies = request.url.params.get("media_type", "movie") == "movie"
    match path:
        case "/api/collections/capabilities":
            return httpx2.Response(200, json=_capabilities(host))
        case "/api/collections/preview":
            return _preview(body)
        case "/api/collections/5/image/poster":
            return httpx2.Response(502, json={"detail": "Bad gateway"})
        case "/api/collections/6/image/poster":
            return httpx2.Response(
                200, content=b"png", headers={"content-type": "image/png"}
            )
        case "/api/collections":
            return httpx2.Response(200, json=_MOVIES[path])
        case _ if path in _FIXED:
            return httpx2.Response(200, json=_FIXED[path])
        case _ if path in _MOVIES:
            return httpx2.Response(200, json=_MOVIES[path] if movies else [])
        case _:
            return httpx2.Response(404)


def _plex(request: httpx2.Request) -> httpx2.Response:
    assert request.headers["X-Plex-Token"] == "token"
    path = request.url.path

    def container(**body: Any) -> httpx2.Response:
        return httpx2.Response(200, json={"MediaContainer": body})

    match path:
        case "/library/sections":
            return container(
                Directory=[{"key": "1", "type": "movie", "title": "Movies"}]
            )
        case "/library/sections/1/collections":
            return container(
                Metadata=[
                    {"ratingKey": "c5", "title": "Scary", "childCount": 3, "smart": 0},
                    {"ratingKey": "c9", "title": "Elsewhere", "childCount": 1},
                ]
            )
        case "/library/sections/1/genre":
            return container(Directory=[{"title": "Horror"}, {"title": "Western"}])
        case "/library/metadata/m2":
            return container(Metadata=[{"Genre": [{"tag": "Horror"}]}])
        case "/library/sections/1/all" if request.url.params.get("includeMeta"):
            return container(
                Meta={
                    "Type": [
                        {
                            "type": "1",
                            "Filter": [
                                {"filter": "genre", "key": "/library/sections/1/genre"},
                                {"filter": "unknownFilter"},
                            ],
                            "Sort": [{"key": "titleSort"}],
                        }
                    ],
                    "FieldType": [
                        {"type": "tag", "Operator": [{"key": "=", "title": "is"}]},
                        {"type": "string", "Operator": [{"key": "~", "title": "like"}]},
                    ],
                }
            )
        case "/library/sections/1/all":
            # Plex holds a third movie Overture never listed.
            return container(
                Metadata=[{"ratingKey": key} for key in ("m1", "m2", "m3")]
            )
        case _:
            return httpx2.Response(404)


def _jellyfin(request: httpx2.Request) -> httpx2.Response:
    assert request.headers["Authorization"] == 'MediaBrowser Token="jelly"'
    params = request.url.params
    match request.url.path:
        case "/Library/VirtualFolders":
            return httpx2.Response(
                200,
                json=[{"ItemId": "1", "Name": "Movies", "CollectionType": "movies"}],
            )
        case "/Items/Filters":
            return httpx2.Response(
                200, json={"Genres": ["Horror", "Drama"], "Tags": []}
            )
        case "/Items" if params.get("IncludeItemTypes") == "BoxSet":
            return httpx2.Response(200, json={"Items": [], "TotalRecordCount": 0})
        case "/Items" if params.get("Genres") == "Horror":
            return httpx2.Response(200, json={"Items": [], "TotalRecordCount": 4})
        case "/Items":
            items = [{"Id": "m1"}, {"Id": "m2"}]
            return httpx2.Response(200, json={"Items": items, "TotalRecordCount": 2})
        case _:
            return httpx2.Response(404)


def _services(request: httpx2.Request) -> httpx2.Response:
    """TMDB, MDBList and Radarr, each holding a little of what Overture reads."""
    path = request.url.path
    match request.url.host:
        case "api.themoviedb.org":
            assert request.url.params["api_key"] == "tmdb-secret"
            if path == "/3/movie/upcoming":
                return httpx2.Response(401)
            if path.endswith("/list"):
                return httpx2.Response(200, json={"genres": [{"id": 1}]})
            return httpx2.Response(
                200, json={"total_results": 7, "results": [{"name": "Saga"}]}
            )
        case "api.mdblist.com":
            assert request.url.params["apikey"] == "mdb-secret"
            if path == "/user":
                return httpx2.Response(
                    200, json={"api_requests": 1000, "username": "private"}
                )
            if path == "/tmdb/movie/1726":
                return httpx2.Response(200, json={"title": "Iron Man", "ids": {}})
            return httpx2.Response(200, json=[])
        case "radarr.test":
            assert request.headers["X-Api-Key"] == "radarr-secret"
            if path == "/api/v3/tag":
                return httpx2.Response(200, json=[{"id": 1, "label": "kids"}])
            if path == "/api/v3/system/status":
                return httpx2.Response(200, json={"version": "5.0"})
            return httpx2.Response(200, json=[])
        case _:
            return httpx2.Response(404)


@pytest.fixture
def requests(monkeypatch: pytest.MonkeyPatch) -> Requests:
    seen: Requests = []
    for name in ("TMDB_API_KEY", "MDBLIST_API_KEY", "RADARR_API_KEY", "SONARR_API_KEY"):
        monkeypatch.delenv(name, raising=False)

    def handler(request: httpx2.Request) -> httpx2.Response:
        host = request.url.host.removesuffix(".test")
        body: dict[str, Any] = json.loads(request.content) if request.content else {}
        seen.append((host, request.method, request.url.path, body))
        if host == "plex-server":
            return _plex(request)
        if host == "jellyfin-server":
            return _jellyfin(request)
        if host in {"api.themoviedb.org", "api.mdblist.com", "radarr"}:
            return _services(request)
        return _overture(host, request, body)

    original = httpx2.AsyncClient

    def client(**kwargs: Any) -> httpx2.AsyncClient:
        return original(transport=httpx2.MockTransport(handler), **kwargs)

    monkeypatch.setattr(module.httpx2, "AsyncClient", client)
    return seen


def _args(report: Path | None, *urls: str, **servers: str) -> Any:
    return module.argparse.Namespace(
        urls=list(urls), report=report, sources=None, insecure=False, **servers
    )


async def test_a_run_checks_overture_against_plex_and_names_each_problem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requests: Requests
) -> None:
    monkeypatch.setenv("OVERTURE_API_KEY", "plex-key")
    monkeypatch.setenv("PLEX_TOKEN", "token")
    report = tmp_path / "report.md"

    status = await module.run(
        _args(report, "http://plex.test", plex="http://plex-server.test")
    )

    assert status == 1
    text = report.read_text()
    assert "| Movies (movie) | field | Genre is 'Horror' | 1 | 2 |" in text
    # The first title only Plex selects is shown with the genres Plex holds.
    assert "only Plex selects Aliens; Plex holds genre='Horror'" in text
    assert "recommends regular, expected smart" in text
    assert "Genre 'horror' is offered as 'Horror'" in text
    assert "| image | Scary poster |" in text
    assert "HTTP 502" in text
    assert "Overture lacks items m3" in text
    assert "Overture lacks collections c9" in text
    assert "Overture does not offer western" in text
    assert "| plex field | unknownFilter |" in text
    assert "| plex operator | string ~ (like) |" in text
    assert "opens ['show.yml']" in text
    # Plex is only ever read, and Overture only through its reads.
    assert {method for host, method, _, _ in requests if host == "plex-server"} == {
        "GET"
    }
    assert {
        path for host, method, path, _ in requests if host == "plex" and method != "GET"
    } <= module.OVERTURE_READS


async def test_jellyfin_filters_are_compared_with_the_values_and_counts_offered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requests: Requests
) -> None:
    monkeypatch.setenv("OVERTURE_API_KEY", "jellyfin-key")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jelly")
    report = tmp_path / "report.md"

    await module.run(
        _args(report, "http://jellyfin.test", jellyfin="http://jellyfin-server.test")
    )

    text = report.read_text()
    assert "| jellyfin values | Genre |" in text
    assert "does not offer drama" in text
    # Jellyfin counts four horror films where Overture counts one.
    assert "| jellyfin count | Genre is 'Horror' | 1 |  | 4 |" in text
    assert "recommend" not in text
    assert {method for host, method, _, _ in requests if host == "jellyfin-server"} == {
        "GET"
    }


async def test_overture_is_never_sent_a_request_that_could_change_it() -> None:
    overture = module.Overture("http://plex.test", "key")
    try:
        with pytest.raises(module.WriteRefusedError):
            await overture.post("/api/collections", {})
    finally:
        await overture.client.aclose()


async def test_keys_and_credentials_are_required(
    monkeypatch: pytest.MonkeyPatch, requests: Requests
) -> None:
    monkeypatch.delenv("OVERTURE_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="OVERTURE_API_KEY"):
        await module.run(_args(None, "http://plex.test"))

    monkeypatch.setenv("OVERTURE_API_KEY", "a,b,c")
    with pytest.raises(SystemExit, match="one per address"):
        await module.run(_args(None, "http://plex.test", "http://jellyfin.test"))

    monkeypatch.delenv("PLEX_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="PLEX_TOKEN"):
        await module.run(
            _args(None, "http://plex.test", plex="http://plex-server.test")
        )


def test_the_first_title_the_evaluators_disagree_on_is_found() -> None:
    whole = (True, True)
    assert module.first_difference(["A", "C"], ["A", "B", "C"], complete=whole) == (
        "B",
        True,
    )
    assert module.first_difference(["A", "B"], ["A", "B"], complete=whole) is None
    # A list the preview cut short may hold the title further on.
    assert module.first_difference(["A"], ["A", "B"], complete=(False, True)) is None
    assert module.first_difference(["A"], ["A", "B"], complete=whole) == ("B", True)


async def test_services_are_read_and_compared_without_their_keys_in_the_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requests: Requests
) -> None:
    monkeypatch.setenv("OVERTURE_API_KEY", "plex-key")
    monkeypatch.setenv("TMDB_API_KEY", "tmdb-secret")
    monkeypatch.setenv("MDBLIST_API_KEY", "mdb-secret")
    monkeypatch.setenv("RADARR_API_KEY", "radarr-secret")
    report = tmp_path / "report.md"

    await module.run(_args(report, "http://plex.test", radarr="http://radarr.test"))

    text = report.read_text()
    for secret in ("tmdb-secret", "mdb-secret", "radarr-secret", "private"):
        assert secret not in text
    # Overture offers no TMDB charts here, and TMDB refuses one.
    assert "| tmdb | movie chart popular |" in text
    assert "Overture does not offer this TMDB chart" in text
    assert "| tmdb | movie chart upcoming |" in text
    assert "HTTP 401" in text
    assert "api_requests=1000" in text
    assert "no franchise or collection field" in text
    assert "Overture lacks tags kids" in text
    assert "the server lacks tags requests" in text
    services = {"api.themoviedb.org", "api.mdblist.com", "radarr"}
    assert {method for host, method, _, _ in requests if host in services} == {"GET"}


async def test_an_arr_needs_its_key(
    monkeypatch: pytest.MonkeyPatch, requests: Requests
) -> None:
    monkeypatch.setenv("OVERTURE_API_KEY", "plex-key")
    with pytest.raises(SystemExit, match="SONARR_API_KEY"):
        await module.run(_args(None, "http://plex.test", sonarr="http://sonarr.test"))
