"""Which libraries of a collection share one collection on a media server."""

lazy from collections.abc import Callable, Iterable
lazy from dataclasses import dataclass

lazy from ...db.models.media_collection import CollectionLibrary, MediaCollection


@dataclass(slots=True, frozen=True)
class ServerCopy:
    """One collection on a server, and the libraries whose members it holds."""

    server_id: int
    libraries: tuple[CollectionLibrary, ...]

    @property
    def lead(self) -> CollectionLibrary:
        """The library a server that needs one creates the collection in."""
        return self.libraries[0]

    @property
    def server_item_id(self) -> str | None:
        return next(
            (part.server_item_id for part in self.libraries if part.server_item_id),
            None,
        )

    @property
    def library_ids(self) -> set[str]:
        return {part.library_id for part in self.libraries}

    @property
    def surplus_ids(self) -> list[str]:
        """Server collections this copy replaces, from libraries saved apart."""
        return [
            identity
            for identity in dict.fromkeys(
                part.server_item_id for part in self.libraries if part.server_item_id
            )
            if identity != self.server_item_id
        ]

    def place(self, server_item_id: str | None, server_path: str | None = None) -> None:
        """Record the server collection that holds these libraries now.

        A collection made just now brings its folder; otherwise the folder a
        part already knows for it goes to every part.
        """
        known = server_path or next(
            (
                part.server_path
                for part in self.libraries
                if server_item_id is not None and part.server_item_id == server_item_id
            ),
            None,
        )
        for part in self.libraries:
            part.server_item_id = server_item_id
            part.server_path = known


#: A server collection, by the database's number of its server and its own ID.
type CopyKey = tuple[int, str]


def copy_keys(parts: Iterable[CollectionLibrary]) -> list[CopyKey]:
    """The server collections these parts are placed in."""
    return [
        (part.server_id, part.server_item_id)
        for part in parts
        if part.server_item_id is not None
    ]


def server_copies(
    row: MediaCollection, *, spans_libraries: Callable[[int], bool]
) -> list[ServerCopy]:
    """The server collections a collection needs, on every server it spans.

    A server that keeps collections outside its libraries needs one for all of
    its libraries; otherwise each library holds its own. *spans_libraries*
    says which kind of server each is, by the database's number of the server.
    """
    by_server: dict[int, list[CollectionLibrary]] = {}
    for part in row.libraries:
        by_server.setdefault(part.server_id, []).append(part)
    return [
        copy
        for server_id, parts in by_server.items()
        for copy in (
            [ServerCopy(server_id, tuple(parts))]
            if spans_libraries(server_id)
            else [ServerCopy(server_id, (part,)) for part in parts]
        )
    ]
