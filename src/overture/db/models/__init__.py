"""Database models package."""

lazy from .art import (
    ART_SLOT_FIELDS,
    ArtSlot,
)
lazy from .auth_session import AuthSession
lazy from .collection_theme import CollectionTheme, CollectionThemeBase
lazy from .download_job import DownloadJob, DownloadJobBase
lazy from .job_result import JobResult, JobRun
lazy from .media_item import MediaItem, MediaItemBase
lazy from .public_dataset import (
    PublicDatasetItem,
    PublicDatasetItemBase,
    PublicDatasetSeason,
    PublicDatasetSeasonBase,
)
lazy from .saved_schedule import SavedSchedule, SavedScheduleBase
lazy from .schedule import TaskSchedule, TaskScheduleBase
lazy from .season import Season, SeasonBase
lazy from .settings import (
    MAX_THEME_FORMAT_LENGTH,
    SETTINGS_ROW_ID,
    AppSettings,
    AppSettingsBase,
    get_app_settings,
)

__all__ = [
    "ART_SLOT_FIELDS",
    "MAX_THEME_FORMAT_LENGTH",
    "SETTINGS_ROW_ID",
    "AppSettings",
    "AppSettingsBase",
    "ArtSlot",
    "AuthSession",
    "CollectionTheme",
    "CollectionThemeBase",
    "DownloadJob",
    "DownloadJobBase",
    "JobResult",
    "JobRun",
    "MediaItem",
    "MediaItemBase",
    "PublicDatasetItem",
    "PublicDatasetItemBase",
    "PublicDatasetSeason",
    "PublicDatasetSeasonBase",
    "SavedSchedule",
    "SavedScheduleBase",
    "Season",
    "SeasonBase",
    "TaskSchedule",
    "TaskScheduleBase",
    "get_app_settings",
]
