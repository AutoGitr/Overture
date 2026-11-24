"""Jellyfin and Emby, read directly, as the checks compare Overture with them."""

lazy from typing import Any

lazy import httpx2

lazy from scripts.json_values import is_object

lazy from .common import (
    ApiError,
    Case,
    Listing,
    Server,
    ServerArt,
    collection_inventory,
    failure,
    inventory,
    item_copy_id,
    named,
    single,
)
lazy from .library import Library

#: The overture field each Jellyfin and Emby item filter tests, by the filter's
#: query parameter and the name ``/Items/Filters`` lists its values under.
MEDIA_BROWSER_FILTERS: dict[str, tuple[str, str]] = {
    "genre": ("Genres", "Genres"),
    "label": ("Tags", "Tags"),
    "content_rating": ("OfficialRatings", "OfficialRatings"),
    "year": ("Years", "Years"),
}


MEDIA_BROWSER_TYPES = {"movie": "Movie", "show": "Series"}


#: The filters testing what each server holds of its own copy of a title; the
#: lead server gives the rest of the details of the titles it holds.
PER_COPY = frozenset({"label"})


LEAD_DETAILS = "the lead server gives the details of the titles it holds too"


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
        #: An administrator, once asked for; empty when the server has none.
        self._administrator: dict[str, Any] | None = None

    async def libraries(self, media_type: str) -> dict[str, str]:
        wanted = {"movie": "movies", "show": "tvshows"}[media_type]
        found = await self.get(
            "/Library/VirtualFolders/Query"
            if self.server == "emby"
            else "/Library/VirtualFolders"
        )
        rows = found["Items"] if is_object(found) else found
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
            # Grouping into collections lists a collection in place of its
            # titles, as Overture's sync must not see them either.
            **(
                {"CollapseBoxSetItems": "false"}
                if self.server == "jellyfin"
                else {"GroupItemsIntoCollections": "false"}
            ),
            **params,
        )

    async def item(self, item_id: str) -> dict[str, Any]:
        """One item as the server holds it.

        Asked as a query by ID: Jellyfin 12 refuses ``/Items/{id}`` without a
        user, which an API key has none of.
        """
        found = await self.get("/Items", Ids=item_id, Fields="SortName,Overview")
        rows: list[dict[str, Any]] = found["Items"]
        return rows[0] if rows else {}

    async def filter_values(self, library: Library) -> dict[str, list[Any]]:
        """The values the server lists for each of its item filters in a library."""
        kind = MEDIA_BROWSER_TYPES[library.media_type]
        if self.server == "jellyfin":
            return await self.get(
                "/Items/Filters", ParentId=library.key, IncludeItemTypes=kind
            )
        # Emby lists each filter's values on its own.
        found: dict[str, list[Any]] = {}
        for _, listed in MEDIA_BROWSER_FILTERS.values():
            try:
                rows = await self.get(
                    f"/{listed}",
                    ParentId=library.key,
                    IncludeItemTypes=kind,
                    Recursive="true",
                )
            except httpx2.HTTPError as exc:
                library.case(f"{self.server} filter", listed).error = failure(exc)
                continue
            found[listed] = [row["Name"] for row in rows["Items"]]
        return found

    async def check_library(self, library: Library) -> None:
        """Compare what Overture lists and counts with what the server does."""
        found = await self.items(library.key, library.media_type, Fields="")
        ours = {item_copy_id(item, library.id) for item in library.items}
        theirs = {str(row["Id"]) for row in found["Items"]}
        case = library.case("inventory", "items")
        inventory(case, ours, theirs, noun="items")
        if extra := sorted(ours - theirs):
            case.note = await self.unlisted(extra[0])
        filters = await self.filter_values(library)
        for field_name, (param, listed) in MEDIA_BROWSER_FILTERS.items():
            spec = library.fields.get(field_name)
            values = [str(value) for value in filters.get(listed) or []]
            if spec is None:
                if values:
                    library.case(
                        f"{self.server} filter", param
                    ).error = "Overture does not offer this filter"
                continue
            differs = "" if library.lead or field_name in PER_COPY else LEAD_DETAILS
            if spec["kind"] == "tag":
                try:
                    await library.values(field_name)
                except ApiError:
                    continue
                case = library.case(f"{self.server} values", spec["label"])
                offered = library.offered_values(field_name)
                case.note = (
                    f"Overture offers {len(offered)}, {self.server} lists {len(values)}"
                )
                spelt = {value.casefold(): value for value in values}
                if missing := set(spelt) - offered:
                    problem = f"Overture does not offer {named(missing)}"
                    if differs:
                        case.note += f"; {problem}: {differs}"
                    else:
                        case.error = problem
                        first = spelt[min(missing)]
                        case.note += await self.held_by(library, param, first)
            if not values:
                continue
            value = values[0]
            case = library.case(f"{self.server} count", f"{spec['label']} is {value!r}")
            case.differs = differs
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
                library.key, library.media_type, Limit=0, **{param: value}
            )
            case.held = counted["TotalRecordCount"]
            if case.mismatch and differs:
                case.note = differs

    async def seen_by_a_user(self, item_id: str) -> str:
        """Name the title an administrator sees, beside what the API key lists.

        A difference shows the API key's listing lags a saved edit; the same
        title shows the server did not save it.
        """
        admin = await self.administrator()
        if admin is None:
            return "the server has no administrator to ask"
        row = await self.get(f"/Users/{admin['Id']}/Items/{item_id}")
        return f"an administrator sees the title {row.get('Name')!r}"

    async def editor_item(self, item_id: str) -> dict[str, Any]:
        """One item with every field, as the server's metadata editor reads it."""
        admin = await self.administrator()
        if admin is None:
            return {}
        if self.server == "jellyfin":
            return await self.get(f"/Items/{item_id}", userId=admin["Id"])
        return await self.get(f"/Users/{admin['Id']}/Items/{item_id}")

    async def administrator(self) -> dict[str, Any] | None:
        """A user who sees every library, fetched once."""
        if self._administrator is None:
            users: list[dict[str, Any]] = await self.get("/Users")
            policies: list[dict[str, Any]] = [
                user.get("Policy") or {} for user in users
            ]
            self._administrator = next(
                (
                    user
                    for user, policy in zip(users, policies, strict=True)
                    if policy.get("IsAdministrator")
                ),
                dict[str, Any](),
            )
        return self._administrator or None

    async def has_theme(self, collection_id: str) -> bool:
        """Whether the server plays a theme for the collection, asked as a user."""
        admin = await self.administrator()
        found = await self.get(
            f"/Items/{collection_id}/ThemeSongs",
            InheritFromParent="false",
            **({"UserId": admin["Id"]} if admin else {}),
        )
        return bool(found["TotalRecordCount"])

    async def member_count(self, collection_id: str) -> int:
        """The members of a collection, as Overture lists them.

        Jellyfin lists them only to a user, so Overture asks as an
        administrator; Emby lists them to the API key.
        """
        admin = await self.administrator() if self.server == "jellyfin" else None
        found = await self.get(
            "/Items",
            ParentId=collection_id,
            Limit=0,
            **({"UserId": admin["Id"]} if admin else {}),
        )
        return found["TotalRecordCount"]

    async def unlisted(self, item_id: str) -> str:
        """What the server holds under an ID its library listing leaves out."""
        found = await self.get("/Items", Ids=item_id, Fields="Path")
        admin = await self.administrator()
        seen: list[dict[str, Any]] = (
            (await self.get("/Items", Ids=item_id, UserId=admin["Id"], Fields="Path"))[
                "Items"
            ]
            if admin
            else []
        )
        rows: list[dict[str, Any]] = found["Items"] or seen
        if not rows:
            return f"{self.server} holds no item {item_id}, to the API key or a user"
        row = rows[0]
        to_whom = "the API key" if found["Items"] else "a user only"
        return (
            f"{self.server} answers {item_id} as {row.get('Name')} "
            f"({row.get('Type')}) at {row.get('Path')}, to {to_whom}"
        )

    async def members_to_a_user(self, collection_id: str) -> str:
        """How many members the server lists in a collection to an administrator.

        Told apart from the none it lists to the API key alone, this shows
        whether the server lists a collection's members only to a user.
        """
        admin = await self.administrator()
        if admin is None:
            return f"{self.server} has no administrator to ask as"
        found = await self.get(
            "/Items", ParentId=collection_id, UserId=admin["Id"], Limit=0
        )
        return (
            f"{self.server} lists {found['TotalRecordCount']} members to "
            f"{admin['Name']}, and none to the API key alone"
        )

    async def held_by(self, library: Library, param: str, value: str) -> str:
        """Name a title the server says holds a value, and what Overture keeps of it.

        Overture's copy of the title holds the labels its last sync of it read,
        so a label added on the server since then is not there yet.
        """
        found = await self.items(
            library.key,
            library.media_type,
            Limit=1,
            Fields="DateLastSaved",
            **{param: value},
        )
        if not found["Items"]:
            return ""
        row = found["Items"][0]
        note = f"; {self.server} says {row['Name']} holds {value!r}"
        item = next(
            (
                item
                for item in library.items
                if item_copy_id(item, library.id) == str(row["Id"])
            ),
            None,
        )
        if item is None:
            return f"{note}, as item {row['Id']}, which no title Overture lists holds"
        record = await library.overture.get(f"/api/library/items/{item['id']}/record")
        copy = next(
            (
                stored["values"]
                for stored in record["stored"]
                if stored["table"] == "media_item_copies"
                and stored["values"].get("server_item_id") == str(row["Id"])
            ),
            None,
        )
        if copy is None:
            return note + ", whose copy Overture does not hold"
        labels: list[str] = copy.get("labels") or []
        return (
            f"{note}; {self.server} saved it at {row.get('DateLastSaved')}, and "
            f"Overture last read it at {copy.get('verified_at')}, holding "
            f"{len(labels)} label{'' if len(labels) == 1 else 's'}"
        )

    async def collection_ids(self) -> dict[str, dict[str, Any]]:
        found = await self.get(
            "/Items", IncludeItemTypes="BoxSet", Recursive="true", Fields="ChildCount"
        )
        return {str(row["Id"]): row for row in found["Items"]}


async def check_media_browser_collections(
    direct: MediaBrowserServer,
    server_id: int,
    collections: list[dict[str, Any]],
    listing: Listing,
) -> tuple[list[Case], dict[str, int], dict[str, ServerArt]]:
    """BoxSets live outside libraries, so they are compared once per server.

    Returns the cases, and the members the server counts in and the art it
    shows of each BoxSet Overture lists.
    """
    listed = await direct.collection_ids()
    mine = {
        str(copy["server_item_id"]): row
        for row in collections
        for copy in row["copies"]
        if copy["server_id"] == server_id
    }
    case = Case(direct.server, "", "inventory", "collections")
    # A BoxSet holds movies and shows alike, so what it holds is not told apart.
    skipped = collection_inventory(
        case,
        listing,
        "",
        mine,
        {
            key: (row["Name"], row.get("ChildCount"), None)
            for key, row in listed.items()
        },
    )
    # Sync leaves out a collection whose members it cannot place in a library.
    if lacking := sorted(set(listed) - set(mine) - skipped):
        members = await direct.get("/Items", ParentId=lacking[0], Limit=0)
        if not members["TotalRecordCount"]:
            case.note = "; ".join(
                part
                for part in (
                    case.note,
                    f"{listed[lacking[0]]['Name']}: "
                    + await direct.members_to_a_user(lacking[0]),
                )
                if part
            )
    cases = [case]
    held: dict[str, int] = {}
    shown: dict[str, ServerArt] = {}
    for key, row in listed.items():
        if (ours := mine.get(key)) is None:
            continue
        held[key] = await direct.member_count(key)
        tags: dict[str, Any] = row.get("ImageTags") or {}
        shown[key] = ServerArt(
            poster="Primary" in tags,
            background=bool(row.get("BackdropImageTags")),
            theme=await direct.has_theme(key) if direct.server == "jellyfin" else None,
        )
        found = Case(direct.server, "", "inventory", f"{row['Name']} members")
        found.held = held[key]
        if len(ours["copies"]) == 1:
            found.count = ours["child_count"]
        if row["Name"] != ours["title"]:
            found.error = f"{direct.server} names it {row['Name']!r}"
        cases.append(found)
    return cases, held, shown
