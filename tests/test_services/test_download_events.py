"""A finished download is one container log line at a level that fits it."""

lazy import logging
lazy from typing import Any

lazy import pytest

lazy from overture.domain import ArtType, JobType
lazy from overture.jobs.kinds import DownloadStatus
lazy from overture.services.downloads.events import DownloadEventPublisher
lazy from tests.factories import DownloadJobFactory
lazy from tests.publishers import NullEventPublisher


@pytest.mark.parametrize(
    ("status", "payload", "level", "line"),
    [
        (
            DownloadStatus.COMPLETED,
            {},
            logging.INFO,
            "Download: Downloaded Alien (poster) - written to disk",
        ),
        (
            DownloadStatus.COMPLETED,
            {"unchanged": True},
            logging.DEBUG,
            (
                "Download: Adopted Alien (poster) - download is identical to the "
                "local file; nothing written"
            ),
        ),
        (
            DownloadStatus.FAILED,
            {"error": "HTTP 404"},
            logging.WARNING,
            "Download: Error Alien (poster) - download failed: HTTP 404",
        ),
        (
            DownloadStatus.CANCELLED,
            {},
            logging.INFO,
            "Download: Skipped Alien (poster) - download cancelled",
        ),
    ],
)
async def test_a_finished_download_logs_its_outcome(
    download_job_factory: DownloadJobFactory,
    caplog: pytest.LogCaptureFixture,
    status: DownloadStatus,
    payload: dict[str, Any],
    level: int,
    line: str,
) -> None:
    job = download_job_factory(job_type=JobType.ART, art_type=ArtType.POSTER)
    caplog.set_level(logging.DEBUG, logger="overture.services.downloads.events")

    await DownloadEventPublisher(NullEventPublisher()).publish(
        job, status, title="Alien", **payload
    )

    assert [(r.levelno, r.getMessage()) for r in caplog.records] == [(level, line)]


async def test_a_download_in_progress_logs_nothing(
    download_job_factory: DownloadJobFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    job = download_job_factory(job_type=JobType.ART, art_type=ArtType.POSTER)
    caplog.set_level(logging.DEBUG)

    await DownloadEventPublisher(NullEventPublisher()).publish(
        job, DownloadStatus.PROGRESS, title="Alien", percent=40
    )

    assert caplog.records == []
