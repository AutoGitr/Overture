"""The verify script checks Overture and its media servers without changing either."""

lazy import argparse
lazy import json
lazy from dataclasses import replace
lazy from pathlib import Path
lazy from typing import Any, cast, override

lazy import httpx2
lazy import pytest

lazy from overture.domain import (
    ArtType,
    AssetStatus,
    CollectionOrder,
    MediaType,
    ServerAsset,
)
lazy from overture.media_servers.adapters import (
    CollectionDetails,
    MemberWrite,
    ServerCollection,
    ServerSection,
)
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.schemas.assets import TitleAssets
lazy from overture.schemas.collections import CollectionCapabilities
lazy from overture.utils.http_security import API_KEY_HEADER
lazy from scripts.verify import cli, common, media_browser, writes
lazy from scripts.verify import library as verify_library
lazy from scripts.verify import plex as verify_plex

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
    capabilities = {
        "server_types": [server],
        "spans_libraries": server != "plex",
        "smart": server == "plex",
        "visibility": server == "plex",
        "member_labels": server == "plex",
        "arr": False,
        "orders": ["title.asc", "custom"],
        "smart_orders": ["title.asc"],
        "fields": [_GENRE],
        "sources": [],
        "dimensions": [
            {
                "dimension": "genre",
                "label": "Genres",
                "title_format": "{value}",
                "smart_only": False,
                "strip_prefix": "",
                "strip_suffix": "",
            },
            {"dimension": "custom", "label": "Custom", "title_format": "{value}"},
        ],
        "charts": [],
    }
    # The script reads what the API sends, so the fixture is that response.
    return CollectionCapabilities.model_validate(capabilities).model_dump(mode="json")


def _assets(
    *,
    poster: dict[str, Any] | None = None,
    background: dict[str, Any] | None = None,
    theme: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a serialized TitleAssets payload matching the API schema."""

    def slot(kind: ServerAsset, overrides: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "kind": kind,
            "status": AssetStatus.MISSING,
            "needed": True,
            "selected": False,
            **(overrides or {}),
        }

    assets = {
        "poster": slot(ServerAsset.POSTER, poster),
        "background": slot(ServerAsset.BACKGROUND, background),
        "theme": slot(ServerAsset.THEME, theme),
    }
    return TitleAssets.model_validate(assets).model_dump(mode="json")


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
        "library_ids": ["1:1"],
        "media_types": ["movie"],
        "copies": [
            {"server_id": 1, "server_item_id": f"c{identity}", "library_ids": ["1:1"]}
        ],
        "server_poster_version": "1",
        "server_background_version": None,
        # Overture chose a poster but keeps no record of sending it.
        "assets": _assets(
            poster={
                "source": "tmdb" if managed else None,
                "selected": managed,
                "status": "partial" if managed else "missing",
            }
        ),
    }


def _item(
    identity: int, title: str, *, poster: dict[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "id": identity,
        "title": title,
        "media_type": "movie",
        "copies": [
            {"server_id": 1, "server_item_id": f"m{identity}", "library_id": "1:1"}
        ],
        "server_removed_at": None,
        "assets": _assets(poster=poster),
    }


type Requests = list[tuple[str, str, str, dict[str, Any]]]

#: What each instance answers for its movies, where the answer never varies.
_MOVIES: dict[str, Any] = {
    "/api/library/libraries": [{"id": "1:1", "title": "Movies", "server_id": 1}],
    "/api/collections/field-values": [
        {"value": "Horror", "label": "Horror", "count": 1}
    ],
    "/api/collections/sets/preview": [{"title": "Horror", "member_count": 1}],
    "/api/collections": [
        _collection(5, "Scary", managed=True),
        _collection(6, "Frights", managed=False),
    ],
    "/api/collections/5": {
        "rule": {
            "libraries": [
                {
                    "library_id": "1:1",
                    "criteria": {
                        "conditions": [
                            {"field": "genre", "operator": "is", "value": "Horror"}
                        ]
                    },
                }
            ],
            "last_synced_at": None,
            "source_summary": None,
            "last_error": "Members synced; Automatic assets failed: Boom",
        },
        "server_poster_version": "1",
        "server_background_version": None,
        "assets": _assets(),
    },
    # Plex names the genre as it lists it, not as the editor offers it.
    "/api/collections/6/adopt": {
        "rule": {
            "libraries": [
                {
                    "library_id": "1:1",
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
            json={
                "libraries": [
                    {
                        "library_id": "1:1",
                        "member_count": 2,
                        "members": ["Alien", "Aliens"],
                    }
                ]
            },
        )
    return httpx2.Response(
        200,
        json={
            "libraries": [
                {"library_id": "1:1", "member_count": 1, "members": ["Alien"]}
            ]
        },
    )


def _issue(template: str, title: str) -> dict[str, Any]:
    url = f"https://github.com/o/r/issues/new?template={template}&item_title={title}"
    return {"url": url, "reason": None, "notes": []}


#: What an instance answers whatever the media type.
_FIXED: dict[str, Any] = {
    "/api/library/items": {
        # Alien's poster was uploaded, and Overture does not hold the image.
        "items": [
            _item(
                1,
                "Alien",
                poster={
                    "source": "upload",
                    "selected": True,
                    "content_hash": "h1",
                    "file": {"hash": "h1"},
                },
            ),
            _item(2, "Aliens"),
        ],
        "total": 2,
    },
    # A field both evaluate is recommended to the wrong kind.
    "/api/collections/recommend-kind": {"kind": "regular", "reason": "Why."},
    "/api/catalog/status": {"enabled": True},
    "/api/catalog/items/1/issue": _issue("movie.yml", "Alien"),
    "/api/catalog/items/2/issue": _issue("show.yml", "Aliens"),
    "/api/collections/tags/radarr": [{"id": 1, "label": "requests"}],
    "/api/collections/arr-options": {"root_folders": [], "quality_profiles": []},
    "/api/collection-groups": [{"name": "Charts", "set": None}],
    "/api/library/items/1/record": {
        "stored": [
            {"table": "media_items", "values": {"id": 1}},
            {
                "table": "media_item_copies",
                "values": {
                    "server_item_id": "m1",
                    "verified_at": "2026-11-01T00:00:00",
                    "labels": ["Kept"],
                },
            },
        ]
    },
}


#: The servers each instance names in MEDIA_SERVERS; the second Plex holds no
#: libraries.
_SERVERS = {
    "plex": [("Plex", "plex")],
    "jellyfin": [("Jellyfin", "jellyfin")],
    "twin": [("Plex", "plex"), ("Plex 4K", "plex")],
}


def _overture(
    host: str, request: httpx2.Request, body: dict[str, Any]
) -> httpx2.Response:
    path = request.url.path
    if request.headers.get(API_KEY_HEADER) != f"{host}-key":
        return httpx2.Response(401, json={"detail": "Invalid API key"})
    movies = request.url.params.get("media_type", "movie") == "movie"
    servers = _SERVERS[host]
    match path:
        case "/api/settings":
            return httpx2.Response(
                200,
                json={
                    "media_servers": [
                        {"id": index, "title": title, "type": kind, "collections": True}
                        for index, (title, kind) in enumerate(servers, start=1)
                    ],
                    "collection_import_unmanaged": True,
                },
            )
        case "/api/collections/capabilities":
            return httpx2.Response(200, json=_capabilities(servers[0][1]))
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
                    # The separator of the Charts group, which Overture keeps.
                    {"ratingKey": "c10", "title": "Charts", "childCount": 0},
                ]
            )
        case "/library/sections/1/genre":
            return container(
                Directory=[
                    {"key": "1", "title": "Horror"},
                    {"key": "2", "title": "Western"},
                    # Plex still lists a genre no movie holds any longer.
                    {"key": "3", "title": "Gone"},
                ]
            )
        case "/library/metadata/m2":
            return container(Metadata=[{"Genre": [{"tag": "Horror"}]}])
        case "/library/sections/1/all" if request.url.params.get("includeMeta"):
            return container(
                Meta={
                    "Type": [
                        {
                            "type": "movie",
                            "Filter": [
                                {"filter": "genre", "key": "/library/sections/1/genre"},
                                {"filter": "unknownFilter"},
                                {"filter": "duplicate"},
                            ],
                            "Field": [
                                {"key": "resolution", "type": "resolution"},
                                # Listed again with its scope.
                                {"key": "movie.unknownFilter", "type": "string"},
                            ],
                            "Sort": [{"key": "titleSort"}],
                        }
                    ],
                    "FieldType": [
                        {"type": "tag", "Operator": [{"key": "=", "title": "is"}]},
                        {"type": "string", "Operator": [{"key": "~", "title": "like"}]},
                        # Plex types its media fields by name.
                        {
                            "type": "resolution",
                            "Operator": [{"key": "=", "title": "is"}],
                        },
                        {"type": "hologram", "Operator": []},
                    ],
                }
            )
        case "/library/sections/1/all" if "genre" in request.url.params:
            held = request.url.params["genre"] != "3"
            return container(totalSize=int(held), size=0)
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
    # Jellyfin knows its libraries by its own ID, never by Overture's.
    if params.get("ParentId", "1") != "1":
        return httpx2.Response(400)
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
            items = [{"Id": "m1", "Name": "Alien"}, {"Id": "m2", "Name": "Aliens"}]
            return httpx2.Response(200, json={"Items": items, "TotalRecordCount": 2})
        case _:
            return httpx2.Response(404)


def _services(request: httpx2.Request) -> httpx2.Response:
    """TMDB, MDBList and Radarr, each holding a little of what Overture reads."""
    path = request.url.path
    match request.url.host:
        case "api.themoviedb.org":
            assert request.headers["Authorization"] == "Bearer tmdb-secret"
            assert "api_key" not in request.url.params
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
    for name in (
        "TMDB_READ_ACCESS_TOKEN",
        "MDBLIST_API_KEY",
        "RADARR_API_KEY",
        "SONARR_API_KEY",
    ):
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

    monkeypatch.setattr(httpx2, "AsyncClient", client)
    return seen


def _args(report: Path | None, url: str, **servers: str) -> Any:
    return argparse.Namespace(
        url=url,
        report=report,
        sources=None,
        insecure=False,
        write=False,
        **{
            **dict.fromkeys(("plex", "jellyfin", "emby", "radarr", "sonarr")),
            **servers,
        },
    )


async def test_a_run_checks_overture_against_plex_and_names_each_problem(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requests: Requests
) -> None:
    monkeypatch.setenv("OVERTURE_API_KEY", "plex-key")
    monkeypatch.setenv("PLEX_TOKEN", "token")
    report = tmp_path / "report.md"

    status = await cli.run(
        _args(report, "http://plex.test", plex="http://plex-server.test")
    )

    assert status == 1
    text = report.read_text()
    assert "| Movies (movie) | field | Genre is 'Horror' | 1 | 2 |" in text
    # Groups of conditions are counted against the titles that make them.
    assert "| groups | any of two | 1 |  |  | Alien | the titles make 2;" in text
    # A source type the library cannot name is said to go untested.
    assert (
        "| source | tmdb_list |  |  |  |  |  | not tested: the library names "
        "none; give one with --sources |"
    ) in text
    # Every managed collection is read on each server given, side by side.
    assert "|  | fields | Scary |" in text
    assert "compared on Plex |" in text
    # The first title only Plex selects is shown with the genres Plex holds.
    assert "only Plex selects Aliens; Plex holds genre='Horror'" in text
    assert "recommends regular, expected smart" in text
    assert "Genre 'horror' is offered as 'Horror'" in text
    assert "| image | Scary poster from the server |" in text
    # A collection whose count differs names the conditions it previewed.
    assert "regular: genre is 'Horror'" in text
    assert "| kept art | uploaded and generated art | 1 |" in text
    assert "Overture lost Alien poster" in text
    # A collection's failed sync is reported with what failed.
    assert (
        "| last sync | Scary |  |  |  |  | Members synced; Automatic assets "
        "failed: Boom |"
    ) in text
    # A chosen poster Overture no longer records as sent is a problem.
    assert (
        "| assets | Scary |  |  |  |  | Overture chose a poster but holds no "
        "record of sending it |"
    ) in text
    assert "HTTP 502" in text
    assert "Overture lacks items m3" in text
    assert "Overture lacks collections Elsewhere (c9, 1 members)" in text
    assert "left out by design: Charts (a separator)" in text
    assert "Overture does not offer western" in text
    assert "no title holds gone" in text
    assert text.count("| plex field | unknownFilter |") == 1
    assert "| plex field | duplicate |" in text
    assert "left out by choice: it tells the library's upkeep" in text
    assert "| plex operator | string ~ (like) |" in text
    assert "| plex operator | hologram |" in text
    assert "resolution" not in text
    assert "opens ['show.yml']" in text
    # Plex is only ever read, and Overture only through its reads.
    assert {method for host, method, _, _ in requests if host == "plex-server"} == {
        "GET"
    }
    assert {
        path for host, method, path, _ in requests if host == "plex" and method != "GET"
    } <= common.OVERTURE_READS


async def test_jellyfin_filters_are_compared_with_the_values_and_counts_offered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requests: Requests
) -> None:
    monkeypatch.setenv("OVERTURE_API_KEY", "jellyfin-key")
    monkeypatch.setenv("JELLYFIN_API_KEY", "jelly")
    report = tmp_path / "report.md"

    await cli.run(
        _args(report, "http://jellyfin.test", jellyfin="http://jellyfin-server.test")
    )

    text = report.read_text()
    assert "| jellyfin values | Genre |" in text
    assert "does not offer drama" in text
    # Overture's copy holds what its last sync read, against the server's save.
    assert (
        "jellyfin says Alien holds 'Drama'; jellyfin saved it at None, and "
        "Overture last read it at 2026-11-01T00:00:00, holding 1 label"
    ) in text
    # Jellyfin counts four horror films where Overture counts one.
    assert "| jellyfin count | Genre is 'Horror' | 1 |  | 4 |" in text
    assert "recommend" not in text
    assert {method for host, method, _, _ in requests if host == "jellyfin-server"} == {
        "GET"
    }


async def test_servers_of_one_kind_in_one_instance_are_checked_through_overture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requests: Requests
) -> None:
    monkeypatch.setenv("OVERTURE_API_KEY", "twin-key")
    monkeypatch.setenv("PLEX_TOKEN", "token")
    report = tmp_path / "report.md"

    await cli.run(_args(report, "http://twin.test", plex="http://plex-server.test"))

    text = report.read_text()
    # Which Plex was given cannot be told, so neither is read directly.
    assert not [host for host, _, _, _ in requests if host == "plex-server"]
    assert "| Movies (movie) | field | Genre is 'Horror' | 1 | 2 |" in text
    assert "## Plex 4K" not in text


async def test_overture_is_never_sent_a_request_that_could_change_it() -> None:
    overture = common.Overture("http://plex.test", "key")
    try:
        with pytest.raises(common.WriteRefusedError):
            await overture.post("/api/collections", {})
    finally:
        await overture.client.aclose()


async def test_keys_and_credentials_are_required(
    monkeypatch: pytest.MonkeyPatch, requests: Requests
) -> None:
    monkeypatch.delenv("OVERTURE_API_KEY", raising=False)
    with pytest.raises(SystemExit, match="OVERTURE_API_KEY"):
        await cli.run(_args(None, "http://plex.test"))

    monkeypatch.setenv("OVERTURE_API_KEY", "key")
    monkeypatch.delenv("PLEX_TOKEN", raising=False)
    with pytest.raises(SystemExit, match="PLEX_TOKEN"):
        await cli.run(_args(None, "http://plex.test", plex="http://plex-server.test"))


def test_the_first_title_the_evaluators_disagree_on_is_found() -> None:
    whole = (True, True)
    assert common.first_difference(["A", "C"], ["A", "B", "C"], complete=whole) == (
        "B",
        True,
    )
    assert common.first_difference(["A", "B"], ["A", "B"], complete=whole) is None
    # A list the preview cut short may hold the title further on.
    assert common.first_difference(["A"], ["A", "B"], complete=(False, True)) is None
    assert common.first_difference(["A"], ["A", "B"], complete=whole) == ("B", True)


async def test_services_are_read_and_compared_without_their_keys_in_the_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, requests: Requests
) -> None:
    monkeypatch.setenv("OVERTURE_API_KEY", "plex-key")
    monkeypatch.setenv("TMDB_READ_ACCESS_TOKEN", "tmdb-secret")
    monkeypatch.setenv("MDBLIST_API_KEY", "mdb-secret")
    monkeypatch.setenv("RADARR_API_KEY", "radarr-secret")
    report = tmp_path / "report.md"

    await cli.run(_args(report, "http://plex.test", radarr="http://radarr.test"))

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
        await cli.run(_args(None, "http://plex.test", sonarr="http://sonarr.test"))


class _Collections:
    """A media server's collections, written as Overture's client writes them."""

    def __init__(self, *, fail_at: str | None = None) -> None:
        self.held: dict[str, ServerCollection] = {
            "old": ServerCollection(
                id="old", title=f"{writes.WRITE_PREFIX} regular", member_ids=()
            ),
            "kept": ServerCollection(id="kept", title="Mine", member_ids=()),
        }
        #: Each collection as the server's own API answers for it.
        self.items: dict[str, dict[str, Any]] = {}
        self.fail_at = fail_at
        self.closed = False
        #: How many more times the server saves each collection, as the
        #: refreshes its membership writes queue do.
        self.saving: dict[str, int] = {}
        self.refreshes = 0

    async def list_collections(self) -> list[ServerCollection]:
        return list(self.held.values())

    async def get_sections(self) -> list[Any]:
        return [ServerSection("1", "Movies", MediaType.MOVIE, library_id="1:1")]

    async def create_collection(
        self, _library: str, title: str, _media: Any, members: list[str]
    ) -> ServerCollection:
        made = ServerCollection(id=title, title=title, member_ids=tuple(members))
        self.held[made.id] = made
        self.items[made.id] = {"Name": title, "ImageTags": {}, "Etag": 0}
        self.saving[made.id] = self.refreshes
        return made

    async def get_collection_member_ids(self, collection_id: str) -> list[str]:
        return list(self.held[collection_id].member_ids)

    async def set_collection_members(
        self, collection_id: str, members: list[str], **_kwargs: Any
    ) -> MemberWrite:
        if self.fail_at == "members":
            # The server refuses the request, as Overture's client reports it.
            request = httpx2.Request(
                "POST", f"http://jellyfin.test/Collections/{collection_id}/Items?ids=a"
            )
            response = httpx2.Response(400, text="Bad ids", request=request)
            cause = httpx2.HTTPStatusError("400", request=request, response=response)
            raise MediaServerError(
                "Verify returned an unsuccessful response"
            ) from cause
        # Jellyfin keeps its own order.
        before = set(self.held[collection_id].member_ids)
        self.held[collection_id] = replace(
            self.held[collection_id], member_ids=tuple(sorted(members))
        )
        return MemberWrite(
            members, len(set(members) - before), len(before - set(members))
        )

    async def update_collection_details(
        self, collection_id: str, _library: str, details: CollectionDetails
    ) -> None:
        if self.fail_at == "details":
            # The server answers the edit but keeps what it had.
            return
        self.held[collection_id] = replace(
            self.held[collection_id], title=details.title
        )
        # Jellyfin locks what Overture's client sends with a value.
        self.items[collection_id] |= {
            "Name": details.title,
            "ForcedSortName": details.sort_title,
            "Overview": details.summary,
            "LockedFields": ["Name", *(["Overview"] if details.summary else [])],
            "DisplayOrder": "SortName"
            if details.order is CollectionOrder.TITLE_ASC
            else "PremiereDate",
        }

    async def upload_collection_art(
        self, collection_id: str, art_type: Any, *_args: Any
    ) -> None:
        if art_type is ArtType.POSTER:
            self.items[collection_id]["ImageTags"] = {"Primary": "new"}

    async def delete_collection(self, collection_id: str) -> None:
        if self.saving.get(collection_id):
            # The refresh still saving it puts it back, as Jellyfin's does.
            self.held[f"{collection_id} again"] = replace(
                self.held[collection_id], id=f"{collection_id} again"
            )
        del self.held[collection_id]

    async def close(self) -> None:
        self.closed = True


class _Jellyfin(media_browser.MediaBrowserServer):
    def __init__(self, server: _Collections) -> None:
        super().__init__("jellyfin", "http://jellyfin.test", "key")
        self.server_state = server

    @override
    async def items(self, library_id: str, media_type: str, **params: Any) -> Any:
        return {"Items": [{"Id": "a"}, {"Id": "b"}, {"Id": "c"}]}

    @override
    async def get(self, path: str, **params: Any) -> Any:
        if path == "/Users":
            return [{"Id": "admin", "Policy": {"IsAdministrator": True}}]
        if path.startswith("/Users/admin/Items/"):
            return self.server_state.items[path.rsplit("/", 1)[1]]
        if path.startswith("/Items/"):
            # The metadata editor's read, which Jellyfin makes as a user.
            assert params == {"userId": "admin"}
            return self.server_state.items.get(path.removeprefix("/Items/"), {})
        assert path == "/Items"
        found = self.server_state.items.get(params["Ids"])
        if found and self.server_state.saving.get(params["Ids"]):
            self.server_state.saving[params["Ids"]] -= 1
            found["Etag"] += 1
        return {"Items": [found] if found else []}


@pytest.mark.parametrize("fail_at", [None, "members"])
async def test_writes_touch_only_their_own_collections_and_delete_them_whatever_fails(
    monkeypatch: pytest.MonkeyPatch, fail_at: str | None
) -> None:
    server = _Collections(fail_at=fail_at)

    def provider(*_args: object, **_kwargs: object) -> tuple[Any, Any]:
        return server, server

    monkeypatch.setattr(writes, "write_provider", provider)
    monkeypatch.setattr(writes, "SETTLE_SECONDS", 0)
    direct = _Jellyfin(server)
    try:
        cases = await writes.WriteCheck(
            direct, "http://jellyfin.test", "key", verify=True
        ).run()
    finally:
        await direct.client.aclose()

    # A collection left by a killed run is deleted, and only Overture's go.
    assert list(server.held) == ["kept"]
    assert server.closed
    problems = {case.label: case.problem for case in cases if case.problem}
    # Each step is reported on its own, the refused request named, and the
    # steps after a refused one still run; this server keeps no background.
    refused = (
        "Verify returned an unsuccessful response: POST "
        "/Collections/zz Overture verify regular/Items answered 'Bad ids'"
    )
    assert problems == {
        **(
            {
                "replace a member": refused,
                "keep the images' names through an edit": refused,
                # Filling a large collection is a membership write too.
                f"create a collection of up to {writes.LARGE_COLLECTION} members": (
                    refused.replace("verify regular", "verify large")
                ),
            }
            if fail_at
            else {}
        ),
        "upload a poster and a background": "the server names the same background",
    }


@pytest.mark.parametrize("settle", [True, False])
async def test_a_collection_is_deleted_once_its_server_stops_saving_it(
    monkeypatch: pytest.MonkeyPatch, *, settle: bool
) -> None:
    server = _Collections()
    server.refreshes = 2

    def provider(*_args: object, **_kwargs: object) -> tuple[Any, Any]:
        return server, server

    async def unsettled(*_args: object) -> None:
        return None

    monkeypatch.setattr(writes, "write_provider", provider)
    monkeypatch.setattr(writes, "SETTLE_SECONDS", 0)
    if not settle:
        monkeypatch.setattr(writes.WriteCheck, "settled", unsettled)
    direct = _Jellyfin(server)
    try:
        cases = await writes.WriteCheck(
            direct, "http://jellyfin.test", "key", verify=True
        ).run()
    finally:
        await direct.client.aclose()

    deleted = next(case for case in cases if case.label.startswith("delete the"))
    # Deleted while a refresh saves it, the server makes it again; it is
    # reported, and deleted too.
    assert deleted.problem == (
        ""
        if settle
        else f"the server made '{writes.WRITE_PREFIX} edited' (zz Overture verify "
        f"regular again, 2 members), '{writes.WRITE_PREFIX} large' (zz Overture "
        "verify large again, 3 members) itself"
    )
    assert list(server.held) == ["kept"]


async def test_writes_fill_a_large_collection_and_explain_an_unsaved_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    server = _Collections(fail_at="details")

    def provider(*_args: object, **_kwargs: object) -> tuple[Any, Any]:
        return server, server

    monkeypatch.setattr(writes, "write_provider", provider)
    monkeypatch.setattr(writes, "SETTLE_SECONDS", 0)
    direct = _Jellyfin(server)
    try:
        cases = {
            case.label: case
            for case in await writes.WriteCheck(
                direct, "http://jellyfin.test", "key", verify=True
            ).run()
        }
    finally:
        await direct.client.aclose()

    large = cases[f"create a collection of up to {writes.LARGE_COLLECTION} members"]
    assert (large.count, large.held, large.problem) == (3, 3, "")
    edit = cases["edit the title, sort title, summary and order"]
    assert edit.problem.startswith("the server holds another title")
    # Read as an administrator, the title shows the edit was never saved.
    assert (
        edit.note == f"an administrator sees the title '{writes.WRITE_PREFIX} regular'"
    )


def test_the_kind_expected_follows_who_tests_the_condition() -> None:
    plex = {"operators": ["is"], "smart_operators": ["is"], "labelled": False}
    labelled = {**plex, "labelled": True}
    only_plex = {"operators": [], "smart_operators": ["is"], "labelled": False}
    assert common.expected_kind(plex, "is") == "smart"
    # A label Overture keeps is refreshed on each sync, so it suits regular.
    assert common.expected_kind(labelled, "is") == "regular"
    assert common.expected_kind(only_plex, "is") == "smart"


def test_a_collection_overture_leaves_out_is_named_with_why() -> None:
    listing = common.Listing(frozenset({"charts"}), import_unmanaged=False)
    assert listing.reason("Charts", 0, None, "movie") == "a separator"
    assert listing.reason("Old", 0, None, "movie") == "empty"
    assert listing.reason("Seasons", 3, "season", "show") == "holds seasons"
    assert "importing unmanaged collections is off" in listing.reason(
        "Mine", 3, "show", "show"
    )
    assert not common.Listing(frozenset(), import_unmanaged=True).reason(
        "Mine", 3, None, "show"
    )


class _Previews:
    """Previews where Plex selects one title Overture leaves out, in 1994."""

    def __init__(self) -> None:
        self.titles = {f"Film {index:03}": 1950 + index % 60 for index in range(200)}
        self.sent = 0

    async def preview(
        self, rule: dict[str, Any], _collection_id: int | None = None
    ) -> list[dict[str, Any]]:
        self.sent += 1
        bounds = {
            condition["operator"]: condition["value"]
            for condition in rule["libraries"][0]["criteria"]["conditions"]
            if condition["field"] == "year"
        }
        selected = sorted(
            title
            for title, year in self.titles.items()
            if bounds.get("gte", 0) <= year <= bounds.get("lte", 9999)
            and (rule["smart"] or title != "Film 104")
        )
        return [
            {
                "library_id": "1:1",
                "member_count": len(selected),
                "members": selected[:20],
            }
        ]


async def test_the_years_are_narrowed_until_the_title_that_differs_is_named() -> None:
    previews = _Previews()
    library = verify_library.Library(
        cast("Any", previews),
        "Plex",
        _capabilities("plex"),
        "movie",
        {"id": "1:1", "title": "Movies"},
        set(),
        [{"title": title, "year": year} for title, year in previews.titles.items()],
        [],
        None,
        common.Listing(frozenset(), import_unmanaged=True),
        lead=True,
    )
    first = common.Members(199, sorted(previews.titles)[:20])
    span, ours, theirs = await library.narrow(
        {"field": "genre"}, first, common.Members(200, sorted(previews.titles)[:20])
    )

    assert span is not None
    assert span[0] <= 1994 <= span[1]
    assert ours.whole
    assert theirs.whole
    assert common.first_difference(ours.names, theirs.names, complete=(True, True)) == (
        "Film 104",
        True,
    )
    # Halving the years takes a handful of previews, not one per year.
    assert previews.sent <= 20


def test_a_refused_request_is_named_with_what_the_server_answered() -> None:
    request = httpx2.Request(
        "GET", "http://plex.test/library/sections/1/all?title%3D%3D=x"
    )
    response = httpx2.Response(500, text="  Internal\n error ", request=request)
    error = httpx2.HTTPStatusError("500", request=request, response=response)
    assert common.failure(error) == (
        "HTTP 500: GET /library/sections/1/all answered 'Internal error'"
    )


async def test_the_character_plex_refuses_in_a_text_value_is_named(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def plex(request: httpx2.Request) -> httpx2.Response:
        # Plex fails on a quote in an exact match, and reads a doubled one.
        query = request.url.query.decode()
        if "%27%27" in query:
            return httpx2.Response(200, json={"MediaContainer": {"totalSize": 1}})
        if "%27" in query:
            return httpx2.Response(500)
        return httpx2.Response(200, json={"MediaContainer": {"totalSize": 0}})

    original = httpx2.AsyncClient

    def client(**kwargs: Any) -> httpx2.AsyncClient:
        return original(transport=httpx2.MockTransport(plex), **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", client)
    server = verify_plex.PlexServer("http://plex-server.test", "token")
    library = cast("Any", type("L", (), {"key": "2", "media_type": "show"}))
    try:
        note = await server.refused(
            library,
            {
                "kind": "field",
                "field": "title",
                "operator": "is",
                "value": "'Allo 'Allo!",
            },
        )
    finally:
        await server.client.aclose()

    assert note == (
        "Plex answers once \"'\" is left out of the value; with ' doubled it selects 1"
    )


class _Offers:
    """An Overture that offers Drama alone and counts one title of each value."""

    async def get(self, path: str, **params: Any) -> Any:
        assert path == "/api/collections/field-values"
        return [{"value": "Drama", "label": "Drama", "count": 1}]

    async def preview(
        self, rule: dict[str, Any], _collection_id: int | None = None
    ) -> list[dict[str, Any]]:
        return [{"library_id": "3:1", "member_count": 1, "members": ["Alien"]}]


async def test_a_server_that_does_not_lead_differs_in_details_but_not_in_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def emby(request: httpx2.Request) -> httpx2.Response:
        # Emby lists each filter's values at its own address.
        assert request.url.params["ParentId"] == "1"
        names = {
            "/emby/Genres": ["Drama", "Horror"],
            "/emby/Tags": ["Kept", "Drama"],
            "/emby/OfficialRatings": [],
            "/emby/Years": [],
        }
        if request.url.path in names:
            rows = [{"Name": name} for name in names[request.url.path]]
            return httpx2.Response(200, json={"Items": rows})
        return httpx2.Response(200, json={"Items": [], "TotalRecordCount": 4})

    original = httpx2.AsyncClient

    def client(**kwargs: Any) -> httpx2.AsyncClient:
        return original(transport=httpx2.MockTransport(emby), **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", client)
    capabilities = _capabilities("emby")
    capabilities["fields"].append(
        {**capabilities["fields"][0], "field": "label", "label": "Tag"}
    )
    library = verify_library.Library(
        cast("Any", _Offers()),
        "Emby",
        capabilities,
        "movie",
        {"id": "3:1", "title": "Movies"},
        set(),
        [],
        [],
        None,
        common.Listing(frozenset(), import_unmanaged=True),
        lead=False,
    )
    server = media_browser.MediaBrowserServer("emby", "http://emby.test", "key")
    try:
        await server.check_library(library)
    finally:
        await server.client.aclose()

    problems = {case.label: case.problem for case in library.cases if case.problem}
    notes = {case.label: case.note for case in library.cases}
    # The lead server gives the genres, so Emby's own are only noted.
    assert "Genre" not in problems
    assert "Overture does not offer horror" in notes["Genre"]
    assert media_browser.LEAD_DETAILS in notes["Genre is 'Drama'"]
    # Labels are Emby's own, so one Overture lacks, or counts apart, is a problem.
    assert problems == {
        "Tag": "Overture does not offer kept",
        "Tag is 'Kept'": "counts differ",
    }


async def test_servers_are_asked_what_overture_cannot_see_for_itself(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def server(request: httpx2.Request) -> httpx2.Response:
        params = request.url.params
        match request.url.path:
            case "/Users":
                users: list[dict[str, Any]] = [
                    {"Id": "u1", "Name": "guest", "Policy": {}},
                    {"Id": "u2", "Name": "admin", "Policy": {"IsAdministrator": True}},
                ]
                return httpx2.Response(200, json=users)
            case "/Items" if params.get("Ids") == "hidden":
                # Jellyfin answers the item to a user only.
                rows = (
                    [{"Name": "Dune", "Type": "Movie", "Path": "/m/Dune.mkv"}]
                    if params.get("UserId") == "u2"
                    else []
                )
                return httpx2.Response(200, json={"Items": rows})
            case "/Items":
                # The members show only to a user.
                count = 2 if params.get("UserId") == "u2" else 0
                return httpx2.Response(
                    200, json={"Items": [], "TotalRecordCount": count}
                )
            case "/library/sections/1/collections":
                rows = [
                    {"ratingKey": "c1", "title": "BFI Greats", "index": 7},
                    {"ratingKey": "c2", "title": "Kept", "index": 8},
                ]
                return httpx2.Response(200, json={"MediaContainer": {"Metadata": rows}})
            case _:
                return httpx2.Response(404)

    original = httpx2.AsyncClient

    def client(**kwargs: Any) -> httpx2.AsyncClient:
        return original(transport=httpx2.MockTransport(server), **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", client)
    jellyfin = media_browser.MediaBrowserServer(
        "jellyfin", "http://jellyfin.test", "key"
    )
    plex = verify_plex.PlexServer("http://plex-server.test", "token")
    library = cast(
        "Any",
        type(
            "L",
            (),
            {
                "key": "1",
                "id": "1:1",
                "collections": [
                    {
                        "id": 3,
                        "copies": [{"server_item_id": "c1", "library_ids": ["1:1"]}],
                    }
                ],
            },
        ),
    )
    try:
        members = await jellyfin.members_to_a_user("box")
        counted = await jellyfin.member_count("box")
        hidden = await jellyfin.unlisted("hidden")
        # Plex lists collection 7 under the title its tag holds; criteria name
        # it by Overture's ID, and one Overture does not list is left out.
        values = await plex.criteria_values(
            library,
            "collection",
            {"greats": "7", "kept": "8", "gone": "9"},
            keyed=False,
        )
    finally:
        await jellyfin.client.aclose()
        await plex.client.aclose()

    assert members == "jellyfin lists 2 members to admin, and none to the API key alone"
    # Overture lists a Jellyfin collection's members as an administrator.
    assert counted == 2
    assert hidden == (
        "jellyfin answers hidden as Dune (Movie) at /m/Dune.mkv, to a user only"
    )
    assert values == {"3": "7"}


async def test_collection_assets_and_plex_themes_are_read_from_asset_deliveries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def collection_row(
        identity: int, title: str, *, theme: dict[str, Any], poster: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            **_collection(identity, title, managed=True),
            "server_poster_version": None,
            "assets": _assets(poster=poster, theme=theme),
        }

    # Collection 1 matches Plex; 2 has a queued theme not yet on Plex; 3 has a
    # theme only on another server while Plex holds one Overture does not know.
    collections = [
        collection_row(
            1,
            "Held",
            poster={"status": "complete", "selected": True, "content_hash": "h1"},
            theme={
                "status": "complete",
                "selected": True,
                "youtube_id": "yt1",
                "deliveries": [
                    {
                        "server_id": 1,
                        "channel": "upload",
                        "required": True,
                        "delivered": True,
                        "present": True,
                        "checked_at": None,
                    }
                ],
            },
        ),
        collection_row(
            2,
            "Queued",
            poster={"status": "missing", "selected": False},
            theme={
                "status": "partial",
                "selected": True,
                "youtube_id": "yt2",
                "deliveries": [
                    {
                        "server_id": 1,
                        "channel": "upload",
                        "required": True,
                        "delivered": False,
                        "present": False,
                        "checked_at": None,
                    }
                ],
            },
        ),
        collection_row(
            3,
            "OtherServer",
            poster={"status": "missing", "selected": False},
            theme={
                "status": "partial",
                "selected": False,
                "deliveries": [
                    {
                        "server_id": 2,
                        "channel": "upload",
                        "required": True,
                        "delivered": True,
                        "present": True,
                        "checked_at": None,
                    }
                ],
            },
        ),
    ]

    def plex(request: httpx2.Request) -> httpx2.Response:
        match request.url.path:
            case "/library/sections/1/all":
                return httpx2.Response(200, json={"MediaContainer": {"Metadata": []}})
            case "/library/sections/1/collections":
                return httpx2.Response(
                    200,
                    json={
                        "MediaContainer": {
                            "Metadata": [
                                {
                                    "ratingKey": "c1",
                                    "title": "Held",
                                    "childCount": 3,
                                    "smart": 0,
                                    "thumb": "/library/metadata/c1/thumb/1",
                                    "theme": "/library/metadata/c1/theme/1",
                                },
                                {
                                    "ratingKey": "c2",
                                    "title": "Queued",
                                    "childCount": 3,
                                    "smart": 0,
                                },
                                {
                                    "ratingKey": "c3",
                                    "title": "OtherServer",
                                    "childCount": 3,
                                    "smart": 0,
                                    "theme": "/library/metadata/c3/theme/1",
                                },
                            ]
                        }
                    },
                )
            case _:
                return httpx2.Response(404)

    def overture_handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path == "/api/collections/1/local-image/poster":
            assert request.url.params.get("t") == "h1"
            return httpx2.Response(
                200, content=b"png", headers={"content-type": "image/png"}
            )
        return httpx2.Response(404)

    original = httpx2.AsyncClient

    def client(**kwargs: Any) -> httpx2.AsyncClient:
        def dispatch(request: httpx2.Request) -> httpx2.Response:
            if request.url.host == "plex-server.test":
                return plex(request)
            return overture_handler(request)

        return original(transport=httpx2.MockTransport(dispatch), **kwargs)

    monkeypatch.setattr(httpx2, "AsyncClient", client)
    overture = common.Overture("http://overture.test", "key")
    plex_server = verify_plex.PlexServer("http://plex-server.test", "token")
    library = verify_library.Library(
        overture,
        "Plex",
        _capabilities("plex"),
        "movie",
        {"id": "1:1", "title": "Movies"},
        set(),
        [],
        collections,
        plex_server,
        common.Listing(frozenset(), import_unmanaged=True),
        lead=True,
    )
    try:
        await plex_server.check_inventory(library)
        for row in collections:
            library.check_assets(row, str(row["copies"][0]["server_item_id"]))
            await library.check_images(row)
    finally:
        await overture.client.aclose()
        await plex_server.client.aclose()

    problems = {
        (case.check, case.label): case.problem for case in library.cases if case.problem
    }
    assert problems == {
        (
            "inventory",
            "OtherServer members",
        ): "Plex holds a theme Overture does not know",
        ("assets", "Queued"): "the server holds none of the theme Overture holds",
    }


def test_a_servers_fields_are_held_and_locked_as_overture_wrote_them() -> None:
    held = common.HeldFields(
        title="Alien",
        sort_title="Alien",
        summary="",
        locked=frozenset({"title", "sort title", "summary"}),
    )
    assert held.against("Alien", "Alien", "") == [
        "summary locked with no value from Overture"
    ]
    assert held.against("Aliens", "", "") == [
        "title 'Alien', not 'Aliens'",
        "sort title locked with no value from Overture",
        "summary locked with no value from Overture",
    ]
    loose = replace(held, locked=frozenset({"title"}))
    assert loose.against("Alien", "Alien", "") == ["sort title unlocked"]


def test_the_same_edit_is_set_side_by_side_on_every_server() -> None:
    def check(server: str, locked: set[str]) -> writes.WriteCheck:
        found = object.__new__(writes.WriteCheck)
        found.direct = cast("Any", type("Direct", (), {"server": server})())
        found.edited = common.HeldFields("t", "s", "m", frozenset(locked))
        return found

    alike = writes.compare_writes(
        [check("plex", {"title", "summary"}), check("jellyfin", {"title", "summary"})]
    )
    assert (alike.error, alike.note) == ("", "compared jellyfin, plex")
    apart = writes.compare_writes(
        [check("plex", {"title", "summary"}), check("emby", {"title"})]
    )
    assert apart.error.startswith("they differ in what they lock")
