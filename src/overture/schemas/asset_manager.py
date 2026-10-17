"""Asset manager REST and WebSocket schemas."""

lazy from enum import StrEnum

lazy from pydantic import Field

lazy from ..domain import ServerAsset
lazy from .base import StrictBaseModel
lazy from .common import JobEnvelope, MediaFolderScope
lazy from .validators import UniqueList


class ScanRequest(MediaFolderScope):
    """Validate the asset scan request payload."""

    art_types: UniqueList[ServerAsset] = Field(
        default_factory=lambda: list(ServerAsset)
    )


class RenameItem(StrictBaseModel):
    """One asset rename request."""

    current_path: str = ""
    suggested_path: str = ""


class RenameRequest(StrictBaseModel):
    """Validate the asset rename request payload."""

    renames: list[RenameItem]
    snapshot_finished_at: str


class AssetIssue(StrictBaseModel):
    """One misnamed asset issue detected by an asset scan."""

    folder: str
    current_path: str
    current_filename: str
    suggested_path: str
    suggested_filename: str
    type: ServerAsset
    conflict: bool = Field(
        description="Another file holds the slot, or is suggested for it instead."
    )
    width: int
    height: int
    conflict_with: str | None = Field(
        default=None, description="The file the suggestion conflicts with."
    )
    season_num: int | None = None
    potential_false_positive: bool = Field(
        description="Only the file's shape suggests this slot; its name does not.",
    )
    renamed: bool | None = None
    rename_error: str | None = None


class AssetScanProgressEvent(JobEnvelope):
    """WebSocket payload for asset scan lifecycle events."""

    results_run_id: str | None = None
    results_total: int | None = None
    done: int | None = None
    total: int | None = None
    total_folders: int | None = None
    issues_found: int | None = None
    results_found: int | None = None
    errors: int | None = None
    started_at: str | None = None
    finished_at: str | None = None
    issues: list[AssetIssue] | None = None


class RenameStatus(StrEnum):
    """What happened to one file an asset rename was asked to move."""

    RENAMED = "renamed"
    #: Another file already holds the suggested name.
    CONFLICT = "conflict"
    ERROR = "error"


class AssetRenameResult(StrictBaseModel):
    """One asset rename result."""

    current_path: str
    suggested_path: str | None = None
    status: RenameStatus
    reason: str | None = None


class AssetRenameResponse(StrictBaseModel):
    """Asset rename response."""

    results: list[AssetRenameResult]
