"""The checks of Overture's own collection writes on each media server."""

lazy import asyncio
lazy from collections.abc import Awaitable, Callable
lazy from typing import Any

lazy import httpx2

lazy from overture.config import Settings
lazy from overture.domain import (
    ArtStyle,
    ArtType,
    CollectionMode,
    CollectionOrder,
    MediaType,
)
lazy from overture.media_servers.adapters import CollectionDetails
lazy from overture.media_servers.base import BaseMediaServerProvider
lazy from overture.media_servers.errors import MediaServerError
lazy from overture.media_servers.plex.client import PLEX_CUSTOM_SORT
lazy from overture.media_servers.plex.query import (
    compile_plex_query,
)
lazy from overture.media_servers.registry import ProviderRegistry
lazy from overture.schemas.collections import FilterGroup
lazy from overture.utils.generated_art import render_art

lazy from .common import Case, failure, named
lazy from .media_browser import MediaBrowserServer
lazy from .plex import PLEX_TYPES, PlexServer

#: The title every collection the write check makes starts with.
WRITE_PREFIX = "zz Overture verify"


#: Seconds Jellyfin or Emby must leave a collection unsaved for its own
#: refreshes to count as done, and how many such waits a deletion is given.
SETTLE_SECONDS = 5


SETTLE_ROUNDS = 24


#: Members of the large collection the write check makes: enough that their
#: IDs overflow one request target, so writes must be batched.
LARGE_COLLECTION = 500


def write_provider(
    server: str, url: str, secret: str, *, verify: bool
) -> tuple[ProviderRegistry, BaseMediaServerProvider[Any]]:
    """Overture's own client of one media server, as a sync builds it."""
    values: dict[str, Any] = {
        name: spec.default for name, spec in Settings.model_fields.items()
    }
    values |= {
        "AUTH_MODE": "none",
        "MEDIA_SERVERS": "Verify",
        "MEDIA_SERVER_VERIFY_TYPE": server,
        "MEDIA_SERVER_VERIFY_URL": url,
        "MEDIA_SERVER_VERIFY_API_KEY": secret,
        "MEDIA_SERVER_VERIFY_VERIFY_TLS": verify,
    }
    settings = Settings(**values)
    registry = ProviderRegistry(app_config=settings)
    # One server, numbered as a fresh database numbers its first.
    registry.attach({server.key: 1 for server in settings.MEDIA_SERVERS})
    return registry, registry.get(1)


class WriteCheck:
    """Make, change and delete temporary collections with Overture's own client.

    Each step reads the server itself back, and is reported on its own with
    the request the server refused. Only collections titled ``WRITE_PREFIX``
    are touched, and every one made is deleted at the end, whatever failed.
    """

    def __init__(
        self,
        direct: PlexServer | MediaBrowserServer,
        url: str,
        secret: str,
        *,
        verify: bool,
    ) -> None:
        self.direct = direct
        self.registry, self.provider = write_provider(
            direct.server, url, secret, verify=verify
        )
        self.cases: list[Case] = []
        self.made: list[str] = []
        #: Each regular Plex collection made, by its section and its key in filters.
        self.filed: dict[str, tuple[str, str]] = {}

    def case(self, label: str) -> Case:
        found = Case(self.direct.server, "", "writes", label)
        self.cases.append(found)
        return found

    async def step[T](
        self, label: str, action: Callable[[Case], Awaitable[T]]
    ) -> T | None:
        """Run one step as its own case; ``None`` when the server refused it."""
        case = self.case(label)
        try:
            return await action(case)
        except (MediaServerError, httpx2.HTTPError) as exc:
            case.error = failure(exc)
            return None

    async def held(self, collection_id: str) -> dict[str, Any]:
        """The collection as the server itself holds it."""
        if isinstance(self.direct, PlexServer):
            rows = (
                await self.direct.container(f"/library/metadata/{collection_id}")
            ).get("Metadata", [{}])
            return rows[0]
        return await self.direct.editor_item(collection_id)

    async def art(self, collection_id: str) -> tuple[Any, Any]:
        """What the server names the collection's poster and background by."""
        row = await self.held(collection_id)
        if isinstance(self.direct, PlexServer):
            return row.get("thumb"), row.get("art")
        tags: dict[str, Any] = row.get("ImageTags") or {}
        backdrops: list[Any] = row.get("BackdropImageTags") or []
        return tags.get("Primary"), next(iter(backdrops), None)

    async def run(self) -> list[Case]:
        try:
            # A collection found here outlived the run that deleted it, which
            # the keys and titles that run deleted show.
            if left := await self.sweep():
                self.case("delete what an earlier run left").note = named(left)
            if (found := await self.movies()) is not None:
                library, items = found
                made = await self.step(
                    "create a collection with two members",
                    lambda case: self.create(case, library, items),
                )
                if made is not None:
                    await self.step(
                        "replace a member"
                        + (
                            " and keep a custom order"
                            if isinstance(self.direct, PlexServer)
                            else ""
                        ),
                        lambda case: self.members(case, made, items),
                    )
                    await self.step(
                        "edit the title, sort title, summary and order"
                        + (
                            " and Home visibility"
                            if isinstance(self.direct, PlexServer)
                            else ""
                        ),
                        lambda case: self.details(case, library, made),
                    )
                    await self.step(
                        "upload a poster and a background",
                        lambda case: self.artwork(case, made),
                    )
                    await self.step(
                        "keep the images' names through an edit",
                        lambda case: self.steady(case, library, made),
                    )
                await self.step(
                    f"create a collection of up to {LARGE_COLLECTION} members",
                    lambda case: self.large(case, library, items),
                )
                if isinstance(self.direct, PlexServer):
                    smart = await self.step(
                        "create a smart collection Plex fills itself",
                        lambda case: self.smart(case, library),
                    )
                    if smart is not None:
                        await self.step(
                            "change the smart collection's filter",
                            lambda case: self.refilter(case, library, smart),
                        )
                await self.step("delete the collections it made", self.delete)
        except (MediaServerError, httpx2.HTTPError) as exc:
            self.case("write to the media server").error = failure(exc)
        finally:
            for collection_id in list(self.made):
                try:
                    await self.discard(collection_id)
                except (MediaServerError, httpx2.HTTPError) as exc:
                    self.case(
                        f"delete {collection_id}"
                    ).error = f"left on the server, delete it by hand: {failure(exc)}"
            await self.registry.close()
        return self.cases

    async def movies(self) -> tuple[str, list[str]] | None:
        """A movie library's ID and up to ``LARGE_COLLECTION`` of its movies.

        ``None``, with why, when the library holds fewer than three.

        The server is asked by its own key of the library; Overture's client
        takes Overture's ID of it.
        """
        section = next(
            (
                row
                for row in await self.provider.get_sections()
                if row.media_type is MediaType.MOVIE
            ),
            None,
        )
        if section is None:
            self.case("find a movie library").error = "the server has no movie library"
            return None
        if isinstance(self.direct, PlexServer):
            items = sorted(await self.direct.item_ids(section.key, "movie"))[
                :LARGE_COLLECTION
            ]
        else:
            found = await self.direct.items(
                section.key, "movie", Limit=LARGE_COLLECTION
            )
            items = [str(row["Id"]) for row in found["Items"]]
        if len(items) < 3:
            self.case("find three movies").error = "the library holds fewer than three"
            return None
        return section.library_id, items

    async def create(self, check: Case, library: str, items: list[str]) -> str:
        """Create a regular collection of the first two movies."""
        first, second, *_ = items
        created = await self.provider.create_collection(
            library, f"{WRITE_PREFIX} regular", MediaType.MOVIE, [first, second]
        )
        self.made.append(created.id)
        if isinstance(self.direct, PlexServer):
            row = await self.held(created.id)
            self.filed[created.id] = (library.partition(":")[2], str(row.get("index")))
        held = await self.provider.get_collection_member_ids(created.id)
        check.count, check.held = 2, len(set(held) & {first, second})
        if not held and isinstance(self.direct, MediaBrowserServer):
            check.note = await self.direct.members_to_a_user(created.id)
        return created.id

    async def members(self, check: Case, collection_id: str, items: list[str]) -> None:
        """Replace a member; Plex keeps the order given, the others their own."""
        first, _, third, *_ = items
        await self.provider.set_collection_members(
            collection_id, [third, first], order=CollectionOrder.CUSTOM
        )
        held = await self.provider.get_collection_member_ids(collection_id)
        if isinstance(self.direct, PlexServer):
            if held != [third, first]:
                check.error = f"the server holds {held}, not [{third}, {first}]"
        elif set(held) != {third, first}:
            check.error = (
                f"the server holds {sorted(held)}, not {sorted([third, first])}"
            )

    async def large(self, check: Case, library: str, items: list[str]) -> None:
        """Create a collection of every movie found, then hold them all.

        As a sync does, the membership write that follows the creation adds
        the members its request could not hold.
        """
        created = await self.provider.create_collection(
            library, f"{WRITE_PREFIX} large", MediaType.MOVIE, items
        )
        self.made.append(created.id)
        await self.provider.set_collection_members(
            created.id, items, order=CollectionOrder.CUSTOM
        )
        held = await self.provider.get_collection_member_ids(created.id)
        check.count, check.held = len(items), len(set(held) & set(items))

    async def details(self, check: Case, library: str, collection_id: str) -> None:
        """Edit what a sync sends, and read the server itself back.

        Plex keeps a custom order; Jellyfin and Emby sort a collection by
        one of their display orders.
        """
        plex = isinstance(self.direct, PlexServer)
        order = CollectionOrder.CUSTOM if plex else CollectionOrder.TITLE_ASC
        await self.settled(collection_id)
        before_path = (await self.held(collection_id)).get("Path") if not plex else None
        locks = await self.locks(collection_id)
        wanted = {
            "title": f"{WRITE_PREFIX} edited",
            "sort title": f"{WRITE_PREFIX} sort",
            "summary": "Made by Overture's verify script",
        }
        await self.provider.update_collection_details(
            collection_id,
            library,
            CollectionDetails(
                title=wanted["title"],
                summary=wanted["summary"],
                sort_title=wanted["sort title"],
                mode=CollectionMode.DEFAULT,
                order=order,
                smart=False,
                visible_home=True,
            ),
        )
        row = await self.held(collection_id)
        if plex:
            kept = {
                "title": row.get("title"),
                "sort title": row.get("titleSort"),
                "summary": row.get("summary"),
                "order": str(row.get("collectionSort")),
            }
            wanted["order"] = str(PLEX_CUSTOM_SORT)
        else:
            kept = {
                "title": row.get("Name"),
                "sort title": row.get("ForcedSortName") or row.get("SortName"),
                "summary": row.get("Overview"),
                "order": row.get("DisplayOrder"),
            }
            wanted["order"] = "SortName"
            # Jellyfin answers with the sort name it derives, in lower case.
            kept["sort title"] = str(kept["sort title"] or "").casefold()
            wanted["sort title"] = wanted["sort title"].casefold()
            after_path = row.get("Path")
            if before_path and after_path and after_path != before_path:
                check.note = (
                    f"{self.direct.server} moved the BoxSet from {before_path} "
                    f"to {after_path}, leaving the old folder on disk"
                )
        wrong = [name for name, value in kept.items() if value != wanted[name]]
        if plex and not await self.on_home(library, collection_id):
            wrong.append("Home visibility")
        if plex and (tags := await self.member_tags(collection_id)) != {
            wanted["title"]
        }:
            # Deleting the collection would leave its members tagged, and Plex
            # makes a collection again from the tag.
            wrong.append(f"collection tag of its members ({sorted(tags)!r})")
        # Changing a BoxSet's own lock changes every member's: an edit keeps both.
        if await self.locks(collection_id) != locks:
            wrong.append("lock of the collection or its members")
        if wrong:
            check.error = "the server holds another " + ", ".join(
                f"{name} ({kept.get(name)!r})" if name in kept else name
                for name in wrong
            )
            if isinstance(self.direct, MediaBrowserServer):
                check.note = await self.direct.seen_by_a_user(collection_id)

    async def member_tags(self, collection_id: str) -> set[str]:
        """The verify collection tags the collection's first member carries."""
        first, *_ = await self.provider.get_collection_member_ids(collection_id)
        tags: list[dict[str, Any]] = (await self.held(first)).get("Collection", [])
        return {
            str(tag["tag"]) for tag in tags if str(tag["tag"]).startswith(WRITE_PREFIX)
        }

    async def locks(self, collection_id: str) -> dict[str, object]:
        """Whether Jellyfin or Emby locks the collection and each member, by ID."""
        if not isinstance(self.direct, MediaBrowserServer):
            return {}
        ids = [
            collection_id,
            *await self.provider.get_collection_member_ids(collection_id),
        ]
        return {
            item_id: (await self.direct.editor_item(item_id)).get("LockData")
            for item_id in ids
        }

    async def on_home(self, library: str, collection_id: str) -> bool:
        """Whether Plex promotes the collection's hub to its owner's Home."""
        assert isinstance(self.direct, PlexServer)
        section = library.partition(":")[2]
        hubs: list[dict[str, Any]] = (
            await self.direct.container(
                f"/hubs/sections/{section}/manage", metadataItemId=collection_id
            )
        ).get("Hub", [])
        return any(
            hub.get("identifier") == f"custom.collection.{section}.{collection_id}"
            and bool(hub.get("promotedToOwnHome"))
            for hub in hubs
        )

    async def artwork(self, check: Case, collection_id: str) -> None:
        before = await self.art(collection_id)
        for art_type in (ArtType.POSTER, ArtType.BACKGROUND):
            await self.provider.upload_collection_art(
                collection_id,
                art_type,
                render_art(art_type, ArtStyle.DARK, WRITE_PREFIX),
                "image/png",
            )
        after = await self.art(collection_id)
        unchanged = [
            name
            for name, old, new in zip(
                ("poster", "background"), before, after, strict=True
            )
            if not new or new == old
        ]
        if unchanged:
            check.error = f"the server names the same {' and '.join(unchanged)}"

    async def steady(self, check: Case, library: str, collection_id: str) -> None:
        """Edit the collection as a sync does; the images must keep their names.

        A sync takes an image named otherwise than when Overture sent it for
        one Overture did not send, and forgets it sent one.
        """
        plex = isinstance(self.direct, PlexServer)
        before = await self.art(collection_id)
        await self.provider.update_collection_details(
            collection_id,
            library,
            CollectionDetails(
                title=f"{WRITE_PREFIX} edited",
                summary="Made by Overture's verify script",
                sort_title=f"{WRITE_PREFIX} sort",
                mode=CollectionMode.DEFAULT,
                order=CollectionOrder.CUSTOM if plex else CollectionOrder.TITLE_ASC,
                smart=False,
                visible_home=True,
            ),
        )
        members = await self.provider.get_collection_member_ids(collection_id)
        await self.provider.set_collection_members(
            collection_id, members[::-1], order=CollectionOrder.CUSTOM
        )
        after = await self.art(collection_id)
        if after != before:
            check.error = (
                f"the server names its poster and background {after}, not "
                f"{before}, after an edit"
            )

    def everything_since(self, year: int) -> str:
        """Overture's Plex query for the movies released after *year*."""
        return compile_plex_query(
            FilterGroup.model_validate(
                {
                    "conditions": [
                        {
                            "kind": "field",
                            "field": "year",
                            "operator": "gt",
                            "value": year,
                        }
                    ]
                }
            ),
            media_type=MediaType.MOVIE,
            order=CollectionOrder.TITLE_ASC,
            limit=None,
            choices={},
            labels={},
        )

    async def filled(
        self, check: Case, library: str, collection_id: str, query: str
    ) -> None:
        """Plex holds what its own query selects, and keeps the query."""
        matching, _ = await self.provider.find_matching(
            library, MediaType.MOVIE, query, 0
        )
        held = await self.provider.get_collection_member_ids(collection_id)
        check.count, check.held = matching, len(held)
        kept = await self.provider.smart_collection_filter(collection_id)
        if kept != query:
            check.note = f"Plex keeps the filter as {kept}"

    async def smart(self, check: Case, library: str) -> str:
        """Create a smart collection from Overture's query; Plex fills it."""
        query = self.everything_since(0)
        created = await self.provider.create_smart_collection(
            library, f"{WRITE_PREFIX} smart", MediaType.MOVIE, query
        )
        self.made.append(created.id)
        await self.filled(check, library, created.id, query)
        return created.id

    async def refilter(self, check: Case, library: str, collection_id: str) -> None:
        """Change a smart collection's query, as a sync of an edited rule does."""
        query = self.everything_since(2000)
        await self.provider.update_smart_collection_filter(
            collection_id, library, MediaType.MOVIE, query
        )
        await self.filled(check, library, collection_id, query)

    async def settled(self, collection_id: str) -> None:
        """Wait until Jellyfin or Emby has stopped saving the collection.

        Each membership write queues a refresh of the BoxSet, which saves its
        folder and its row again. One still running when the BoxSet is
        deleted puts them back: a folder the server no longer lists, or on
        Jellyfin a collection it lists again.

        Raises:
            MediaServerError: The server kept saving it.
        """
        if not isinstance(self.direct, MediaBrowserServer):
            return
        saved: object = None
        for _ in range(SETTLE_ROUNDS):
            # Each save changes the Etag; Emby names no DateLastSaved.
            found = await self.direct.get("/Items", Ids=collection_id, Fields="Etag")
            rows: list[dict[str, Any]] = found["Items"]
            now = rows[0].get("Etag") if rows else None
            if now is None or now == saved:
                return
            saved = now
            await asyncio.sleep(SETTLE_SECONDS)
        raise MediaServerError(
            f"{self.direct.server} kept saving collection {collection_id} for "
            f"{SETTLE_SECONDS * SETTLE_ROUNDS} seconds"
        )

    async def discard(self, collection_id: str) -> None:
        """Delete a collection a step made, once its server is done with it."""
        await self.settled(collection_id)
        await self.provider.delete_collection(collection_id)
        if collection_id in self.made:
            self.made.remove(collection_id)

    async def sweep(self) -> list[str]:
        """Delete every collection a run made, recorded or not; name each one.

        A server can make a collection and then fail the request, so the one
        it made is found by its title.
        """
        swept: list[str] = []
        for row in await self.provider.list_collections():
            if row.title.startswith(WRITE_PREFIX):
                swept.append(f"{row.title!r} ({row.id}, {len(row.member_ids)} members)")
                await self.discard(row.id)
        return swept

    async def delete(self, check: Case) -> None:
        """Delete what the steps made; nothing titled as theirs may be left.

        A collection found after them is one the server made, or made again,
        itself, and is deleted too.
        """
        deleted: list[str] = []
        for collection_id in list(self.made):
            row = await self.held(collection_id)
            title = row.get("title") or row.get("Name")
            deleted.append(f"{title!r} ({collection_id})")
            await self.discard(collection_id)
        check.note = f"deleted {named(deleted)}"
        # A refresh the server ran on its own would bring a collection back
        # within this time.
        await asyncio.sleep(SETTLE_SECONDS)
        problems: list[str] = []
        if made := await self.sweep():
            problems.append(f"the server made {named(made)} itself")
        if isinstance(self.direct, PlexServer):
            for section, key in self.filed.values():
                page = await self.direct.container(
                    f"/library/sections/{section}/all",
                    type=PLEX_TYPES["movie"],
                    collection=key,
                    **{"X-Plex-Container-Start": 0, "X-Plex-Container-Size": 0},
                )
                if filed := int(page.get("totalSize", page.get("size", 0))):
                    problems.append(
                        f"Plex still files {filed} titles under the deleted "
                        f"collection's filter key {key}"
                    )
        left = [
            row.title
            for row in await self.provider.list_collections()
            if row.title.startswith(WRITE_PREFIX)
        ]
        if left:
            problems.append(f"the server still lists {named(left)}")
        check.error = "; ".join(problems)
