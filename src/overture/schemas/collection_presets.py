"""Portable collection files: OvertureDB presets and Overture's own exports.

A file names media types where a collection names libraries, so it can be
added to any install; the person adding it picks the libraries.
"""

lazy from datetime import datetime
lazy from typing import Annotated, Literal, Self

lazy from pydantic import Field, model_validator

lazy from ..catalog_contract.contract import PRESET_ID_PATTERN, PRESET_VERSION
lazy from ..domain import (
    CollectionPosterStyle,
    Integration,
    MediaType,
    PresetCategory,
)
lazy from ..utils.collection_fields import FIELDS
lazy from .base import PublicText, StrictBaseModel
lazy from .catalog import ContributionIssue
lazy from .collections import (
    CollectionGeneratorBase,
    CollectionOptions,
    CollectionPolicyBase,
    FilterGroup,
    LibraryId,
)
lazy from .validators import CollectionIds, GroupName, GroupNames, UniqueList

#: Collections one file adds.
PRESET_COLLECTIONS_MAX = 50
#: Groups one file adds.
PRESET_GROUPS_MAX = 10

type ArtUrl = Annotated[str, Field(min_length=1, max_length=2000, pattern=r"^https://")]
type PresetTag = Annotated[str, Field(min_length=1, max_length=40)]


class PresetMetadata(StrictBaseModel):
    """How a preset describes itself in the gallery."""

    id: Annotated[str, Field(max_length=60, pattern=f"^{PRESET_ID_PATTERN.pattern}$")]
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


class PortableCollection(CollectionOptions):
    """A collection, with criteria for each media type instead of each library.

    ``collection_group`` names a group of the file or one the install has.
    """

    policy: CollectionPolicyBase = Field(default_factory=CollectionPolicyBase)
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


class PortableGroup(CollectionPolicyBase):
    """A group's defaults, and the set it runs when it is one."""

    name: Annotated[GroupName, Field(min_length=1)]
    generator: PortableSet | None = None
    #: Head the group's collections with an empty one titled after the group.
    separator: bool = False


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
    #: Integrations it needs that are not set up.
    unavailable: list[Integration] = Field(default_factory=list[Integration])
    #: Why it cannot be added, such as needing a newer Overture.
    problem: str | None = None
    #: A small rendition of its first poster.
    preview_url: str | None = None
    #: When it was last added here; None when it never was.
    added_at: datetime | None = None
    #: What the published version changes since it was added, such as
    #: "Changes Christmas"; empty when nothing did.
    changes: list[str] = Field(default_factory=list[str])


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


class PresetRefusal(StrictBaseModel):
    """Something left out of an export, and why."""

    title: str
    reason: PublicText


class PresetExport(StrictBaseModel):
    """An export, with what it left out and what an install adding it should know."""

    #: None when nothing chosen could be exported.
    file: CollectionPresetFile | None = None
    refused: list[PresetRefusal] = Field(default_factory=list[PresetRefusal])
    warnings: list[str] = Field(default_factory=list[str])
    #: The OvertureDB issue that contributes the file as a preset.
    issue: ContributionIssue | None = None


class PresetImportRequest(StrictBaseModel):
    """A file to add, the libraries for each media type, and what to change."""

    file: CollectionPresetFile
    libraries: Annotated[
        dict[MediaType, Annotated[list[LibraryId], Field(min_length=1, max_length=20)]],
        Field(min_length=1),
    ]
    #: Collection titles and group names to skip, whether new or updated.
    skip: Annotated[list[str], Field(max_length=PRESET_COLLECTIONS_MAX)] = Field(
        default_factory=list[str]
    )

    @model_validator(mode="after")
    def validate_libraries(self) -> Self:
        """A library holds one media type, so it is chosen for one."""
        chosen = [library for ids in self.libraries.values() for library in ids]
        if len(chosen) != len(set(chosen)):
            raise ValueError("Choose each library for one media type")
        return self


type PresetItemStatus = Literal["add", "update", "skip", "refused"]


class PresetPlanItem(StrictBaseModel):
    """What adding one collection or group of a file does."""

    kind: Literal["collection", "group"]
    name: str
    status: PresetItemStatus
    #: Why it is refused, or a warning about what it does once added.
    reason: PublicText | None = None
    #: Whether to add or update it unless someone says otherwise; something
    #: deleted here since the preset added it is left out.
    chosen: bool = True


class PresetImportPlan(StrictBaseModel):
    """What adding a file does, item by item, before anything is saved."""

    items: list[PresetPlanItem] = Field(default_factory=list[PresetPlanItem])
    warnings: list[str] = Field(default_factory=list[str])


class PresetImportResult(StrictBaseModel):
    """What adding a file did, item by item."""

    items: list[PresetPlanItem] = Field(default_factory=list[PresetPlanItem])
    collection_ids: list[int] = Field(default_factory=list[int])
