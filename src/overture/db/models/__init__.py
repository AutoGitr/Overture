"""Database models package."""

lazy from .added_preset import AddedPreset
lazy from .api_key import ApiKey
lazy from .asset import Asset, AssetDelivery
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
lazy from .media_item_copy import MediaItemCopy, SeasonCopy
lazy from .media_server import MediaServer
lazy from .notification import NotificationRule
lazy from .saved_schedule import SavedSchedule
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
    "AddedPreset",
    "ApiKey",
    "AppSettings",
    "AppSettingsBase",
    "Asset",
    "AssetDelivery",
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
    "MediaItemCopy",
    "MediaItemTerm",
    "MediaServer",
    "NotificationRule",
    "SavedSchedule",
    "Season",
    "SeasonCopy",
    "Term",
    "get_app_settings",
]
