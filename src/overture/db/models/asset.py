"""Assets and their deliveries: what Overture chose, holds and placed where.

One :class:`Asset` row is one artwork slot or theme of an item, season or
collection. It records the selection, the content Overture holds for it, and
a stored status. Every place the content has to be is one
:class:`AssetDelivery`: the item's local folder, or a server's copy of a
collection. :mod:`overture.db.ledger` is the only writer of either table, so
the status always follows from the rows.
"""

lazy from datetime import datetime
lazy from typing import Any, ClassVar, Optional

lazy from sqlmodel import (
    AutoString,
    CheckConstraint,
    Field,
    Index,
    Relationship,
    SQLModel,
    UniqueConstraint,
    text,
)

lazy from ...domain import (
    ArtStyle,
    AssetStatus,
    CollectionPosterStyle,
    DeliveryChannel,
    ServerAsset,
    ThemeBulkSource,
    ThemeIdSource,
)
lazy from ...utils.art_urls import PublicArtUrl
lazy from ..columns import enum_type, typed_columns
lazy from .media_collection import MediaCollection
lazy from .media_item import MediaItem
lazy from .season import Season


class Asset(SQLModel, table=True):
    """One artwork slot or theme of exactly one item, season or collection."""

    __tablename__: ClassVar[Any] = "assets"
    __table_args__ = (
        CheckConstraint(
            "(media_item_id IS NOT NULL) + (season_id IS NOT NULL) "
            "+ (collection_id IS NOT NULL) = 1",
            name="ck_assets_owner",
        ),
        CheckConstraint(
            "(kind = 'season_poster') = (season_id IS NOT NULL)",
            name="ck_assets_season_kind",
        ),
        CheckConstraint(
            "(url IS NOT NULL) + (upload_hash IS NOT NULL) "
            "+ (youtube_id IS NOT NULL) <= 1",
            name="ck_assets_selection",
        ),
        CheckConstraint(
            "(kind = 'theme' AND url IS NULL AND upload_hash IS NULL) "
            "OR (kind != 'theme' AND youtube_id IS NULL)",
            name="ck_assets_selection_kind",
        ),
        CheckConstraint(
            "generated_style IS NULL OR upload_hash IS NOT NULL",
            name="ck_assets_generated",
        ),
        CheckConstraint(
            "NOT generated_title_only OR generated_style IS NOT NULL",
            name="ck_assets_generated_title_only",
        ),
        CheckConstraint(
            "(poster_style IS NOT NULL) = (collection_id IS NOT NULL "
            "AND kind = 'poster' AND url IS NOT NULL)",
            name="ck_assets_collection_poster_style",
        ),
        CheckConstraint(
            "youtube_id_source IS NULL OR youtube_id IS NOT NULL",
            name="ck_assets_theme_source",
        ),
        CheckConstraint(
            "theme_found_by IS NULL OR youtube_id IS NOT NULL",
            name="ck_assets_theme_found_by_video",
        ),
        UniqueConstraint("media_item_id", "kind", name="uq_assets_media_item"),
        UniqueConstraint("season_id", "kind", name="uq_assets_season"),
        UniqueConstraint("collection_id", "kind", name="uq_assets_collection"),
        Index("ix_assets_kind_status", "kind", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    media_item_id: int | None = Field(
        default=None, foreign_key="media_items.id", ondelete="CASCADE", index=True
    )
    season_id: int | None = Field(
        default=None, foreign_key="seasons.id", ondelete="CASCADE", index=True
    )
    collection_id: int | None = Field(
        default=None,
        foreign_key="media_collections.id",
        ondelete="CASCADE",
        index=True,
    )
    kind: ServerAsset = Field(sa_type=enum_type(ServerAsset))

    # The selection: a public artwork link, an image Overture keeps under its
    # hash, or a YouTube video. Exactly one, or none.
    # SQLModel maps no NewType; the column stays text. Typed so only a link
    # ``public_art_url`` checked can be assigned to it.
    url: PublicArtUrl | None = Field(default=None, sa_type=AutoString)
    upload_hash: str | None = None
    youtube_id: str | None = None
    #: Which OvertureDB poster field a collection's selected poster link is
    #: contributed as. Set exactly when a collection poster selects a link.
    poster_style: CollectionPosterStyle | None = Field(
        default=None, sa_type=enum_type(CollectionPosterStyle)
    )
    #: The selected upload is one Overture generated in this style from the
    #: owner's title, and generates again when the title changes.
    generated_style: ArtStyle | None = Field(default=None, sa_type=enum_type(ArtStyle))
    #: The generated poster shows the title alone, without its group.
    generated_title_only: bool = Field(default=False, nullable=False)
    #: How the selected video was established.
    youtube_id_source: ThemeIdSource | None = Field(
        default=None, sa_type=enum_type(ThemeIdSource)
    )
    #: The catalog or search a collection's theme video was found in, so a
    #: ThemerrDB theme is never contributed as OvertureDB's.
    theme_found_by: ThemeBulkSource | None = Field(
        default=None, sa_type=enum_type(ThemeBulkSource)
    )
    youtube_title: str | None = None
    #: Seconds, as YouTube gives the video's length.
    youtube_duration: int | None = None
    #: A theme whose selection was forgotten; the local file's embedded video
    #: is not read back as a selection until one is chosen again.
    provenance_cleared: bool = Field(default=False, nullable=False)

    #: The hash of the bytes the selection is, once Overture has them. Each
    #: required delivery holding these bytes completes the asset. A Plex
    #: collection theme uploaded before themes were hashed is named
    #: ``youtube:<video>`` instead, until it is uploaded again.
    content_hash: str | None = None
    #: The content's perceptual fingerprint: an image's pHash, or the hash of
    #: a theme's audio stream, which leaves out tags a server may rewrite.
    fingerprint: str | None = None
    width: int | None = None
    height: int | None = None
    #: Seconds of a theme's audio.
    duration: int | None = None

    #: ``False`` when the owner's policy asks for no such asset, which leaves
    #: it complete as it is.
    needed: bool = Field(default=True, nullable=False)
    status: AssetStatus = Field(
        default=AssetStatus.MISSING, sa_type=enum_type(AssetStatus)
    )

    media_item: Optional["MediaItem"] = Relationship(back_populates="assets")
    season: Optional["Season"] = Relationship(back_populates="assets")
    collection: Optional["MediaCollection"] = Relationship(back_populates="assets")
    #: Joined into the asset's own query: an asset is never read without them.
    deliveries: list["AssetDelivery"] = Relationship(
        back_populates="asset",
        cascade_delete=True,
        sa_relationship_kwargs={"lazy": "joined", "order_by": "AssetDelivery.id"},
    )

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if "deliveries" not in data:
            self.deliveries = []


class AssetDelivery(SQLModel, table=True):
    """One place an asset's content has to be, and what was last seen there.

    A delivery without a server is the item's local folder; one with a server
    is that server's copy of a collection, written as a file in its folder or
    uploaded through its API.
    """

    __tablename__: ClassVar[Any] = "asset_deliveries"
    __table_args__ = (
        CheckConstraint(
            "(server_id IS NULL) = (server_item_id IS NULL)",
            name="ck_asset_deliveries_destination",
        ),
        CheckConstraint(
            "server_id IS NOT NULL OR channel = 'file'",
            name="ck_asset_deliveries_local_file",
        ),
        UniqueConstraint(
            "asset_id", "server_id", "server_item_id", name="uq_asset_deliveries"
        ),
        # SQLite counts NULLs as distinct, so the one local folder needs its own.
        Index(
            "uq_asset_deliveries_local",
            "asset_id",
            unique=True,
            sqlite_where=text("server_id IS NULL"),
        ),
        Index("ix_asset_deliveries_server", "server_id", "server_item_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    asset_id: int = Field(foreign_key="assets.id", ondelete="CASCADE", index=True)
    server_id: int | None = Field(
        default=None, foreign_key="media_servers.id", ondelete="CASCADE"
    )
    server_item_id: str | None = None
    channel: DeliveryChannel = Field(sa_type=enum_type(DeliveryChannel))
    #: Whether the asset is complete only once this delivery holds its content.
    required: bool = Field(default=True, nullable=False)

    #: The content last confirmed at the destination: a file's hash, or the
    #: content an upload sent and a check found the server still showing.
    observed_hash: str | None = None
    #: What the server names its current image or theme by (an image link or
    #: theme ID), as the last check saw it.
    observed_ref: str | None = None
    # A local file's stat revision and image facts, as the last inspection saw.
    file_mtime_ns: int | None = None
    file_size: int | None = None
    #: The file's fingerprint, as :attr:`Asset.fingerprint` is the content's.
    fingerprint: str | None = None
    width: int | None = None
    height: int | None = None
    #: Seconds of a theme file's audio.
    duration: int | None = None
    checked_at: datetime | None = None

    asset: "Asset" = Relationship(back_populates="deliveries")


typed_columns(Asset)
typed_columns(AssetDelivery)
