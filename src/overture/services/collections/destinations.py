"""Where each of a collection's assets has to be: one rule for every writer."""

lazy from ...db.ledger import Destination, place
lazy from ...db.models.media_collection import MediaCollection
lazy from ...domain import ITEM_ASSETS, DeliveryChannel, ServerAsset
lazy from ...media_servers.adapters import FolderThemes, UploadThemes
lazy from ...media_servers.registry import ProviderRegistry


def collection_destinations(
    row: MediaCollection, kind: ServerAsset, provider_registry: ProviderRegistry
) -> list[Destination]:
    """Return the server copies a collection's *kind* is delivered to.

    Art is uploaded to every copy. A theme is uploaded to each Plex copy, and
    written once per Jellyfin server to the folder its copies share; a server
    that keeps no collection themes, or has no folder set for them, takes
    none. A copy on a server no longer configured is not delivered to.
    """
    destinations: list[Destination] = []
    seen_folders: set[int] = set()
    for part in row.copies:
        if not provider_registry.configured_server_id(part.server_id):
            continue
        copy = (part.server_id, part.server_item_id)
        if kind is not ServerAsset.THEME:
            destinations.append(Destination(*copy, channel=DeliveryChannel.UPLOAD))
            continue
        provider = provider_registry.get(part.server_id)
        match provider.collections:
            case UploadThemes():
                destinations.append(Destination(*copy, channel=DeliveryChannel.UPLOAD))
            case FolderThemes() if (
                provider.server.collections_path is not None
                and part.server_id not in seen_folders
            ):
                seen_folders.add(part.server_id)
                destinations.append(Destination(*copy, channel=DeliveryChannel.FILE))
            case _:
                pass
    return destinations


def place_collection(row: MediaCollection, provider_registry: ProviderRegistry) -> None:
    """Make the collection's server copies the places each of its assets has to be."""
    for kind in ITEM_ASSETS:
        place(row, kind, collection_destinations(row, kind, provider_registry))
