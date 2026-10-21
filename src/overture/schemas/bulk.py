"""Bulk job REST schemas."""

lazy from typing import Annotated, Any, Literal, Self

lazy from pydantic import Field, model_validator

lazy from ..domain import (
    ASSETS_MATCH_THRESHOLD_DEFAULT,
    DEFAULT_ART_SOURCE_ORDER,
    DEFAULT_THEME_SOURCE_ORDER,
    ITEM_ART_TYPES,
    MATCH_THRESHOLD_MAX,
    PERFECT_MATCH_ONLY,
    ArtBulkSource,
    ArtType,
    RecentUnit,
    ThemeBulkSource,
)
lazy from .base import StrictBaseModel
lazy from .common import JobEnvelope
lazy from .schedules import ScheduleResponseBase, ScheduleWrite
lazy from .validators import LibraryIds, UniqueList

AssetRunStatus = Literal["started", "already_running", "not_requested"]

#: Sources in priority order; at least one, each once.
type SourceOrder[T] = Annotated[UniqueList[T], Field(min_length=1)]


class BulkAssetsArtConfig(StrictBaseModel):
    """Art-specific assets workflow configuration."""

    art_types: UniqueList[ArtType] = Field(default_factory=lambda: list(ITEM_ART_TYPES))
    source_order: SourceOrder[ArtBulkSource] = Field(
        default_factory=lambda: list(DEFAULT_ART_SOURCE_ORDER)
    )
    #: Largest pHash distance local art matching accepts; ``-1`` accepts only
    #: byte-identical images.
    threshold: Annotated[int, Field(ge=PERFECT_MATCH_ONLY, le=MATCH_THRESHOLD_MAX)] = (
        ASSETS_MATCH_THRESHOLD_DEFAULT
    )


class BulkAssetsThemeConfig(StrictBaseModel):
    """Theme-specific assets workflow configuration."""

    source_order: SourceOrder[ThemeBulkSource] = Field(
        default_factory=lambda: list(DEFAULT_THEME_SOURCE_ORDER)
    )


class _BulkSharedRunFields(StrictBaseModel):
    """Shared library and skip fields for bulk asset work."""

    library_ids: LibraryIds = Field(default_factory=list[str])
    item_ids: UniqueList[Annotated[int, Field(gt=0)]] | None = None
    include_unmonitored: bool = Field(
        default=False, description="Include unmonitored items in either target scope."
    )
    overwrite_existing: bool = Field(
        default=False,
        description=(
            "Resolve sources again for saved selections and existing themes. "
            "Takes precedence over retry_saved_downloads; "
            "recent-check filtering still applies."
        ),
    )
    retry_saved_downloads: bool = Field(
        default=False,
        description=(
            "Restore missing files from saved artwork URLs or YouTube IDs "
            "without choosing a new source. Existing files are retained; "
            "recent-check filtering does not apply to these retries."
        ),
    )
    skip_recent_val: Annotated[int, Field(ge=0)] = 0
    skip_recent_unit: RecentUnit = RecentUnit.HOURS

    @model_validator(mode="after")
    def validate_target_selection(self) -> Self:
        """Explicit items replace libraries; an empty list never means all items."""
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
        if self.item_ids is None and not self.library_ids:
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
            raise ValueError("Scheduled assets require a library selection")
        return self


class BulkAssetsScheduleResponse(ScheduleResponseBase):
    """Saved unified assets schedule response."""

    kind: Literal["assets"] = "assets"
    config: BulkAssetsRequest


class BulkJobEvent(JobEnvelope):
    """Shared WebSocket payload fields for bulk art/theme lifecycle events."""

    done: int | None = None
    total: int | None = None
    queued: int | None = None
    downloaded: int | None = None
    adopted: int | None = None
    skipped: int | None = None
    no_match: int | None = None
    errors: int | None = None
    settled: int | None = None
    started_at: str | None = None
    finished_at: str | None = None


class BulkArtJobEvent(BulkJobEvent):
    """WebSocket payload for bulk art lifecycle events."""


class BulkThemeJobEvent(BulkJobEvent):
    """WebSocket payload for bulk theme lifecycle events."""
