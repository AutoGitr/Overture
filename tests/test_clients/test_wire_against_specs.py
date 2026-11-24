"""Every field Overture reads from a media server is one the server publishes.

The wire types in ``media_servers/wire.py`` are written by hand, so a typo or
a field a server renamed would read as absent and pass every fake. Each field
must appear in the matching schema of the pinned specifications: for the
types Jellyfin and Emby share, in either one's.
"""

lazy import typing
lazy from typing import Any

lazy import pytest

lazy from overture.media_servers import wire
lazy from tests.provider_specs import ProviderSpec

#: Each wire type, and where each server's specification describes it: a
#: schema name, then the property path inside it.
SCHEMAS: dict[str, dict[str, tuple[str, ...]]] = {
    "MediaBrowserItem": {"jellyfin": ("BaseItemDto",), "emby": ("BaseItemDto",)},
    "MediaBrowserImage": {"jellyfin": ("ImageInfo",), "emby": ("ImageInfo",)},
    "MediaBrowserPerson": {
        "jellyfin": ("BaseItemPerson",),
        "emby": ("BaseItemPerson",),
    },
    "MediaBrowserNamed": {"jellyfin": ("NameGuidPair",), "emby": ("NameIdPair",)},
    "MediaBrowserSection": {
        "jellyfin": ("VirtualFolderInfo",),
        "emby": ("VirtualFolderInfo",),
    },
    "RemoteImage": {"jellyfin": ("RemoteImageInfo",), "emby": ("RemoteImageInfo",)},
    "RemoteImages": {
        "jellyfin": ("RemoteImageResult",),
        "emby": ("RemoteImageResult",),
    },
    "MediaBrowserPolicy": {"jellyfin": ("UserPolicy",), "emby": ("UserPolicy",)},
    "MediaBrowserUser": {"jellyfin": ("UserDto",), "emby": ("UserDto",)},
    "PlexMetadata": {"plex": ("Metadata",)},
    "PlexMedia": {"plex": ("Media",)},
    "PlexPart": {"plex": ("Part",)},
    "PlexSection": {"plex": ("Directory",)},
    "PlexGuid": {"plex": ("Tag",)},
    "PlexDirector": {"plex": ("Tag",)},
    "PlexContainer": {"plex": ("mediaContainerWithMetadata", "MediaContainer")},
}
#: Fields Plex sends that its published specification leaves out; scripts/verify
#: reads each from a real server.
UNPUBLISHED = {
    "PlexMetadata": {
        "Children",
        "Label",
        "Location",
        "Producer",
        "childCount",
        "collectionFilterBasedOnUser",
        "collectionMode",
        "collectionSort",
        "content",
        "editionTitle",
        "librarySectionID",
        "smart",
    },
}


def _properties(spec: ProviderSpec, schema: dict[str, Any]) -> set[str]:
    """The properties a schema names, through its references and ``allOf``."""
    resolved = spec.resolve(schema)
    names = set(resolved.get("properties", {}))
    for part in resolved.get("allOf", []):
        names |= _properties(spec, part)
    return names


def _published(provider: str, path: tuple[str, ...]) -> set[str]:
    spec = ProviderSpec(provider)
    schema: dict[str, Any] = {"$ref": f"#/components/schemas/{path[0]}"}
    for name in path[1:]:
        schema = spec.resolve(schema)["properties"][name]
    return _properties(spec, schema)


@pytest.mark.parametrize("name", SCHEMAS)
def test_every_field_read_is_one_a_server_publishes(name: str) -> None:
    read = set(typing.get_type_hints(getattr(wire, name)))
    published = set[str]().union(
        *(_published(provider, path) for provider, path in SCHEMAS[name].items())
    )
    assert read - published == UNPUBLISHED.get(name, set())


def test_every_wire_type_is_checked() -> None:
    shapes = {
        name
        for name, value in vars(wire).items()
        if typing.is_typeddict(value) and name.startswith(("Plex", "MediaBrowser"))
    }
    assert shapes - set(SCHEMAS) <= {
        # Containers and identities whose fields the specs name differently,
        # or which hold only what the mapped types above already check.
        "PlexChildren",
        "PlexLocation",
        "PlexSectionsContainer",
        "PlexArtwork",
        "PlexArtworkContainer",
        "PlexArtworkResponse",
        "PlexIdentityContainer",
        "PlexIdentity",
        "PlexConnection",
        "PlexResource",
        "MediaBrowserIdentity",
        "MediaBrowserResponse",
        "MediaBrowserSections",
        "PlexResponse",
        "PlexSectionsResponse",
    }
