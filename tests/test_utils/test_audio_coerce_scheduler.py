"""Coverage for centralized pure utility ownership."""

lazy import asyncio
lazy import json
lazy from pathlib import Path
lazy from typing import cast

lazy import httpx2
lazy import pytest

lazy from overture.config import Settings
lazy from overture.services.scheduler import ScheduledJobInfo, SchedulerService
lazy from overture.utils import audio
lazy from overture.utils.process import ProcessResult


async def test_ffprobe_duration_reads_positive_json_duration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _Process:
        returncode = 0

        async def communicate(self):
            return b'{"format":{"duration":"12.5"}}', b""

    async def fake_subprocess(*_args: object, **_kwargs: object):
        proc = _Process()
        stdout, stderr = await proc.communicate()
        return ProcessResult(proc.returncode, stdout, stderr.decode())

    monkeypatch.setattr(audio, "run_process", fake_subprocess)

    assert await audio.ffprobe_duration(tmp_path / "theme.mp3") == 12.5


async def test_ffprobe_duration_returns_none_on_probe_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _Process:
        returncode = 1

        async def communicate(self):
            return b"", b"bad file"

    async def fake_subprocess(*_args: object, **_kwargs: object):
        proc = _Process()
        stdout, stderr = await proc.communicate()
        return ProcessResult(proc.returncode, stdout, stderr.decode())

    monkeypatch.setattr(audio, "run_process", fake_subprocess)

    assert await audio.ffprobe_duration(tmp_path / "theme.mp3") is None


@pytest.mark.parametrize(
    ("tags", "expected"),
    [
        (
            {"comment": "overture:youtube_id=dQw4w9WgXcQ"},
            ("dQw4w9WgXcQ", "embedded_id"),
        ),
        ({"youtube_id": "bMt47exzvyg"}, ("bMt47exzvyg", "embedded_id")),
        (
            {
                "purl": "https://www.youtube.com/watch?v=UuPb1J_RCJM",
                "comment": "https://www.youtube.com/watch?v=UuPb1J_RCJM",
            },
            ("UuPb1J_RCJM", "source_url"),
        ),
        (
            {
                "purl": "https://www.youtube.com/watch?v=hXVsOWrU6Ws",
                "comment": "https://www.youtube.com/watch?v=hXVsOWrU6Ws",
            },
            ("hXVsOWrU6Ws", "source_url"),
        ),
        (
            {"description": "https://youtu.be/dQw4w9WgXcQ"},
            ("dQw4w9WgXcQ", "metadata_url"),
        ),
        (
            {
                "description": "https://youtu.be/bMt47exzvyg",
                "purl": "https://youtu.be/dQw4w9WgXcQ",
            },
            ("dQw4w9WgXcQ", "source_url"),
        ),
        (
            {"youtube_id": "dQw4w9WgXcQ", "purl": "https://youtu.be/dQw4w9WgXcQ"},
            ("dQw4w9WgXcQ", "embedded_id"),
        ),
        ({"comment": "dQw4w9WgXcQ"}, None),
        ({"description": "dQw4w9WgXcQ", "pcommon": "bMt47exzvyg"}, None),
        ({"comment": "Just some random track"}, None),
        (
            {
                "comment": "overture:youtube_id=dQw4w9WgXcQ",
                "purl": "https://youtu.be/bMt47exzvyg",
            },
            None,
        ),
        ({"youtube_id": "dQw4w9WgXcQ", "overture_youtube_id": "bMt47exzvyg"}, None),
        (
            {
                "purl": "https://youtu.be/dQw4w9WgXcQ",
                "comment": "https://youtu.be/bMt47exzvyg",
            },
            None,
        ),
        (
            {"comment": "https://youtu.be/dQw4w9WgXcQ https://youtu.be/bMt47exzvyg"},
            None,
        ),
        (
            {
                "description": "https://youtu.be/dQw4w9WgXcQ https://youtu.be/bMt47exzvyg"
            },
            None,
        ),
        ({"comment": "overture:youtube_id=dQw4w9WgXcQlong"}, None),
        ({"purl": "https://youtu.be/dQw4w9WgXcQlong"}, None),
        ({"purl": "https://evil.youtube.com/watch?v=dQw4w9WgXcQ"}, None),
        ({"purl": "https://example.org/youtube.com/watch?v=dQw4w9WgXcQ"}, None),
    ],
)
def test_extract_youtube_source_from_tags(
    tags: dict[str, str],
    expected: tuple[str, str] | None,
) -> None:
    assert audio.extract_youtube_source_from_tags(tags) == expected
    assert (
        audio.extract_youtube_source_from_tags(dict(reversed(list(tags.items()))))
        == expected
    )


async def test_ffprobe_theme_metadata_parses_duration_and_tags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    class _Process:
        returncode = 0

        async def communicate(self):
            payload = {
                "format": {
                    "duration": "45.5",
                    "tags": {
                        "title": "Breaking Bad Theme",
                        "comment": "overture:youtube_id=bMt47exzvyg",
                    },
                }
            }
            return json.dumps(payload).encode(), b""

    async def fake_subprocess(*_args: object, **_kwargs: object):
        proc = _Process()
        stdout, stderr = await proc.communicate()
        return ProcessResult(proc.returncode, stdout, stderr.decode())

    monkeypatch.setattr(audio, "run_process", fake_subprocess)

    metadata = await audio.ffprobe_theme_metadata(tmp_path / "theme.mp3")
    assert metadata is not None
    assert metadata.duration == 45.5
    assert metadata.youtube_id == "bMt47exzvyg"
    assert metadata.youtube_id_source == "embedded_id"
    assert metadata.title == "Breaking Bad Theme"


async def test_downloaded_audio_yields_a_temporary_file(
    tmp_path: Path,
) -> None:
    class _Response:
        status_code = 200

        def __init__(self) -> None:
            self.headers: dict[str, str] = {}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args: object):
            return None

        def raise_for_status(self) -> None:
            return

        async def aiter_bytes(self, *, chunk_size: int):
            assert chunk_size == 64 * 1024
            yield b"au"
            yield b"dio"

    class _Client:
        def stream(self, *_args: object, **_kwargs: object):
            return _Response()

    client = cast("httpx2.AsyncClient", _Client())
    async with audio.downloaded_audio(client, "url", {}, config_dir=tmp_path) as path:
        assert await asyncio.to_thread(path.read_bytes) == b"audio"
    assert not path.exists()


@pytest.mark.parametrize(
    ("returncode", "stdout", "expected"),
    [
        (0, b"SHA256=abc123\n", "abc123"),
        (1, b"", None),
        (0, b"MD5=abc123\n", None),
    ],
)
async def test_audio_hash_reads_ffmpeg_packet_hash(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    returncode: int,
    stdout: bytes,
    expected: str | None,
) -> None:
    calls: list[list[str]] = []

    async def fake_subprocess(args: list[str], **_kwargs: object) -> ProcessResult:
        calls.append(args)
        return ProcessResult(returncode, stdout, "")

    monkeypatch.setattr(audio, "run_process", fake_subprocess)

    assert await audio.audio_hash(tmp_path / "theme.mp3") == expected
    assert calls[0][calls[0].index("-c") + 1] == "copy"
    assert calls[0][calls[0].index("-map") + 1] == "0:a"


async def test_scheduler_stop_drains_owned_callback(*, app_config: Settings) -> None:
    scheduler = SchedulerService(app_config=app_config)
    entered = asyncio.Event()

    async def callback() -> None:
        entered.set()
        await asyncio.Event().wait()

    scheduler.set_interval_job("owned", enabled=True, func=callback, minutes=1)
    scheduler.start()
    task = scheduler.trigger_job("owned")
    await entered.wait()
    await scheduler.stop()
    assert task.cancelled()
    assert not scheduler.running
    with pytest.raises(RuntimeError, match="closed"):
        scheduler.set_interval_job("late", enabled=True, func=callback, minutes=1)
    await scheduler.stop()


async def test_scheduler_reports_failed_callback_cleanup(
    *, app_config: Settings
) -> None:
    scheduler = SchedulerService(app_config=app_config)
    entered = asyncio.Event()

    async def callback() -> None:
        entered.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError as exc:
            raise RuntimeError("callback cleanup failed") from exc

    scheduler.set_interval_job("failed", enabled=True, func=callback, minutes=1)
    scheduler.start()
    task = scheduler.trigger_job("failed")
    await entered.wait()
    with pytest.raises(RuntimeError, match="Scheduled callback failed"):
        await scheduler.stop()
    assert task.done()
    assert not scheduler.running


def test_scheduler_service_replaces_removes_and_reports_jobs(
    *, app_config: Settings
) -> None:
    scheduler = SchedulerService(app_config=app_config)

    assert scheduler.set_cron_job(
        "sync",
        enabled=True,
        func=_noop,
        cron_expression="0 * * * *",
    )
    info = scheduler.job_info("sync")
    assert info.enabled is True
    assert info.next_run is not None

    assert not scheduler.set_cron_job(
        "sync",
        enabled=False,
        func=_noop,
        cron_expression="",
    )
    assert scheduler.job_info("sync") == ScheduledJobInfo(
        enabled=False,
        next_run=None,
    )


async def _noop() -> None:
    return None
