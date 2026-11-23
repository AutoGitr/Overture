"""Bulk job REST schemas."""

lazy from collections.abc import Sequence
lazy from dataclasses import dataclass
lazy from functools import cached_property
lazy from typing import Annotated, Any, Literal, Self

lazy from pydantic import AfterValidator, Field, model_validator

lazy from ..domain import (
    ASSETS_MATCH_THRESHOLD_DEFAULT,
    CURRENT_SELECTION,
    CURRENT_SELECTION_LABEL,
    DEFAULT_ART_SOURCE_ORDER,
    DEFAULT_THEME_SOURCE_ORDER,
    ITEM_ART_TYPES,
    MATCH_THRESHOLD_MAX,
    PERFECT_MATCH_ONLY,
    ArtBulkSource,
    ArtSourceStep,
    ArtType,
    BulkSource,
    RecentUnit,
    ThemeBulkSource,
    ThemeSourceStep,
)
lazy from .base import PositiveId, StrictBaseModel
lazy from .common import JobEnvelope
lazy from .schedules import ScheduleResponseBase, ScheduleWrite
lazy from .validators import GroupNames, LibraryIds, UniqueList

AssetRunStatus = Literal["started", "already_running", "not_requested"]

#: What a source order means, as the API documents it.
_SOURCE_ORDER = (
    "Sources in the order they are tried. Those before `current_selection` "
    "may replace what a slot holds, its saved selection or a theme in place; "
    "those after it only fill slots that hold nothing. A saved selection "
    "missing from disk is downloaded again when no source replaces it."
)


def _holds_current_selection[T](order: list[T]) -> list[T]:
    if CURRENT_SELECTION not in order:
        raise ValueError(f"The source order must include {CURRENT_SELECTION_LABEL}")
    return order


#: Sources in priority order, each once, with Current selection among them.
type SourceOrder[T] = Annotated[UniqueList[T], AfterValidator(_holds_current_selection)]


@dataclass(frozen=True, slots=True)
class SourcePrecedence:
    """What a source order makes of what a slot holds.

    A slot holds its saved selection, or a theme in place. The sources ranked
    above Current selection may replace that; a slot holding nothing asks
    every source.
    """

    #: Every source, in order.
    sources: tuple[BulkSource, ...]
    #: The sources ranked above Current selection, in order.
    replacing: tuple[BulkSource, ...]

    @classmethod
    def of(cls, order: Sequence[ArtSourceStep | ThemeSourceStep]) -> Self:
        place = order.index(CURRENT_SELECTION)
        sources = tuple(
            step for step in order if isinstance(step, ArtBulkSource | ThemeBulkSource)
        )
        return cls(sources, sources[:place])

    def asked(self, *, holding: bool) -> tuple[BulkSource, ...]:
        """The sources a slot asks: those that may replace what it holds, or all."""
        return self.replacing if holding else self.sources

    def replaces(self, source: BulkSource) -> bool:
        """Whether *source* may replace what a slot holds."""
        return source in self.replacing

    @property
    def catalogs_only(self) -> bool:
        """Whether every source is a curated catalog."""
        return all(source.catalog for source in self.sources)


class BulkAssetsArtConfig(StrictBaseModel):
    """Art-specific assets workflow configuration."""

    art_types: UniqueList[ArtType] = Field(default_factory=lambda: list(ITEM_ART_TYPES))
    source_order: SourceOrder[ArtSourceStep] = Field(
        default_factory=lambda: list(DEFAULT_ART_SOURCE_ORDER),
        description=_SOURCE_ORDER,
    )
    #: Largest pHash distance local art matching accepts; ``-1`` accepts only
    #: byte-identical images.
    threshold: Annotated[int, Field(ge=PERFECT_MATCH_ONLY, le=MATCH_THRESHOLD_MAX)] = (
        ASSETS_MATCH_THRESHOLD_DEFAULT
    )

    @cached_property
    def precedence(self) -> SourcePrecedence:
        return SourcePrecedence.of(self.source_order)


class BulkAssetsThemeConfig(StrictBaseModel):
    """Theme-specific assets workflow configuration."""

    source_order: SourceOrder[ThemeSourceStep] = Field(
        default_factory=lambda: list(DEFAULT_THEME_SOURCE_ORDER),
        description=_SOURCE_ORDER,
    )

    @cached_property
    def precedence(self) -> SourcePrecedence:
        return SourcePrecedence.of(self.source_order)


class _BulkSharedRunFields(StrictBaseModel):
    """Shared library and skip fields for bulk asset work."""

    library_ids: LibraryIds = Field(default_factory=list[str])
    item_ids: UniqueList[PositiveId] | None = None
    collection_ids: UniqueList[PositiveId] | None = Field(
        default=None, description="These collections, besides any groups."
    )
    collection_groups: GroupNames | None = Field(
        default=None, description="The collections of these groups."
    )
    all_collections: bool = False
    include_unmonitored: bool = Field(
        default=False, description="Include unmonitored items in either target scope."
    )
    skip_recent_val: Annotated[int, Field(ge=0)] = 0
    skip_recent_unit: RecentUnit = RecentUnit.HOURS

    @property
    def collection_scope(self) -> bool:
        """Whether the run targets collections, alone or beside libraries."""
        return (
            self.all_collections
            or self.collection_ids is not None
            or self.collection_groups is not None
        )

    @model_validator(mode="after")
    def validate_target_selection(self) -> Self:
        """Libraries may run beside every collection, or chosen groups and collections.

        A sidebar snapshot of items runs alone, and an empty list never means
        everything.
        """
        if self.collection_ids == []:
            raise ValueError("collection_ids must include at least one collection")
        if self.all_collections and (
            self.collection_groups is not None or self.collection_ids is not None
        ):
            raise ValueError("Select some collections or every collection")
        if self.item_ids is not None and (self.library_ids or self.collection_scope):
            raise ValueError("Select collections, items, or libraries")
        if self.item_ids is not None:
            if self.library_ids:
                raise ValueError("Select either library_ids or item_ids")
            if not self.item_ids:
                raise ValueError("item_ids must include at least one item")
        return self

    def shared_fields(self) -> dict[str, Any]:
        """Return the target and skip fields every asset workflow shares."""
        return self.model_dump(include=set(_BulkSharedRunFields.model_fields))


class BulkMatchArtRequest(BulkAssetsArtConfig, _BulkSharedRunFields):
    """Internal bulk art worker request payload."""


class BulkThemeRequest(BulkAssetsThemeConfig, _BulkSharedRunFields):
    """Internal bulk theme worker request payload."""


class BulkAssetsRequest(_BulkSharedRunFields):
    """Validate the unified assets workflow request payload."""

    art: BulkAssetsArtConfig | None = None
    themes: BulkAssetsThemeConfig | None = None

    @model_validator(mode="after")
    def validate_selected_assets(self) -> Self:
        """Require at least one selected asset workflow and a valid target."""
        if self.art is None and self.themes is None:
            raise ValueError("At least one asset workflow must be selected")
        if self.item_ids is None and not self.collection_scope and not self.library_ids:
            raise ValueError("Select at least one library")
        return self

    def art_request(self) -> BulkMatchArtRequest | None:
        """Return an internal art request with shared fields applied."""
        if self.art is None:
            return None
        return BulkMatchArtRequest.model_validate(
            {**self.shared_fields(), **self.art.model_dump()}
        )

    def theme_request(self) -> BulkThemeRequest | None:
        """Return an internal theme request with shared fields applied."""
        if self.themes is None:
            return None
        return BulkThemeRequest.model_validate(
            {**self.shared_fields(), **self.themes.model_dump()}
        )


class BulkAssetsRunResponse(StrictBaseModel):
    """Immediate unified assets run status."""

    art: AssetRunStatus = "not_requested"
    themes: AssetRunStatus = "not_requested"


class BulkAssetsStopRequest(StrictBaseModel):
    """Selected assets workflows to stop."""

    art: bool = True
    themes: bool = True


class BulkAssetsScheduleWrite(ScheduleWrite[BulkAssetsRequest]):
    """Create or update a saved assets schedule."""

    @model_validator(mode="after")
    def validate_schedule_scope(self) -> Self:
        """Sidebar snapshots are only available for immediate runs."""
        if self.config.item_ids is not None:
            raise ValueError(
                "Scheduled assets require libraries, collections or collection groups"
            )
        return self


class BulkAssetsScheduleResponse(ScheduleResponseBase):
    """Saved unified assets schedule response."""

    kind: Literal["assets"] = "assets"
    config: BulkAssetsRequest


class BulkJobEvent(JobEnvelope):
    """Shared WebSocket payload fields for bulk art/theme lifecycle events."""

    settled: int | None = None


class BulkArtJobEvent(BulkJobEvent):
    """WebSocket payload for bulk art lifecycle events."""


class BulkThemeJobEvent(BulkJobEvent):
    """WebSocket payload for bulk theme lifecycle events."""
