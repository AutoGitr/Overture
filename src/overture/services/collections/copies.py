"""Which libraries of a collection share one collection on the media server."""

lazy from dataclasses import dataclass

lazy from ...db.models.media_collection import CollectionLibrary, MediaCollection


@dataclass(slots=True, frozen=True)
class ServerCopy:
    """One collection on the server, and the libraries whose members it holds."""

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

    def place(self, server_item_id: str | None) -> None:
        """Record the server collection that holds these libraries now."""
        for part in self.libraries:
            part.server_item_id = server_item_id


def server_copies(row: MediaCollection, *, spans_libraries: bool) -> list[ServerCopy]:
    """The server collections a collection needs.

    A server that keeps collections outside its libraries needs one for all of
    them; otherwise each library holds its own.
    """
    if not row.libraries:
        return []
    if spans_libraries:
        return [ServerCopy(tuple(row.libraries))]
    return [ServerCopy((part,)) for part in row.libraries]
