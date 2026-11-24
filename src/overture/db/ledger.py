"""The only writer of assets: what Overture chose, holds and placed where.

Every change to an :class:`~overture.db.models.asset.Asset` or its deliveries
is one of the named transitions here, and each one ends by settling the
asset's stored status from its rows. No other module assigns their columns
(``tests/test_architecture/test_asset_ownership.py`` holds that), so a
status can never disagree with what the rows say, and items, seasons,
collections and themes all follow the same rule:

* **complete**: the asset is not needed, or it has a selection and every
  required delivery holds its content (no required delivery: the selection
  alone completes it).
* **partial**: something is recorded: a selection, content, or anything
  seen at a destination, Overture's or not.
* **missing**: nothing is.

The functions work on rows loaded in a session the caller owns, and write
nothing until it flushes.
"""

lazy from collections.abc import Collection, Iterable
lazy from dataclasses import dataclass
lazy from datetime import datetime
lazy from enum import StrEnum
lazy from functools import cache

lazy from sqlalchemy.orm import Session as OrmSession
lazy from sqlmodel import inspect

lazy from ..domain import (
    ArtGeneration,
    ArtSource,
    AssetStatus,
    CollectionPosterStyle,
    DeliveryChannel,
    MediaType,
    ServerAsset,
    ThemeBulkSource,
    ThemeIdSource,
)
lazy from ..utils.art_urls import PublicArtUrl, selected_art_source
lazy from .models.asset import Asset, AssetDelivery
lazy from .models.media_collection import MediaCollection
lazy from .models.media_item import MediaItem
lazy from .models.season import Season

type Owner = MediaItem | Season | MediaCollection


@dataclass(frozen=True, slots=True)
class ContentFacts:
    """The bytes a selection is: their hash and what they show or play."""

    content_hash: str
    fingerprint: str | None = None
    width: int | None = None
    height: int | None = None
    #: Seconds of a theme's audio.
    duration: int | None = None


@dataclass(frozen=True, slots=True)
class FileFacts:
    """What one inspection of a file at a destination established.

    The stat revision is ``None`` when the file's metadata could not be read,
    so the next inspection reads it again even if it did not change.
    """

    file_hash: str
    file_mtime_ns: int | None
    file_size: int | None
    fingerprint: str | None = None
    width: int | None = None
    height: int | None = None
    duration: int | None = None

    def content(self) -> ContentFacts:
        """Return the file's bytes as the content of a selection."""
        return ContentFacts(
            self.file_hash, self.fingerprint, self.width, self.height, self.duration
        )


@dataclass(frozen=True, slots=True)
class Destination:
    """One place an asset's content has to be.

    Without a server it is the item's local folder; with one, that server's
    copy of a collection.
    """

    server_id: int | None = None
    server_item_id: str | None = None
    channel: DeliveryChannel = DeliveryChannel.FILE
    #: Whether the asset is complete only once the content is here.
    required: bool = True

    @property
    def key(self) -> tuple[int | None, str | None]:
        return self.server_id, self.server_item_id


#: The item's or season's local folder, which every file asset is written to.
LOCAL = Destination()


class Evidence(StrEnum):
    """What a check of one destination found against the asset's content."""

    #: The destination holds the content.
    SAME = "same"
    #: It holds something else, or nothing.
    DIFFERENT = "different"
    #: It could not be read: no evidence either way, so nothing changes.
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Selection:
    """What an asset selects: an artwork link, a kept image, or a video."""

    url: PublicArtUrl | None = None
    upload_hash: str | None = None
    youtube_id: str | None = None


# --- Reading -----------------------------------------------------------------


def find_asset(owner: Owner, kind: ServerAsset) -> Asset | None:
    """Return the owner's asset of *kind*, or ``None`` when it has none."""
    for asset in owner.assets:
        if asset.kind == kind:
            return asset
    return None


@cache
def _blank(kind: ServerAsset) -> Asset:
    """An asset recording nothing, which must never be written to."""
    return Asset(kind=kind)


def read_asset(owner: Owner, kind: ServerAsset) -> Asset:
    """Return the owner's asset of *kind*, or a shared blank one to read from."""
    return find_asset(owner, kind) or _blank(kind)


def selection(asset: Asset) -> Selection | None:
    """Return what the asset selects, or ``None`` when it selects nothing."""
    if asset.url is None and asset.upload_hash is None and asset.youtube_id is None:
        return None
    return Selection(asset.url, asset.upload_hash, asset.youtube_id)


def art_source(asset: Asset) -> ArtSource | None:
    """Return where an artwork asset's selection comes from, if it has one."""
    if asset.generated_style:
        return ArtSource.GENERATED
    return ArtSource.UPLOAD if asset.upload_hash else selected_art_source(asset.url)


def generation(asset: Asset) -> ArtGeneration | None:
    """Return how Overture drew the asset's art, if it drew it."""
    if asset.generated_style is None:
        return None
    return ArtGeneration(asset.generated_style, title_only=asset.generated_title_only)


def content(asset: Asset) -> ContentFacts | None:
    """Return the content Overture holds for the selection, or ``None``."""
    if asset.content_hash is None:
        return None
    return ContentFacts(
        asset.content_hash, asset.fingerprint, asset.width, asset.height, asset.duration
    )


def delivery(asset: Asset, destination: Destination = LOCAL) -> AssetDelivery | None:
    """Return the asset's delivery to *destination*, or ``None``."""
    for row in asset.deliveries:
        if _key(row) == destination.key:
            return row
    return None


def _key(row: AssetDelivery) -> tuple[int | None, str | None]:
    return row.server_id, row.server_item_id


def file_facts(row: AssetDelivery | None) -> FileFacts | None:
    """Return what the last inspection of a delivered file found, or ``None``."""
    if row is None or row.observed_hash is None or row.channel != DeliveryChannel.FILE:
        return None
    return FileFacts(
        row.observed_hash,
        row.file_mtime_ns,
        row.file_size,
        row.fingerprint,
        row.width,
        row.height,
        row.duration,
    )


def local_file(asset: Asset) -> FileFacts | None:
    """Return the facts of the file in the item's own folder, or ``None``."""
    return file_facts(delivery(asset))


def dimensions(asset: Asset) -> tuple[int | None, int | None]:
    """Return the size of the image in place: the local file's, else the content's.

    A collection keeps no local file, so what it shows is the content uploaded.
    """
    file = local_file(asset)
    return (file.width, file.height) if file else (asset.width, asset.height)


def shows_something(row: AssetDelivery) -> bool:
    """Whether something was seen at a delivery, Overture's content or not."""
    return row.observed_hash is not None or row.observed_ref is not None


def holds_content(row: AssetDelivery, asset: Asset) -> bool:
    """Whether a delivery holds the asset's content."""
    return asset.content_hash is not None and row.observed_hash == asset.content_hash


def _missing(asset: Asset, deliveries: Iterable[AssetDelivery]) -> list[AssetDelivery]:
    return [row for row in deliveries if row.required and not holds_content(row, asset)]


def missing_deliveries(asset: Asset) -> list[AssetDelivery]:
    """Return the required deliveries that do not hold the asset's content."""
    return _missing(asset, asset.deliveries)


def settled_status(
    asset: Asset, deliveries: Collection[AssetDelivery] | None = None
) -> AssetStatus:
    """Return the status the asset's rows give it, by the module's one rule.

    *deliveries* are the ones to judge it by, when they are not yet its own.
    """
    held = asset.deliveries if deliveries is None else deliveries
    if not asset.needed:
        return AssetStatus.COMPLETE
    selected = selection(asset) is not None
    if selected and not _missing(asset, held):
        return AssetStatus.COMPLETE
    started = (
        selected
        or asset.content_hash is not None
        or any(shows_something(row) for row in held)
    )
    return AssetStatus.PARTIAL if started else AssetStatus.MISSING


# --- Writing -----------------------------------------------------------------


def _owned(owner: Owner, kind: ServerAsset) -> Asset:
    """Return the owner's asset of *kind*, attaching a new row when it has none."""
    existing = find_asset(owner, kind)
    if existing is not None:
        return existing
    if isinstance(owner, MediaCollection):
        created = Asset(collection_id=owner.id, kind=kind)
    elif isinstance(owner, Season):
        created = Asset(season_id=owner.id, kind=kind)
    else:
        created = Asset(media_item_id=owner.id, kind=kind)
    owner.assets.append(created)
    return created


def _settle(asset: Asset) -> Asset:
    """Store the status the asset's rows give it."""
    asset.status = settled_status(asset)
    return asset


def place(
    owner: Owner,
    kind: ServerAsset,
    destinations: Iterable[Destination],
) -> Asset:
    """Make *destinations* the places the owner's *kind* has to be.

    A destination already placed keeps what was seen there; one no longer
    listed is dropped with it.
    """
    wanted = {destination.key: destination for destination in destinations}
    if not wanted and find_asset(owner, kind) is None:
        return read_asset(owner, kind)
    asset = _owned(owner, kind)
    for row in list(asset.deliveries):
        if _key(row) not in wanted:
            asset.deliveries.remove(row)
    for destination in wanted.values():
        row = delivery(asset, destination)
        if row is None:
            _add(asset, destination)
        else:
            if row.channel != destination.channel:
                _forget(row)
            row.channel = destination.channel
            row.required = destination.required
    return _settle(asset)


def _forget(row: AssetDelivery) -> None:
    """Forget everything seen at a delivery, which now names another place."""
    row.observed_hash = None
    row.observed_ref = None
    row.file_mtime_ns = None
    row.file_size = None
    row.fingerprint = None
    row.width = None
    row.height = None
    row.duration = None
    row.checked_at = None


def place_local(
    owner: MediaItem | Season,
    kinds: Iterable[ServerAsset],
    *,
    folder: bool,
    moved: bool = False,
) -> None:
    """Place an item's or season's assets in its local folder, if it has one.

    A *moved* folder holds none of the files seen in the old one, so what
    was seen there is forgotten.
    """
    for kind in kinds:
        asset = place(owner, kind, (LOCAL,) if folder else ())
        if moved and (row := delivery(asset)) is not None:
            # Cleared in place: a replacement row would be inserted before
            # the old one is deleted, against the one-local-row index.
            _forget(row)
            _settle(asset)


def set_needed(owner: Owner, kind: ServerAsset, needed: bool) -> Asset:
    """Record whether anything is wanted for the owner's *kind*.

    An asset nothing is wanted for (``needed`` false) is complete as it is.
    """
    asset = _owned(owner, kind)
    asset.needed = needed
    return _settle(asset)


def select_art(
    owner: Owner,
    kind: ServerAsset,
    url: PublicArtUrl,
    *,
    poster_style: CollectionPosterStyle | None = None,
) -> Asset:
    """Select the artwork at *url*; content held for another selection goes.

    A collection's poster takes *poster_style*, the OvertureDB poster it is
    contributed as.
    """
    asset = _owned(owner, kind)
    if (asset.url, asset.upload_hash) != (url, None):
        _forget_content(asset)
    asset.url = url
    asset.upload_hash = None
    asset.poster_style = poster_style
    asset.generated_style = None
    asset.generated_title_only = False
    return _settle(asset)


def select_upload(
    owner: Owner,
    kind: ServerAsset,
    upload_hash: str,
    *,
    generated: ArtGeneration | None = None,
) -> Asset:
    """Select the image Overture keeps as *upload_hash*.

    *generated* says how Overture drew it, for an image it made.
    """
    asset = _owned(owner, kind)
    if (asset.url, asset.upload_hash) != (None, upload_hash):
        _forget_content(asset)
    asset.url = None
    asset.upload_hash = upload_hash
    asset.poster_style = None
    asset.generated_style = generated.style if generated else None
    asset.generated_title_only = generated.title_only if generated else False
    return _settle(asset)


def select_theme(
    owner: MediaItem | MediaCollection,
    youtube_id: str,
    *,
    source: ThemeIdSource,
    title: str | None,
    duration: int | None,
    found_by: ThemeBulkSource | None = None,
) -> Asset:
    """Select the YouTube video *youtube_id* as the theme, and how it was found.

    *found_by* names the catalog or search a collection's video came from.
    """
    asset = _owned(owner, ServerAsset.THEME)
    if asset.youtube_id != youtube_id:
        _forget_content(asset)
    asset.youtube_id = youtube_id
    asset.youtube_id_source = source
    asset.theme_found_by = found_by
    asset.youtube_title = title
    asset.youtube_duration = duration
    asset.provenance_cleared = False
    return _settle(asset)


def clear_selection(owner: Owner, kind: ServerAsset) -> None:
    """Forget the selection and its content; what deliveries hold is kept.

    A theme's provenance stays cleared until a video is selected again, so a
    later inspection does not read the old video back from the file.
    """
    asset = find_asset(owner, kind)
    if asset is None and kind is not ServerAsset.THEME:
        return
    asset = asset or _owned(owner, kind)
    asset.url = None
    asset.upload_hash = None
    asset.youtube_id = None
    asset.youtube_id_source = None
    asset.theme_found_by = None
    asset.youtube_title = None
    asset.youtube_duration = None
    asset.poster_style = None
    asset.generated_style = None
    asset.generated_title_only = False
    asset.provenance_cleared = kind is ServerAsset.THEME
    _forget_content(asset)
    _settle(asset)


def _forget_content(asset: Asset) -> None:
    asset.content_hash = None
    asset.fingerprint = None
    asset.width = None
    asset.height = None
    asset.duration = None


def record_content(owner: Owner, kind: ServerAsset, facts: ContentFacts) -> Asset:
    """Record *facts* as the bytes the current selection is."""
    asset = _owned(owner, kind)
    asset.content_hash = facts.content_hash
    asset.fingerprint = facts.fingerprint
    asset.width = facts.width
    asset.height = facts.height
    asset.duration = facts.duration
    return _settle(asset)


def record_file(
    owner: Owner,
    kind: ServerAsset,
    facts: FileFacts | None,
    *,
    destination: Destination = LOCAL,
    at: datetime | None = None,
) -> Asset | None:
    """Record what an inspection found at a file destination: *facts*, or none.

    A found file places its destination if it was not, as it proves the asset
    is kept there; an absent one places nothing.

    Returns:
        The asset, or ``None`` when an absent file found nothing to record.
    """
    asset = find_asset(owner, kind)
    row = delivery(asset, destination) if asset is not None else None
    if facts is None:
        if asset is None or row is None:
            return asset
        _forget(row)
    else:
        asset = asset or _owned(owner, kind)
        row = row or _add(asset, destination)
        row.observed_hash = facts.file_hash
        row.file_mtime_ns = facts.file_mtime_ns
        row.file_size = facts.file_size
        row.fingerprint = facts.fingerprint
        row.width = facts.width
        row.height = facts.height
        row.duration = facts.duration
    row.checked_at = at
    return _settle(asset)


def record_written(
    owner: Owner,
    kind: ServerAsset,
    facts: FileFacts,
    *,
    destination: Destination = LOCAL,
    at: datetime | None = None,
) -> Asset:
    """Record a file Overture wrote for the selection: its content, delivered."""
    record_content(owner, kind, facts.content())
    asset = record_file(owner, kind, facts, destination=destination, at=at)
    if asset is None:
        raise ValueError("A written file is always recorded")
    return asset


def confirm_delivery(
    owner: Owner,
    kind: ServerAsset,
    destination: Destination,
    *,
    ref: str | None,
    at: datetime | None = None,
) -> Asset:
    """Record that *destination* received the asset's content, named *ref* there.

    Raises:
        ValueError: When the asset has no content to have delivered.
    """
    asset = _owned(owner, kind)
    if asset.content_hash is None:
        raise ValueError("Only content Overture holds can be delivered")
    row = delivery(asset, destination) or _add(asset, destination)
    row.observed_hash = asset.content_hash
    row.observed_ref = ref
    row.checked_at = at
    return _settle(asset)


def observe(
    owner: Owner,
    kind: ServerAsset,
    destination: Destination,
    evidence: Evidence,
    *,
    ref: str | None,
    at: datetime | None = None,
) -> Asset | None:
    """Record what a check of a server copy found: *evidence*, and *ref*.

    *ref* is what the server names its current image or theme by, ``None``
    when it shows none. Only :attr:`Evidence.DIFFERENT` takes the content
    away from the copy, and only :attr:`Evidence.SAME` gives it the content.
    :attr:`Evidence.UNKNOWN` leaves the copy as it was, *ref* included: a copy
    that could not be read proves nothing about what it shows, and keeping
    the ref it was confirmed under makes the next check read it again.
    """
    asset = find_asset(owner, kind)
    row = delivery(asset, destination) if asset is not None else None
    if asset is None or row is None or evidence is Evidence.UNKNOWN:
        return asset
    if evidence is Evidence.SAME and asset.content_hash is not None:
        row.observed_hash = asset.content_hash
    else:
        row.observed_hash = None
    row.observed_ref = ref
    row.checked_at = at
    return _settle(asset)


def _add(asset: Asset, destination: Destination) -> AssetDelivery:
    row = AssetDelivery(
        asset_id=asset.id or 0,
        server_id=destination.server_id,
        server_item_id=destination.server_item_id,
        channel=destination.channel,
        required=destination.required,
    )
    asset.deliveries.append(row)
    return row


def statuses(
    owner: Owner, kinds: Collection[ServerAsset]
) -> dict[ServerAsset, AssetStatus]:
    """Return the stored status of each of the owner's *kinds*."""
    return {kind: read_asset(owner, kind).status for kind in kinds}


def combined_status(parts: Iterable[AssetStatus]) -> AssetStatus:
    """Return the status of assets taken together: complete only if all are.

    No parts at all are missing, so a show without a tracked season never has
    complete season posters.
    """
    parts = list(parts)
    if parts and all(part is AssetStatus.COMPLETE for part in parts):
        return AssetStatus.COMPLETE
    if any(part is not AssetStatus.MISSING for part in parts):
        return AssetStatus.PARTIAL
    return AssetStatus.MISSING


@dataclass(frozen=True, slots=True)
class ItemArtStatus:
    """An item's artwork taken together, and its season posters on their own."""

    art: AssetStatus
    season_posters: AssetStatus


def item_art_status(item: MediaItem, seasons: Iterable[Season]) -> ItemArtStatus:
    """Return the status of an item's artwork; *seasons* are its tracked seasons.

    A show's artwork is complete only with a complete poster for every
    tracked season, so a show without one never is.
    """
    season_posters = combined_status(
        read_asset(season, ServerAsset.SEASON_POSTER).status for season in seasons
    )
    parts = [
        read_asset(item, ServerAsset.POSTER).status,
        read_asset(item, ServerAsset.BACKGROUND).status,
    ]
    if item.media_type is MediaType.SHOW:
        parts.append(season_posters)
    return ItemArtStatus(combined_status(parts), season_posters)


class LedgerRefusalError(RuntimeError):
    """A flush that would store an asset's status other than its rows give."""


def _asset_of(session: OrmSession, row: AssetDelivery) -> Asset | None:
    """The asset *row* delivers, though it was written by its asset's ID alone."""
    if "asset" not in inspect(row).unloaded:
        return row.asset
    with session.no_autoflush:
        return session.get(Asset, row.asset_id)


def verify_flush(session: OrmSession, *_: object) -> None:
    """Refuse a flush that leaves an asset with a status its rows do not give.

    Every transition settles the status, so a mismatch means a write that
    bypassed this module; it fails where it happens instead of drifting. Each
    asset a new, changed or deleted asset or delivery touches is judged by the
    deliveries it holds once the flush is done, however they were written.

    Raises:
        LedgerRefusalError: When an asset's stored status disagrees with its rows.
    """
    touched: dict[int, Asset] = {}
    added: dict[int, list[AssetDelivery]] = {}
    for row in (*session.new, *session.dirty, *session.deleted):
        if isinstance(row, Asset):
            touched[id(row)] = row
        elif isinstance(row, AssetDelivery) and (asset := _asset_of(session, row)):
            touched[id(asset)] = asset
            # Rows compare by their fields, so a row is found by its identity.
            if row in session.new and all(held is not row for held in asset.deliveries):
                added.setdefault(id(asset), []).append(row)
    for key, asset in touched.items():
        if asset in session.deleted:
            continue
        held = [
            *(row for row in asset.deliveries if row not in session.deleted),
            *added.get(key, ()),
        ]
        if asset.status != (expected := settled_status(asset, held)):
            raise LedgerRefusalError(
                f"Asset {asset.id} ({asset.kind}) stores {asset.status} where its "
                f"rows give {expected}: it was written outside the ledger"
            )
