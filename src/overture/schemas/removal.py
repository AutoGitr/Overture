"""What removing artwork or a theme does, and what each choice would affect."""

lazy from typing import Annotated, Literal, Self

lazy from pydantic import Field, model_validator

lazy from ..domain import ArtType
lazy from .base import StrictBaseModel
lazy from .validators import UniqueList

#: An item's art a removal names: one slot, or every slot of it and its seasons.
type ItemArtAsset = ArtType | Literal["art"]
#: The assets a removal names: art, or the theme.
type RemovableAsset = ItemArtAsset | Literal["theme"]


class AssetRemoval(StrictBaseModel):
    """What removing an asset does, in any combination.

    Overture only ever deletes images and MP3 themes: the art and theme files
    it manages in media folders, and the server's copies of them.
    """

    #: Forget the selection Overture saved.
    forget: bool = True
    #: Delete the file in the media folder.
    delete_file: bool = False
    #: Delete the media server's copy.
    delete_from_server: bool = False

    @model_validator(mode="after")
    def validate_choice(self) -> Self:
        """A removal removes something."""
        if not (self.forget or self.delete_file or self.delete_from_server):
            raise ValueError("Choose what to remove")
        return self


class RemovalTarget(StrictBaseModel):
    """The items or collections, and which of their assets, a removal acts on."""

    asset: RemovableAsset
    item_ids: UniqueList[Annotated[int, Field(gt=0)]] = Field(default_factory=list[int])
    collection_ids: UniqueList[Annotated[int, Field(gt=0)]] = Field(
        default_factory=list[int]
    )
    #: One season of the one item; without it a season poster names them all.
    season_id: Annotated[int, Field(gt=0)] | None = None

    @model_validator(mode="after")
    def validate_target(self) -> Self:
        """Name items or collections, and a season only for one show's poster."""
        if bool(self.item_ids) == bool(self.collection_ids):
            raise ValueError("Name items or collections")
        if self.collection_ids and self.asset is ArtType.SEASON_POSTER:
            raise ValueError("Collections have no season posters")
        if self.season_id is not None and (
            self.asset is not ArtType.SEASON_POSTER or len(self.item_ids) != 1
        ):
            raise ValueError("A season belongs to one show's season posters")
        return self


class RemovalOption(StrictBaseModel):
    """How many of the targets one removal choice would change."""

    count: int
    #: Why it changes none of them, when it cannot.
    unavailable: str | None = None


class RemovalOptions(StrictBaseModel):
    """What each removal choice would change for a target, as things stand."""

    forget: RemovalOption
    delete_file: RemovalOption
    delete_from_server: RemovalOption


type RemovalChoice = Literal["forget", "delete_file", "delete_from_server"]
