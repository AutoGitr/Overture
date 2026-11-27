"""Portable collection files: OvertureDB presets and Overture's own exports.

A file names media types where a collection names libraries, so it can be
added to any install: each collection or set in it fills the create form,
where the person adding it picks the libraries. It says what each collection
is and nothing more; how it is shown, its art and themes, and what it
requests or labels follow the defaults of the install adding it.
"""

lazy from datetime import datetime
lazy from typing import Annotated, Self

lazy from pydantic import Field, model_validator

lazy from ..catalog_contract.contract import PRESET_ID_PATTERN, PRESET_VERSION
lazy from ..domain import (
    CollectionPosterStyle,
    MediaType,
    PresetCategory,
)
lazy from ..utils.collection_fields import FIELDS
lazy from .base import PositiveId, PublicText, StrictBaseModel
lazy from .catalog import ContributionIssue
lazy from .collections import (
    CollectionContent,
    CollectionContentPolicy,
    CollectionGeneratorBase,
    FilterGroup,
    MinimumItems,
)
lazy from .validators import (
    CollectionIds,
    GroupName,
    GroupNames,
    RequiredGroupName,
    UniqueList,
)

#: Collections one file adds.
PRESET_COLLECTIONS_MAX = 50
#: Groups one file adds.
PRESET_GROUPS_MAX = 10

type ArtUrl = Annotated[str, Field(min_length=1, max_length=2000, pattern=r"^https://")]
type PresetTag = Annotated[str, Field(min_length=1, max_length=40)]
type PresetId = Annotated[
    str, Field(max_length=60, pattern=f"^{PRESET_ID_PATTERN.pattern}$")
]


class PresetMetadata(StrictBaseModel):
    """How a preset describes itself in the gallery."""

    id: PresetId
    title: Annotated[str, Field(min_length=1, max_length=100)]
    description: Annotated[str, Field(min_length=1, max_length=500)]
    category: PresetCategory
    tags: Annotated[list[PresetTag], Field(max_length=10)] = Field(
        default_factory=list[str]
    )
    #: Every media type the preset's collections and sets hold.
    media_types: Annotated[UniqueList[MediaType], Field(min_length=1)]


class PresetImage(StrictBaseModel):
    """A public image link."""

    url: ArtUrl


class PresetPoster(PresetImage):
    """A public poster link, and which OvertureDB poster style it is."""

    style: CollectionPosterStyle = CollectionPosterStyle.INDIVIDUAL


class PresetArt(StrictBaseModel):
    """The art a collection starts with."""

    poster: PresetPoster | None = None
    background: PresetImage | None = None


class PortableCollection(CollectionContent):
    """A collection, with criteria for each media type instead of each library.

    ``collection_group`` names a group of the file or one the install has.
    """

    minimum_items: MinimumItems | None = None
    #: Plex evaluates the criteria live instead of Overture on each sync.
    smart: bool = False
    #: The most members taken from each library.
    limit: Annotated[int, Field(ge=1, le=10000)] | None = None
    criteria: Annotated[dict[MediaType, FilterGroup], Field(min_length=1)]
    art: PresetArt | None = None

    @model_validator(mode="after")
    def validate_criteria(self) -> Self:
        """Require a condition for each media type."""
        if any(criteria.is_empty() for criteria in self.criteria.values()):
            raise ValueError(f"Add a condition for each media type of {self.title}")
        return self


class PortableSet(CollectionGeneratorBase):
    """A collection set, for media types instead of libraries."""

    media_types: Annotated[UniqueList[MediaType], Field(min_length=1)]


class PortableGroup(CollectionContentPolicy):
    """A group's defaults, and the set it runs when it is one."""

    name: RequiredGroupName
    generator: PortableSet | None = None


def _criteria(file: CollectionPresetFile) -> list[tuple[MediaType, FilterGroup]]:
    return [
        *(
            (media_type, criteria)
            for collection in file.collections
            for media_type, criteria in collection.criteria.items()
        ),
        *(
            (media_type, criteria)
            for group in file.groups
            if group.generator is not None
            for media_type in group.generator.media_types
            for criteria in (
                group.generator.criteria,
                *(value.criteria for value in group.generator.custom_values),
            )
        ),
    ]


class CollectionPresetFile(StrictBaseModel):
    """Collections, sets and groups that can be added to any install."""

    #: The one version of the format this Overture reads.
    preset_version: Annotated[int, Field(ge=PRESET_VERSION, le=PRESET_VERSION)] = (
        PRESET_VERSION
    )
    #: How an OvertureDB preset describes itself; an export may leave it out.
    preset: PresetMetadata | None = None
    groups: Annotated[list[PortableGroup], Field(max_length=PRESET_GROUPS_MAX)] = Field(
        default_factory=list[PortableGroup]
    )
    collections: Annotated[
        list[PortableCollection], Field(max_length=PRESET_COLLECTIONS_MAX)
    ] = Field(default_factory=list[PortableCollection])

    @model_validator(mode="after")
    def validate_contents(self) -> Self:
        """Require something to add, each once, testing only what travels."""
        if not self.groups and not self.collections:
            raise ValueError("Add a collection or a set")
        names = [group.name.strip().casefold() for group in self.groups]
        if len(names) != len(set(names)):
            raise ValueError("Give each group its own name")
        titles = [collection.title.casefold() for collection in self.collections]
        if len(titles) != len(set(titles)):
            raise ValueError("Give each collection its own title")
        for _, criteria in _criteria(self):
            for condition in criteria.field_conditions():
                if not FIELDS[condition.field].portable:
                    raise ValueError(
                        f"{FIELDS[condition.field].label} names something only "
                        "one install has, so it cannot be added elsewhere"
                    )
        if self.preset is not None and (
            unlisted := self.media_types() - set(self.preset.media_types)
        ):
            raise ValueError(
                "The preset holds "
                + " and ".join(sorted(media_type.plural for media_type in unlisted))
                + " it does not list"
            )
        return self

    def media_types(self) -> set[MediaType]:
        """The media types its collections and sets hold."""
        return {media_type for media_type, _ in _criteria(self)} | {
            media_type
            for group in self.groups
            if group.generator is not None
            for media_type in group.generator.media_types
        }


class PresetListing(StrictBaseModel):
    """One OvertureDB preset in the gallery."""

    id: str
    #: Its description; None when this Overture cannot read the preset.
    preset: PresetMetadata | None = None
    file: CollectionPresetFile | None = None
    #: What to set up before its collections can find their titles, such as
    #: "Set TMDB_READ_ACCESS_TOKEN to use TMDB".
    setup: list[PublicText] = Field(default_factory=list[PublicText])
    #: Why it cannot be added, such as needing a newer Overture.
    problem: str | None = None
    #: A small rendition of its first poster.
    preview_url: str | None = None


class PresetGallery(StrictBaseModel):
    """The presets OvertureDB publishes."""

    generated_at: datetime | None = None
    presets: list[PresetListing] = Field(default_factory=list[PresetListing])
    #: Why the gallery could not be read.
    error: PublicText | None = None


class PresetExportRequest(StrictBaseModel):
    """What to export: collections, and groups with their sets and collections."""

    collection_ids: CollectionIds | None = None
    groups: GroupNames | None = None
    preset: PresetMetadata | None = None

    @model_validator(mode="after")
    def validate_selection(self) -> Self:
        """Require something to export."""
        if not self.collection_ids and not self.groups:
            raise ValueError("Choose collections or groups to export")
        return self


class PresetSubject(StrictBaseModel):
    """A collection, or the group a set was saved into."""

    collection_id: PositiveId | None = None
    group: GroupName | None = None

    @model_validator(mode="after")
    def validate_subject(self) -> Self:
        """Name exactly one collection or group."""
        if (self.collection_id is None) == (self.group is None):
            raise ValueError("Name a collection or a group")
        return self


class PresetUseCreate(PresetSubject):
    """Keep track of the OvertureDB preset item a collection or set was saved from."""

    preset_id: PresetId
    #: The collection's title or the set's group name in the preset.
    item: Annotated[str, Field(min_length=1, max_length=200)]


class PresetUseReview(PresetSubject):
    """Take OvertureDB's changes to a preset item, or keep the saved one as it is."""

    take: bool


class PresetUseRead(PresetUseCreate):
    """A collection or set saved from a preset, and what OvertureDB changed since."""

    #: The preset's title, while OvertureDB publishes it.
    preset_title: str | None = None
    #: What OvertureDB has changed in the item since, such as "criteria".
    changes: list[str] = Field(default_factory=list[str])
    #: OvertureDB no longer publishes the item.
    gone: bool = False


class PresetUses(StrictBaseModel):
    """Every collection and set saved from a preset."""

    uses: list[PresetUseRead] = Field(default_factory=list[PresetUseRead])
    #: Why OvertureDB's presets could not be read to compare them.
    error: PublicText | None = None


class PresetRefusal(StrictBaseModel):
    """Something left out of an export, and why."""

    title: str
    reason: PublicText


class PresetExport(StrictBaseModel):
    """An export, with what it left out and what an install adding it should know."""

    #: The file's text, without the settings it leaves unset; None when
    #: nothing chosen could be exported.
    text: str | None = None
    #: The groups and collections it holds.
    count: int = 0
    refused: list[PresetRefusal] = Field(default_factory=list[PresetRefusal])
    warnings: list[str] = Field(default_factory=list[str])
    #: The OvertureDB issue that contributes the file as a preset.
    issue: ContributionIssue | None = None
