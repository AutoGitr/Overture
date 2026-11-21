"""How an asset and its deliveries read, for items, seasons and collections alike."""

lazy from datetime import datetime

lazy from pydantic import Field

lazy from ..db.ledger import (
    art_source,
    dimensions,
    holds_content,
    local_file,
    read_asset,
    shows_something,
)
lazy from ..db.models.asset import Asset, AssetDelivery
lazy from ..db.models.media_collection import MediaCollection
lazy from ..db.models.media_item import MediaItem
lazy from ..domain import (
    ArtSource,
    ArtStyle,
    AssetStatus,
    CollectionPosterStyle,
    DeliveryChannel,
    ServerAsset,
    ThemeIdSource,
)
lazy from ..utils.art_urls import art_preview_url
lazy from .base import StrictBaseModel


class AssetFileRead(StrictBaseModel):
    """The file in the item's own folder, as the last inspection found it."""

    hash: str
    fingerprint: str | None = None
    width: int | None = None
    height: int | None = None
    #: Seconds of a theme file's audio.
    duration: int | None = None


class AssetDeliveryRead(StrictBaseModel):
    """One place the asset has to be, and whether it holds the content."""

    #: The server whose copy of a collection it is; none for the item's folder.
    server_id: int | None
    channel: DeliveryChannel
    #: The asset is complete only once this place holds its content.
    required: bool
    #: This place holds the content of the current selection.
    delivered: bool
    #: Something is there: a file, or an image or theme the server shows,
    #: whether or not it is the selection.
    present: bool
    #: When it was last checked; none before the first check.
    checked_at: datetime | None


class AssetRead(StrictBaseModel):
    """One artwork slot or theme: its selection, content, deliveries and status."""

    kind: ServerAsset
    status: AssetStatus
    #: ``False`` when nothing is wanted here, which leaves the asset complete.
    needed: bool
    url: str | None = None
    #: A smaller rendition of a selected artwork link, for lists.
    preview_url: str | None = None
    upload_hash: str | None = None
    #: Where selected artwork comes from.
    source: ArtSource | None = None
    poster_style: CollectionPosterStyle | None = None
    generated_style: ArtStyle | None = None
    generated_title_only: bool = False
    youtube_id: str | None = None
    youtube_id_source: ThemeIdSource | None = None
    youtube_title: str | None = None
    #: Seconds, as YouTube gives the video's length.
    youtube_duration: int | None = None
    #: The hash of the bytes the selection is, once Overture holds them; it
    #: versions the image Overture serves for the asset.
    content_hash: str | None = None
    #: The size of the image in place: the local file's, else the content's.
    width: int | None = None
    height: int | None = None
    #: Seconds a theme plays: the length of the audio Overture holds, else of
    #: the local file, else of the video.
    duration: int | None = None
    file: AssetFileRead | None = None
    deliveries: list[AssetDeliveryRead] = Field(default_factory=list[AssetDeliveryRead])


def _delivery_read(row: AssetDelivery, asset: Asset) -> AssetDeliveryRead:
    return AssetDeliveryRead(
        server_id=row.server_id,
        channel=row.channel,
        required=row.required,
        delivered=holds_content(row, asset),
        present=shows_something(row),
        checked_at=row.checked_at,
    )


def asset_read(asset: Asset) -> AssetRead:
    """Map one asset row, or a blank one, to its public shape."""
    art = asset.kind is not ServerAsset.THEME
    art_type = asset.kind.art_type
    file = local_file(asset)
    width, height = dimensions(asset)
    return AssetRead(
        kind=asset.kind,
        status=asset.status,
        needed=asset.needed,
        url=asset.url,
        preview_url=art_preview_url(asset.url, art_type)
        if asset.url and art_type
        else None,
        upload_hash=asset.upload_hash,
        source=art_source(asset) if art else None,
        poster_style=asset.poster_style,
        generated_style=asset.generated_style,
        generated_title_only=asset.generated_title_only,
        youtube_id=asset.youtube_id,
        youtube_id_source=asset.youtube_id_source,
        youtube_title=asset.youtube_title,
        youtube_duration=asset.youtube_duration,
        content_hash=asset.content_hash,
        width=width,
        height=height,
        duration=asset.duration
        or (file.duration if file else None)
        or asset.youtube_duration,
        file=AssetFileRead(
            hash=file.file_hash,
            fingerprint=file.fingerprint,
            width=file.width,
            height=file.height,
            duration=file.duration,
        )
        if file
        else None,
        deliveries=[_delivery_read(row, asset) for row in asset.deliveries],
    )


class TitleAssets(StrictBaseModel):
    """A title's or collection's poster, background and theme."""

    poster: AssetRead
    background: AssetRead
    theme: AssetRead


def assets_read(owner: MediaItem | MediaCollection) -> TitleAssets:
    """Map the owner's poster, background and theme, blank where it holds none."""
    return TitleAssets(
        poster=asset_read(read_asset(owner, ServerAsset.POSTER)),
        background=asset_read(read_asset(owner, ServerAsset.BACKGROUND)),
        theme=asset_read(read_asset(owner, ServerAsset.THEME)),
    )
