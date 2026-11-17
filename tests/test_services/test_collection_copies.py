"""Which server copy stands for a collection held on several servers."""

lazy from overture.db.models.media_collection import CollectionLibrary, MediaCollection
lazy from overture.domain import MediaType
lazy from overture.services.collections.copies import lead_part


def _held(*copies: tuple[int, str | None]) -> MediaCollection:
    """A collection with a part on each server, in the order they were made."""
    row = MediaCollection(title="Saga")
    row.libraries = [
        CollectionLibrary(
            server_id=server_id,
            collection_id=0,
            library_id=f"{server_id}:movies",
            media_type=MediaType.MOVIE,
            server_item_id=server_item_id,
        )
        for server_id, server_item_id in copies
    ]
    return row


def test_the_copy_on_the_earliest_configured_server_leads() -> None:
    row = _held((2, "jellyfin-saga"), (1, "plex-saga"))

    lead = lead_part(row, [1, 2])

    assert lead is not None
    assert (lead.server_id, lead.server_item_id) == (1, "plex-saga")
    assert lead_part(row, [2, 1]) is row.libraries[0]


def test_copies_on_servers_no_longer_configured_or_not_made_never_lead() -> None:
    row = _held((3, "gone-saga"), (1, None), (2, "jellyfin-saga"))

    lead = lead_part(row, [1, 2])

    assert lead is not None
    assert lead.server_item_id == "jellyfin-saga"
    assert lead_part(row, [1]) is None
