"""The read-only checks of Overture and each media server it names."""

lazy import argparse
lazy import os
lazy from typing import Any

lazy import httpx2

lazy from .common import (
    ApiError,
    Case,
    Listing,
    Overture,
    collection_copy,
    failure,
    inventory,
    item_copy_id,
    named,
)
lazy from .library import Library
lazy from .media_browser import MediaBrowserServer, check_media_browser_collections
lazy from .plex import PlexServer


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
                group["name"].casefold()
                for group in await overture.get("/api/collection-groups")
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
        cases.extend(await compare_servers(everything, servers, direct))
    finally:
        await overture.client.aclose()
    return cases


async def compare_servers(
    everything: list[dict[str, Any]],
    servers: list[dict[str, Any]],
    direct: dict[str, PlexServer | MediaBrowserServer],
) -> list[Case]:
    """Read each managed collection's fields on every server given, side by side.

    Every server copy must hold what Overture says its sync wrote, locked, and
    leave unlocked what Overture has no value for, so the servers agree with
    Overture and so with each other.
    """
    kinds = [server["type"] for server in servers]
    given = {
        server["id"]: (server["title"], paired)
        for server in servers
        if kinds.count(server["type"]) == 1
        and (paired := direct.get(server["type"])) is not None
    }
    cases: list[Case] = []
    for row in everything:
        if not row["managed"] or row["withheld"] or row["unsynced"]:
            continue
        copies = [
            (given[copy["server_id"]], str(copy["server_item_id"]))
            for copy in row["copies"]
            if copy["server_id"] in given and copy["server_item_id"]
        ]
        if not copies:
            continue
        case = Case("every server", "", "fields", row["title"])
        problems: list[str] = []
        for (title, server), collection_id in copies:
            try:
                held = await server.fields(collection_id)
            except httpx2.HTTPError as exc:
                problems.append(f"{title}: {failure(exc)}")
                continue
            problems.extend(
                f"{title}: {problem}"
                for problem in held.against(
                    row["title"], row["sort_title"] or "", row["summary"] or ""
                )
            )
        case.note = "compared on " + named({title for (title, _), _ in copies})
        case.error = "; ".join(problems)
        cases.append(case)
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
