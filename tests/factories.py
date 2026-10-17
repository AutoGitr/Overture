"""Call signatures for the model factory fixtures in :mod:`conftest`.

A fixture is injected by name, so a test that takes ``media_item_factory``
tells the type checker nothing about what it received. These protocols are
what the fixtures return, and annotating the parameter with one gives the
test the real signature - including which keyword arguments a factory takes
and which model it builds.
"""

lazy from typing import Any, Protocol

lazy from overture.db.models.download_job import DownloadJob
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.public_dataset import PublicDatasetItem
lazy from overture.db.models.schedule import TaskSchedule
lazy from overture.db.models.season import Season
lazy from overture.db.models.settings import AppSettings

#: Artwork slots declared by a factory caller, keyed by art type.
type ArtSpec = dict[str, dict[str, Any]]


class MediaItemFactory(Protocol):
    """Build a :class:`MediaItem`, optionally with artwork slots filled in."""

    def __call__(self, art: ArtSpec | None = None, **overrides: Any) -> MediaItem: ...


class SeasonFactory(Protocol):
    """Build a :class:`Season`, optionally with artwork slots filled in."""

    def __call__(self, art: ArtSpec | None = None, **overrides: Any) -> Season: ...


class AppSettingsFactory(Protocol):
    """Build an :class:`AppSettings` row."""

    def __call__(self, **overrides: Any) -> AppSettings: ...


class ScheduleFactory(Protocol):
    """Build a :class:`TaskSchedule` row."""

    def __call__(self, **overrides: Any) -> TaskSchedule: ...


class DownloadJobFactory(Protocol):
    """Build a :class:`DownloadJob` row."""

    def __call__(self, **overrides: Any) -> DownloadJob: ...


class PublicDatasetItemFactory(Protocol):
    """Build a :class:`PublicDatasetItem` row."""

    def __call__(self, **overrides: Any) -> PublicDatasetItem: ...
