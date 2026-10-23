"""Database model package exports."""

from sqlmodel import SQLModel

from .models.art import ArtSlot as ArtSlot
from .models.auth_session import AuthSession as AuthSession
from .models.download_job import DownloadJob as DownloadJob
from .models.job_result import JobLogLine as JobLogLine
from .models.job_result import JobResult as JobResult
from .models.job_result import JobRun as JobRun
from .models.media_collection import MediaCollection as MediaCollection
from .models.media_collection import MediaCollectionMember as MediaCollectionMember
from .models.media_item import MediaItem as MediaItem
from .models.public_dataset import PublicDatasetCollection as PublicDatasetCollection
from .models.public_dataset import PublicDatasetDraft as PublicDatasetDraft
from .models.public_dataset import PublicDatasetItem as PublicDatasetItem
from .models.public_dataset import PublicDatasetSeason as PublicDatasetSeason
from .models.saved_schedule import SavedSchedule as SavedSchedule
from .models.schedule import TaskSchedule as TaskSchedule
from .models.season import Season as Season
from .models.settings import AppSettings as AppSettings
from .models.settings import get_app_settings as get_app_settings

#: Schema for every table this package declares. Depend on this rather than on
#: ``SQLModel.metadata`` directly: reaching it through this module is what
#: guarantees the model imports above have run and registered their tables.
metadata = SQLModel.metadata

__all__ = [
    "AppSettings",
    "ArtSlot",
    "AuthSession",
    "DownloadJob",
    "JobLogLine",
    "JobResult",
    "JobRun",
    "MediaCollection",
    "MediaCollectionMember",
    "MediaItem",
    "PublicDatasetCollection",
    "PublicDatasetDraft",
    "PublicDatasetItem",
    "PublicDatasetSeason",
    "SavedSchedule",
    "Season",
    "TaskSchedule",
    "get_app_settings",
    "metadata",
]
