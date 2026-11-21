"""Call signatures for the model factory fixtures in :mod:`conftest`.

A fixture is injected by name, so a test that takes ``media_item_factory``
tells the type checker nothing about what it received. These protocols are
what the fixtures return, and annotating the parameter with one gives the
test the real signature - including which keyword arguments a factory takes
and which model it builds.
"""

lazy from typing import Any, Protocol

lazy from sqlmodel import SQLModel, inspect

lazy from overture.db.ledger import (
    LOCAL,
    ContentFacts,
    Destination,
    FileFacts,
    confirm_delivery,
    file_facts,
    find_asset,
    local_file,
    read_asset,
    record_content,
    record_file,
    select_art,
    select_theme,
    select_upload,
    selection,
)
lazy from overture.db.models.asset import Asset
lazy from overture.db.models.catalog import CatalogItem
lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_collection import MediaCollection
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.models.settings import AppSettings
lazy from overture.domain import (
    ArtType,
    CollectionPosterStyle,
    ServerAsset,
    ThemeIdSource,
)
lazy from overture.utils.art_urls import PublicArtUrl


def build[Model: SQLModel](model: type[Model], **fields: Any) -> Model:
    """Construct a table row, refusing fields it does not have.

    A table model drops unknown keyword arguments, so a test naming a field
    the model lost would otherwise run with that state silently missing.
    """
    unknown = fields.keys() - inspect(model).attrs.keys()
    if unknown:
        raise TypeError(f"{model.__name__} has no fields {sorted(unknown)}")
    return model(**fields)


#: Assets declared by a factory caller, keyed by kind, as :func:`seed_asset` takes.
type ArtSpec = dict[str, dict[str, Any]]


class MediaItemFactory(Protocol):
    """Build a :class:`MediaItem`, optionally with artwork slots filled in."""

    def __call__(self, art: ArtSpec | None = None, **overrides: Any) -> MediaItem: ...


class SeasonFactory(Protocol):
    """Build a :class:`Season`, optionally with artwork slots filled in."""

    def __call__(self, art: ArtSpec | None = None, **overrides: Any) -> Season: ...


class AppSettingsFactory(Protocol):
    """Build an :class:`AppSettings` row."""

    def __call__(self, **overrides: Any) -> AppSettings: ...


class DownloadJobFactory(Protocol):
    """Build a :class:`DownloadJob` row."""

    def __call__(self, **overrides: Any) -> DownloadJob: ...


class CatalogItemFactory(Protocol):
    """Build a :class:`CatalogItem` row."""

    def __call__(self, **overrides: Any) -> CatalogItem: ...


def seed_asset(
    owner: MediaItem | Season | MediaCollection,
    kind: ArtType | ServerAsset,
    *,
    url: str | None = None,
    upload_hash: str | None = None,
    poster_style: CollectionPosterStyle | None = None,
    file_hash: str | None = None,
    content_hash: str | None = None,
    fingerprint: str | None = None,
    width: int | None = None,
    height: int | None = None,
    file_mtime_ns: int | None = 1,
    file_size: int | None = 1,
) -> Asset:
    """Give *owner* an asset as a test's starting state, through the ledger.

    *url* or *upload_hash* is the selection, unless the asset has one. For a
    title or season,
    *file_hash* is the file found in its folder, which is the selection's
    content unless *content_hash* names other bytes. For a collection,
    *file_hash* is the content Overture uploaded, shown by every copy placed.
    """
    kind = kind.server_asset if isinstance(kind, ArtType) else kind
    if url is not None:
        select_art(owner, kind, PublicArtUrl(url), poster_style=poster_style)
    if upload_hash is not None:
        select_upload(owner, kind, upload_hash)
    selected = selection(read_asset(owner, kind)) is not None
    facts = (
        FileFacts(file_hash, file_mtime_ns, file_size, fingerprint, width, height)
        if file_hash is not None
        else None
    )
    if isinstance(owner, MediaCollection):
        if facts is not None:
            record_content(owner, kind, facts.content())
            asset = find_asset(owner, kind)
            for row in list(asset.deliveries if asset else ()):
                confirm_delivery(
                    owner,
                    kind,
                    Destination(row.server_id, row.server_item_id, row.channel),
                    ref=None,
                )
    else:
        if facts is not None:
            record_file(owner, kind, facts)
        content = content_hash or (file_hash if selected else None)
        if content is not None:
            record_content(
                owner,
                kind,
                facts.content()
                if facts is not None and content == file_hash
                else ContentFacts(content),
            )
    return read_asset(owner, kind)


def theme_of(owner: MediaItem | MediaCollection) -> Asset:
    """Return the owner's theme asset, blank when it has none."""
    return read_asset(owner, ServerAsset.THEME)


def theme_file(owner: MediaItem | MediaCollection) -> FileFacts | None:
    """Return the theme file found for the owner: its folder's, or a server's."""
    return next(
        (
            facts
            for row in theme_of(owner).deliveries
            if (facts := file_facts(row)) is not None
        ),
        None,
    )


def theme_file_hash(owner: MediaItem | MediaCollection) -> str | None:
    """Return the hash of the theme file found for the owner, if any."""
    facts = theme_file(owner)
    return facts.file_hash if facts else None


def server_ref(owner: MediaCollection, kind: ArtType | ServerAsset) -> str | None:
    """Return what the collection's first copy names its current image or theme by."""
    kind = kind.server_asset if isinstance(kind, ArtType) else kind
    return next(
        (
            row.observed_ref
            for row in read_asset(owner, kind).deliveries
            if row.server_id
        ),
        None,
    )


def local_hash(owner: MediaItem | Season, kind: ArtType | ServerAsset) -> str | None:
    """Return the hash of the owner's file of *kind* in its folder, if any."""
    kind = kind.server_asset if isinstance(kind, ArtType) else kind
    facts = local_file(read_asset(owner, kind))
    return facts.file_hash if facts else None


def seed_theme[Owner: (MediaItem, MediaCollection)](
    owner: Owner,
    youtube_id: str | None = None,
    *,
    source: ThemeIdSource = ThemeIdSource.DOWNLOAD,
    title: str | None = None,
    duration: int | None = None,
    file_hash: str | None = None,
    content_hash: str | None = None,
    file_mtime_ns: int | None = 1,
    file_size: int | None = 1,
    file_duration: int | None = None,
    destination: Destination = LOCAL,
    uploaded_as: str | None = None,
) -> Owner:
    """Give *owner* a theme as a test's starting state, through the ledger; return it.

    *file_hash* is the theme file at *destination* (a title's folder unless
    named), which is the selection's content unless *content_hash* names
    other bytes. *uploaded_as* is the server's name for an uploaded theme,
    delivered to *destination*.
    """
    if youtube_id is not None:
        select_theme(owner, youtube_id, source=source, title=title, duration=duration)
    if file_hash is not None:
        record_file(
            owner,
            ServerAsset.THEME,
            FileFacts(file_hash, file_mtime_ns, file_size, duration=file_duration),
            destination=destination,
        )
    content = content_hash or (file_hash if youtube_id is not None else None)
    if uploaded_as is not None:
        content = content or f"youtube:{youtube_id}"
    if content is not None:
        record_content(
            owner,
            ServerAsset.THEME,
            ContentFacts(
                content, duration=file_duration if content == file_hash else None
            ),
        )
    if uploaded_as is not None:
        confirm_delivery(owner, ServerAsset.THEME, destination, ref=uploaded_as)
    return owner


def file_hash_of(asset: Asset) -> str | None:
    """Return the hash of the asset's file in its owner's folder, if any."""
    facts = local_file(asset)
    return facts.file_hash if facts else None


def file_of(asset: Asset) -> FileFacts:
    """Return the facts of the asset's file in its owner's folder."""
    facts = local_file(asset)
    assert facts is not None, "the asset records no local file"
    return facts
