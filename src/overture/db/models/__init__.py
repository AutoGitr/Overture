"""Database models package."""

lazy from .api_key import ApiKey
lazy from .art import (
    ArtSlot,
)
lazy from .auth_session import AuthSession
lazy from .catalog import (
    CatalogCollection,
    CatalogDraft,
    CatalogItem,
    CatalogItemSeason,
)
lazy from .collection_group import CollectionGroup
lazy from .collection_rule import CollectionRule
lazy from .download_job import DownloadJob
lazy from .job_result import JobLogLine, JobResult, JobRun
lazy from .library import Library
lazy from .media_collection import (
    CollectionLibrary,
    MediaCollection,
    MediaCollectionMember,
)
lazy from .media_item import MediaItem
lazy from .notification import NotificationRule
lazy from .saved_schedule import SavedSchedule
lazy from .schedule import TaskSchedule
lazy from .season import Season
lazy from .settings import (
    MAX_THEME_FORMAT_LENGTH,
    SETTINGS_ROW_ID,
    AppSettings,
    AppSettingsBase,
    get_app_settings,
)
lazy from .term import MediaItemTerm, Term

__all__ = [
    "MAX_THEME_FORMAT_LENGTH",
    "SETTINGS_ROW_ID",
    "ApiKey",
    "AppSettings",
    "AppSettingsBase",
    "ArtSlot",
    "AuthSession",
    "CatalogCollection",
    "CatalogDraft",
    "CatalogItem",
    "CatalogItemSeason",
    "CollectionGroup",
    "CollectionLibrary",
    "CollectionRule",
    "DownloadJob",
    "JobLogLine",
    "JobResult",
    "JobRun",
    "Library",
    "MediaCollection",
    "MediaCollectionMember",
    "MediaItem",
    "MediaItemTerm",
    "NotificationRule",
    "SavedSchedule",
    "Season",
    "TaskSchedule",
    "Term",
    "get_app_settings",
]
