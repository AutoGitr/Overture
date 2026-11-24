"""Plex, read directly, as the checks compare Overture with it."""

lazy from typing import Any
lazy from urllib.parse import unquote

lazy import httpx2

lazy from overture.domain import (
    CollectionOrder,
    MediaType,
)
lazy from overture.media_servers.plex.query import (
    compile_plex_query,
    plex_field_keys,
    plex_operators,
    plex_sort,
)
lazy from overture.schemas.collections import FilterGroup
lazy from overture.utils.collection_fields import FIELDS, PlexFieldType
lazy from scripts.json_values import is_array

lazy from .common import (
    ApiError,
    Case,
    Server,
    ServerArt,
    collection_copy,
    collection_inventory,
    holds_server_theme,
    inventory,
    item_copy_id,
    named,
)
lazy from .library import Library

#: Plex's page size when listing a section's items.
PLEX_PAGE = 500


#: Plex filters and sorts Overture leaves out by choice, and why; an episode's
#: form of a key without its own entry shares the key's.
_MAINTENANCE = "it tells the library's upkeep, not what a collection holds"


_EPISODE_OF_SHOW = "a show collection tests the show's own value"


PLEX_KNOWN_GAPS: dict[str, str] = {
    "duplicate": _MAINTENANCE,
    "trash": _MAINTENANCE,
    "unmatched": _MAINTENANCE,
    "location": (
        "Plex offers only the library's root folders, and Folder tests any path"
    ),
    "episode.title": _EPISODE_OF_SHOW,
    "episode.year": _EPISODE_OF_SHOW,
    "episode.originallyAvailableAt": _EPISODE_OF_SHOW,
    "episode.userRating": _EPISODE_OF_SHOW,
    "episode.viewCount": _EPISODE_OF_SHOW,
    "episode.collection": _EPISODE_OF_SHOW,
    "episode.unwatched": "Unplayed tests a show's unplayed episodes",
    "mediaHeight": "a collection is rarely wanted in order of resolution",
}


#: The scopes Plex lists a section's filters, fields and sorts under.
PLEX_SCOPES = frozenset({"movie", "show", "season", "episode"})


PLEX_TYPES = {"movie": 1, "show": 2}


PLEX_EPISODE = 4


#: The Plex field types Overture writes; Plex types its media fields by name.
PLEX_FIELD_TYPES: frozenset[PlexFieldType] = frozenset(
    {"string", "tag", "integer", "float", "date", "boolean"}
)


#: Values per field Plex is asked whether any title holds.
VALUE_PROBES = 20


#: Characters Plex may refuse in a text value, each probed on its own.
PLEX_TEXT_PROBES = ("'", "!", "&", '"', "%")


#: Where a title's metadata holds a filter's tags, when not under its name.
PLEX_TAGS = {"actor": "Role", "contentRating": "contentRating"}


class PlexServer(Server):
    """Plex, asked directly with its token."""

    server = "plex"

    def __init__(self, base_url: str, token: str, *, verify: bool = True) -> None:
        super().__init__(base_url, {"X-Plex-Token": token}, verify=verify)
        self._directories: dict[tuple[str, int | None], dict[str, str]] = {}

    async def container(self, path: str, **params: Any) -> dict[str, Any]:
        return (await self.get(path, **params))["MediaContainer"]

    async def libraries(self, media_type: str) -> dict[str, str]:
        sections = (await self.container("/library/sections")).get("Directory", [])
        return {
            str(row["key"]): row["title"]
            for row in sections
            if row["type"] == media_type
        }

    async def item_ids(self, library_id: str, media_type: str) -> set[str]:
        ids: set[str] = set()
        while True:
            page = await self.container(
                f"/library/sections/{library_id}/all",
                type=PLEX_TYPES[media_type],
                **{
                    "X-Plex-Container-Start": len(ids),
                    "X-Plex-Container-Size": PLEX_PAGE,
                },
            )
            rows = page.get("Metadata", [])
            ids.update(str(row["ratingKey"]) for row in rows)
            if len(rows) < PLEX_PAGE:
                return ids

    async def collections(self, library_id: str) -> dict[str, dict[str, Any]]:
        rows = (
            await self.container(
                f"/library/sections/{library_id}/collections", includeFields="theme"
            )
        ).get("Metadata", [])
        return {str(row["ratingKey"]): row for row in rows}

    async def directory(
        self, path: str, item_type: int | None = None
    ) -> dict[str, str]:
        """The keys Plex lists a filter's values under, by folded name, fetched once."""
        key = (path, item_type)
        if key not in self._directories:
            params = {} if item_type is None else {"type": item_type}
            self._directories[key] = {
                str(row["title"]).casefold(): unquote(str(row["key"]))
                for row in (await self.container(path, **params)).get("Directory", [])
                if row.get("title") and row.get("key")
            }
        return self._directories[key]

    async def unheld(
        self, library: Library, filter_name: str, values: dict[str, str]
    ) -> set[str]:
        """Which of *values* no title of the library holds, asked of Plex.

        Plex keeps listing a value after the last title holding it loses it,
        and lists labels only collections hold.
        """
        found: set[str] = set()
        for name, key in list(values.items())[:VALUE_PROBES]:
            page = await self.container(
                f"/library/sections/{library.key}/all",
                type=PLEX_TYPES[library.media_type],
                **{
                    filter_name: key,
                    "X-Plex-Container-Start": 0,
                    "X-Plex-Container-Size": 0,
                },
            )
            if not int(page.get("totalSize", page.get("size", 0))):
                found.add(name)
        return found

    async def count(self, library: Library, condition: dict[str, Any]) -> int | None:
        """How many titles Plex selects by a condition, or ``None`` if it refuses it."""
        query = compile_plex_query(
            FilterGroup.model_validate({"conditions": [condition]}),
            media_type=MediaType(library.media_type),
            order=CollectionOrder.TITLE_ASC,
            limit=None,
            choices={},
            labels={},
        )
        try:
            page = await self.container(
                f"/library/sections/{library.key}/all?"
                f"type={PLEX_TYPES[library.media_type]}"
                f"&X-Plex-Container-Start=0&X-Plex-Container-Size=0&{query}"
            )
        except httpx2.HTTPStatusError:
            return None
        return int(page.get("totalSize", page.get("size", 0)))

    async def refused(self, library: Library, condition: dict[str, Any]) -> str:
        """Which character of a text value Plex refuses, asked of Plex directly."""
        value = str(condition["value"])
        culprits = [
            char
            for char in PLEX_TEXT_PROBES
            if char in value
            and await self.count(
                library, {**condition, "value": value.replace(char, "")}
            )
            is not None
        ]
        if not culprits:
            return "Plex refuses the value whichever character is left out"
        note = "Plex answers once {} is left out of the value".format(
            " or ".join(repr(char) for char in culprits)
        )
        if "'" in culprits:
            doubled = await self.count(
                library, {**condition, "value": value.replace("'", "''")}
            )
            note += "; with ' doubled " + (
                "it refuses it too" if doubled is None else f"it selects {doubled}"
            )
        return note

    async def check_library(self, library: Library) -> None:
        """Compare what Overture lists and offers with what Plex holds and offers."""
        await self.check_inventory(library)
        meta = (
            await self.container(
                f"/library/sections/{library.key}/all",
                type=PLEX_TYPES[library.media_type],
                includeMeta=1,
                **{"X-Plex-Container-Start": 0, "X-Plex-Container-Size": 0},
            )
        ).get("Meta", {})
        self.check_offers(library, meta)
        await self.check_values(library, meta)

    async def check_inventory(self, library: Library) -> None:
        held = await self.item_ids(library.key, library.media_type)
        inventory(
            library.case("inventory", "items"),
            {item_copy_id(item, library.id) for item in library.items},
            held,
            noun="items",
        )
        listed = await self.collections(library.key)
        mine = {
            str(copy["server_item_id"]): row
            for row in library.collections
            if (copy := collection_copy(row, library.id))
        }
        collection_inventory(
            library.case("inventory", "collections"),
            library.listing,
            library.media_type,
            mine,
            {
                key: (row["title"], int(row.get("childCount", 0)), row.get("subtype"))
                for key, row in listed.items()
            },
        )
        for key, row in listed.items():
            if (ours := mine.get(key)) is None:
                continue
            library.held[key] = int(row.get("childCount", 0))
            thumb = str(row.get("thumb") or "")
            # Plex composes a poster from the members of a collection without one.
            library.shown[key] = ServerArt(
                poster=bool(thumb) and "/composite/" not in thumb,
                background=bool(row.get("art")),
                theme=bool(row.get("theme")),
            )
            case = library.case("inventory", f"{row['title']} members")
            case.held = library.held[key]
            # Overture counts the members on every server holding a copy.
            if len(ours["copies"]) == 1:
                case.count = ours["child_count"]
            else:
                case.note = (
                    f"Overture counts its members on {len(ours['copies'])} servers"
                )
            problems: list[str] = []
            if bool(int(row.get("smart", 0))) != (ours["kind"] == "smart"):
                problems.append(
                    f"Plex says smart={row.get('smart')}, Overture {ours['kind']}"
                )
            if row["title"] != ours["title"]:
                problems.append(f"Plex names it {row['title']!r}")
            ours_copy = collection_copy(ours, library.id)
            has_theme = holds_server_theme(
                ours, ours_copy["server_id"] if ours_copy else None
            )
            if bool(row.get("theme")) != has_theme:
                problems.append(
                    "Plex holds a theme Overture does not know"
                    if row.get("theme")
                    else "Overture lists a theme Plex does not hold"
                )
            case.error = "; ".join(problems)

    def check_offers(self, library: Library, meta: dict[str, Any]) -> None:
        """Each Plex filter, field, sort and operator must be one Overture uses."""
        # Plex types media fields by name (``resolution``); Overture writes
        # each as one of its own types, found through the fields of the type.
        written_as: dict[str, set[PlexFieldType]] = {
            kind: {kind} for kind in PLEX_FIELD_TYPES
        }
        for kind in meta.get("Type", []):
            if kind.get("type") in PLEX_SCOPES:
                self.check_scope(library, kind, written_as)
        for field_type in meta.get("FieldType", []):
            kind = str(field_type.get("type"))
            ours = written_as.get(kind)
            if not ours:
                library.case(
                    "plex operator", kind
                ).error = "Overture has no Plex field of this type"
                continue
            written = frozenset[str]().union(*map(plex_operators, ours))
            for operator in field_type.get("Operator", []):
                if operator["key"] not in written:
                    library.case(
                        "plex operator",
                        f"{kind} {operator['key']} ({operator['title']})",
                    ).error = "Overture never writes this Plex operator"

    @staticmethod
    def check_scope(
        library: Library,
        kind: dict[str, Any],
        written_as: dict[str, set[PlexFieldType]],
    ) -> None:
        """Check the filters, fields and sorts Plex lists for one item type.

        Adds the Overture type each Plex field type is written as to
        *written_as*.
        """
        known = plex_field_keys(MediaType(library.media_type))
        prefix = "" if kind["type"] == library.media_type else f"{kind['type']}."

        def scoped(key: str) -> str:
            return (key if "." in key else f"{prefix}{key}").removeprefix(
                f"{library.media_type}."
            )

        for entry in kind.get("Field", []):
            field_name = known.get(scoped(entry["key"]))
            plex = FIELDS[field_name].plex if field_name else None
            if plex is not None and entry.get("type"):
                written_as.setdefault(entry["type"], set()).add(plex.type)
        # Plex lists some keys both bare and with their scope (``show.title``).
        offered = {
            *(scoped(entry["filter"]) for entry in kind.get("Filter", [])),
            *(scoped(entry["key"]) for entry in kind.get("Field", [])),
        }
        for key in sorted(offered - set(known)):
            gap(library.case("plex field", key), key, "test this Plex field")
        if prefix:
            return
        sorts = _plex_sorts()
        for entry in kind.get("Sort", []):
            if entry["key"] not in sorts:
                gap(
                    library.case("plex sort", entry["key"]),
                    entry["key"],
                    "order by this Plex sort",
                )

    async def check_values(self, library: Library, meta: dict[str, Any]) -> None:
        """Each value a title holds by Plex's list must be one Overture offers."""
        keys = plex_field_keys(MediaType(library.media_type))
        types: list[dict[str, Any]] = meta.get("Type", [])
        own = next(
            (kind for kind in types if kind.get("type") == library.media_type), None
        )
        filters: list[dict[str, Any]] = own.get("Filter", []) if own else []
        for entry in filters:
            field_name = keys.get(entry["filter"])
            spec = library.fields.get(str(field_name)) if field_name else None
            plex = FIELDS[field_name].plex if field_name else None
            if spec is None or plex is None or spec["kind"] != "tag":
                continue
            if not entry.get("key"):
                continue
            listed = await self.directory(entry["key"])
            held = await self.criteria_values(
                library, spec["field"], listed, keyed=plex.keyed
            )
            names = {key: name for name, key in listed.items()}
            try:
                values = await library.values(spec["field"])
            except ApiError:
                continue
            offered = library.offered_values(spec["field"])
            labels = {str(row["value"]).casefold(): row["label"] for row in values}
            case = library.case("plex values", spec["label"])
            notes = [f"Overture offers {len(offered)}, Plex lists {len(held)}"]
            missing = {name: key for name, key in held.items() if name not in offered}
            if unheld := await self.unheld(library, entry["filter"], missing):
                notes.append(
                    f"no title holds {named([names[held[value]] for value in unheld])}"
                )
            real = set(missing) - unheld
            # Plex lists the titles without a rating under "None".
            if spec["field"] == "content_rating" and "none" in real:
                real.discard("none")
                notes.append("Plex lists the titles without a rating as None")
            if real:
                problem = (
                    "Overture does not offer "
                    f"{named([names[held[value]] for value in real])}"
                )
                if FIELDS[spec["field"]].tmdb:
                    notes.append(f"{problem}: Overture offers TMDB's, Plex its own")
                else:
                    case.error = problem
            if unlisted := offered - set(held):
                notes.append(
                    "Plex's list leaves out "
                    f"{named([labels[value] for value in unlisted])}; Overture "
                    "finds them through the titles holding them"
                )
            case.note = "; ".join(notes)

    async def criteria_values(
        self, library: Library, field_name: str, listed: dict[str, str], *, keyed: bool
    ) -> dict[str, str]:
        """Plex's listed values, by name, as the values criteria hold, folded.

        A keyed field's are Plex's keys (``1080``), not its names. A
        collection's is Overture's ID of it: Plex lists a collection by its
        ``index``, under the title its tag holds, and one Overture does not
        list is left out, as the editor leaves it out.
        """
        if field_name != "collection":
            return {key.casefold(): key for key in listed.values()} if keyed else listed
        ours = {
            str(copy["server_item_id"]): str(row["id"])
            for row in library.collections
            if (copy := collection_copy(row, library.id))
        }
        by_index = {
            str(row["index"]): key
            for key, row in (await self.collections(library.key)).items()
            if row.get("index") is not None
        }
        return {
            ours[rating_key]: index
            for index in listed.values()
            if (rating_key := by_index.get(index, "")) in ours
        }

    async def explain(
        self,
        library: Library,
        entry: dict[str, Any],
        value: Any,
        difference: tuple[str, bool],
    ) -> str:
        """Name the title the evaluators disagree on, with what Plex holds for it."""
        title, plex_holds = difference
        side = "only Plex selects" if plex_holds else "only Overture selects"
        plex = FIELDS[entry["field"]].plex
        if plex is None:
            return f"{side} {title}"
        key = plex.key_for(MediaType(library.media_type))
        found = f"{side} {title}"
        item = next((row for row in library.items if row["title"] == title), None)
        if item is not None and (rating_key := item_copy_id(item, library.id)):
            rows = (await self.container(f"/library/metadata/{rating_key}")).get(
                "Metadata", [{}]
            )
            tag = PLEX_TAGS.get(key, key.capitalize())
            raw = rows[0].get(tag, rows[0].get(key)) if rows else None
            shown = (
                ", ".join(str(tag.get("tag")) for tag in raw) if is_array(raw) else raw
            )
            found += f"; Plex holds {key}={shown!r}"
        if plex.type == "tag" and not plex.keyed:
            episode = key.startswith("episode.")
            listed = await self.directory(
                f"/library/sections/{library.key}/{key.removeprefix('episode.')}",
                PLEX_EPISODE if episode else PLEX_TYPES[library.media_type],
            )
            if str(value).casefold() not in listed:
                found += f"; Plex's {key} list does not name {value!r}"
        return found


def gap(case: Case, key: str, what: str) -> None:
    """Note a Plex feature Overture leaves out by choice; report any other."""
    reason = PLEX_KNOWN_GAPS.get(key) or PLEX_KNOWN_GAPS.get(
        key.removeprefix("episode.")
    )
    if reason:
        case.note = f"left out by choice: {reason}"
    else:
        case.error = f"Overture cannot {what}"


def _plex_sorts() -> set[str]:
    """The Plex sort keys Overture's orders use."""
    keys: set[str] = set()
    for order in CollectionOrder:
        try:
            keys.add(plex_sort(order).removesuffix(":desc"))
        except ValueError:
            continue
    return keys
