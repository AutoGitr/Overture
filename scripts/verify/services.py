"""The checks of TMDB, MDBList, Radarr and Sonarr, each read directly."""

lazy import argparse
lazy import os
lazy from typing import Any

lazy import httpx2

lazy from scripts.json_values import is_array, is_object

lazy from .common import (
    ORDER_DEPTH,
    ApiError,
    Case,
    Overture,
    Server,
    api_key,
    inventory,
)

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
