"""YouTube resolver subprocess parsing tests using fakes."""

lazy import asyncio
lazy import contextlib
lazy import json
lazy import sys
lazy from importlib.machinery import ModuleSpec
lazy from pathlib import Path
lazy from typing import Any

lazy import pytest

lazy from overture.schemas.themes import ThemeSearchResult
lazy from overture.services.themes import youtube_resolver as module
lazy from overture.services.themes.youtube_resolver import (
    DownloadError,
    DurationError,
    ThemeAudio,
    TranscodeError,
    YouTubeResolver,
)
lazy from overture.utils import progress as progress_module
lazy from overture.utils import rate_limit
lazy from overture.utils.process import ProcessResult
lazy from overture.utils.progress import ProgressUpdate
lazy from tests.pause_clock import PauseClock


@pytest.fixture(autouse=True)
def _pauses_on_a_fake_clock(pause_clock: PauseClock) -> None:
    """Keep rate-limit pauses from delaying resolver tests."""


async def test_search_parses_json_lines(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = "\n".join(
        [
            json.dumps(
                {
                    "id": "abcDEF123_4",
                    "title": "Theme",
                    "channel": "Channel",
                    "duration": 120,
                }
            ),
            "",
        ]
    ).encode()

    async def fake_exec(_args: object, **_kwargs: object) -> ProcessResult:
        return ProcessResult(0, payload, "")

    monkeypatch.setattr(module, "run_process", fake_exec)

    assert await YouTubeResolver(tmp_path).search("theme", limit=1) == [
        ThemeSearchResult(
            id="abcDEF123_4",
            title="Theme",
            channel="Channel",
            duration=120,
            url="https://www.youtube.com/watch?v=abcDEF123_4",
        )
    ]


async def test_search_uses_the_pinned_javascript_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[object, ...]] = []

    async def fake_exec(args: list[str], **_kwargs: object) -> ProcessResult:
        commands.append(tuple(args))
        return ProcessResult(0, b"", "")

    monkeypatch.setattr(module, "run_process", fake_exec)

    assert await YouTubeResolver(tmp_path).search("theme") == []
    assert commands == [
        (
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--js-runtimes",
            "deno",
            "--sleep-requests",
            "1",
            "--color",
            "never",
            "ytsearch10:theme",
            "--dump-json",
            "--flat-playlist",
            "--no-download",
            "--ignore-errors",
        )
    ]


async def test_search_with_video_ids_and_deduplication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commands: list[tuple[object, ...]] = []
    payload = "\n".join(
        [
            json.dumps(
                {
                    "id": "vid_first_1",
                    "title": "Theme 1",
                    "channel": "Channel 1",
                    "duration": 120,
                    "thumbnail": "https://img.test/1.jpg",
                }
            ),
            json.dumps(
                {
                    "id": "vid_second2",
                    "title": "Theme 2",
                    "channel": "Channel 2",
                    "duration": 180,
                    "thumbnail": "https://img.test/2.jpg",
                }
            ),
            # Duplicate returned by yt-dlp
            json.dumps(
                {
                    "id": "vid_first_1",
                    "title": "Theme 1 duplicate",
                    "channel": "Channel 1",
                    "duration": 120,
                }
            ),
        ]
    ).encode()

    async def fake_exec(args: list[str], **_kwargs: object) -> ProcessResult:
        commands.append(tuple(args))
        return ProcessResult(0, payload, "")

    monkeypatch.setattr(module, "run_process", fake_exec)

    results = await YouTubeResolver(tmp_path).search(
        "query string", limit=5, video_ids=["vid_second2"]
    )
    assert len(results) == 2
    assert [r.id for r in results] == ["vid_first_1", "vid_second2"]
    assert results[0].thumbnail == "https://img.test/1.jpg"
    assert commands == [
        (
            sys.executable,
            "-m",
            "yt_dlp",
            "--ignore-config",
            "--js-runtimes",
            "deno",
            "--sleep-requests",
            "1",
            "--color",
            "never",
            "ytsearch5:query string",
            "https://www.youtube.com/watch?v=vid_second2",
            "--dump-json",
            "--flat-playlist",
            "--no-download",
            "--ignore-errors",
        )
    ]


async def test_search_empty_when_no_query_and_no_video_ids(tmp_path: Path) -> None:
    assert await YouTubeResolver(tmp_path).search("", limit=10, video_ids=[]) == []


def test_theme_runtime_requires_all_binaries_and_ejs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def available_binary(_binary: str) -> str:
        return "/bin/tool"

    def available_module(_name: str, _package: str | None = None) -> ModuleSpec:
        return ModuleSpec("yt_dlp_ejs", loader=None)

    monkeypatch.setattr(module.shutil, "which", available_binary)
    monkeypatch.setattr(module.importlib.util, "find_spec", available_module)
    assert module.theme_runtime_available() is True

    def missing_deno(binary: str) -> str | None:
        return None if binary == "deno" else "/bin/tool"

    monkeypatch.setattr(module.shutil, "which", missing_deno)
    assert module.theme_runtime_available() is False


async def test_search_reports_subprocess_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_exec(_args: object, **_kwargs: object) -> ProcessResult:
        return ProcessResult(1, b"", "password=secret")

    monkeypatch.setattr(module, "run_process", fake_exec)

    with pytest.raises(ValueError, match="YouTube search failed"):
        await YouTubeResolver(tmp_path).search("theme")


@pytest.mark.parametrize("stage", ["search", "info", "download"])
@pytest.mark.parametrize(
    ("output", "detail"),
    [
        (
            "[youtube] Downloading webpage\n" * 30
            + "ERROR: HTTP Error 429: Too Many Requests token=secret\n"
            + "WARNING: request failed\n",
            "ERROR: HTTP Error 429: Too Many Requests token=[REDACTED]",
        ),
        ("ERROR: Video unavailable. This video is private", "This video is private"),
        ("HTTP Error 403 token=secret", "HTTP Error 403 token=[REDACTED]"),
        ("", "yt-dlp exited with status 1"),
    ],
)
async def test_youtube_failures_preserve_the_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
    output: str,
    detail: str,
) -> None:
    async def run(args: list[str], **_kwargs: object) -> ProcessResult:
        if stage == "download" and "--dump-json" in args:
            return ProcessResult(0, b'{"duration":120}', "")
        return ProcessResult(1, b"", output)

    monkeypatch.setattr(module, "run_process", run)
    resolver = YouTubeResolver(tmp_path)
    operation = (
        resolver.search("theme")
        if stage == "search"
        else resolver.download_audio("abcDEF123_4", 30, 300, normalize_loudness=False)
    )
    with pytest.raises(
        ValueError if stage == "search" else DownloadError, match=r"failed|Failed"
    ) as exc:
        await operation
    message = str(exc.value)
    assert detail in message
    assert "secret" not in message
    assert "\n" not in message
    assert "Downloading webpage" not in message
    assert not (tmp_path / ".tmp").exists()


async def test_youtube_errors_are_bounded_after_redaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run(_args: object, **_kwargs: object) -> ProcessResult:
        return ProcessResult(
            1, b"", "ERROR: token=" + "secret" * 1000 + " " + "x" * 2000
        )

    monkeypatch.setattr(module, "run_process", run)
    with pytest.raises(ValueError, match="YouTube search failed") as exc:
        await YouTubeResolver(tmp_path).search("theme")
    message = str(exc.value)
    assert message.startswith("YouTube search failed: ERROR: token=[REDACTED]")
    assert len(message) == len("YouTube search failed: ") + 1000
    assert "secret" not in message


_RATE_LIMITED = ProcessResult(1, b"", "ERROR: HTTP Error 429: Too Many Requests")
_SUCCEEDED = ProcessResult(0, b"", "")


@pytest.mark.parametrize(
    ("reason", "waits"),
    [
        ("HTTP Error 429: Too Many Requests", [60]),
        ("This content isn't available, try again later", [60]),
        ("HTTP Error 403: Forbidden", []),
        ("Video unavailable", []),
        ("Sign in to confirm you're not a bot", []),
    ],
)
async def test_only_explicit_rate_limits_pause_later_requests(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pause_clock: PauseClock,
    reason: str,
    waits: list[int],
) -> None:
    calls = 0

    async def run(_args: object, **_kwargs: object) -> ProcessResult:
        nonlocal calls
        calls += 1
        return ProcessResult(1, b"", f"ERROR: {reason}")

    monkeypatch.setattr(module, "run_process", run)
    resolver = YouTubeResolver(tmp_path)
    with pytest.raises(DownloadError) as exc:
        await resolver.download_audio("abcDEF123_4", 30, 300, normalize_loudness=False)
    assert ("YouTube is rate limiting requests" in str(exc.value)) == bool(waits)
    with pytest.raises(ValueError, match="YouTube search failed"):
        await resolver.search("theme")
    assert pause_clock.waits == waits
    assert calls == 2


async def test_repeated_rate_limits_back_off_until_a_request_succeeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pause_clock: PauseClock
) -> None:
    outcomes = iter([*[_RATE_LIMITED] * 6, _SUCCEEDED, _RATE_LIMITED, _SUCCEEDED])

    async def run(_args: object, **_kwargs: object) -> ProcessResult:
        return next(outcomes)

    monkeypatch.setattr(module, "run_process", run)
    resolver = YouTubeResolver(tmp_path)
    for _ in range(9):
        with contextlib.suppress(ValueError):
            await resolver.search("theme")
    assert pause_clock.waits == [60, 120, 240, 480, 900, 900, 60]


async def test_a_paused_search_without_wait_fails_at_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pause_clock: PauseClock
) -> None:
    outcomes = iter([_RATE_LIMITED, _SUCCEEDED])
    calls = 0

    async def run(_args: object, **_kwargs: object) -> ProcessResult:
        nonlocal calls
        calls += 1
        return next(outcomes)

    monkeypatch.setattr(module, "run_process", run)
    resolver = YouTubeResolver(tmp_path)
    with pytest.raises(ValueError, match="YouTube is rate limiting requests"):
        await resolver.search("theme")
    pause_clock.now += 30.5
    with pytest.raises(ValueError, match=r"rate limiting requests; try again in 30s"):
        await resolver.search("theme", wait=False)
    assert calls == 1
    pause_clock.now += 30
    assert await resolver.search("theme", wait=False) == []
    assert pause_clock.waits == []


async def test_an_in_flight_rate_limit_extends_a_waiting_requests_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pause_clock: PauseClock
) -> None:
    in_flight = asyncio.Event()
    release = asyncio.Event()
    calls: list[float] = []

    async def run(_args: object, **_kwargs: object) -> ProcessResult:
        calls.append(pause_clock.now)
        if len(calls) == 1:
            in_flight.set()
            await release.wait()
            return _RATE_LIMITED
        return _RATE_LIMITED if len(calls) == 2 else _SUCCEEDED

    async def limited_search() -> None:
        with pytest.raises(ValueError, match="YouTube is rate limiting requests"):
            await resolver.search("theme")

    async def sleep(delay: float) -> None:
        # The search started before the pause is refused while this one sleeps.
        release.set()
        await slow
        await pause_clock.sleep(delay)

    monkeypatch.setattr(module, "run_process", run)
    monkeypatch.setattr(rate_limit, "sleep", sleep)
    resolver = YouTubeResolver(tmp_path)
    slow = asyncio.create_task(limited_search())
    await in_flight.wait()
    await limited_search()
    assert await resolver.search("theme") == []
    # 60s for the first rate limit, then the in-flight one doubles it to 120s.
    assert calls == [100, 100, 220]
    assert pause_clock.waits == [60, 60]


async def test_download_audio_rejects_duration_below_minimum(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_exec(_args: object, **_kwargs: object) -> ProcessResult:
        return ProcessResult(
            0, json.dumps({"duration": 5, "title": "Tiny"}).encode(), ""
        )

    monkeypatch.setattr(module, "run_process", fake_exec)

    with pytest.raises(DurationError, match="below minimum"):
        await YouTubeResolver(tmp_path).download_audio(
            "abcDEF123_4",
            min_duration=30,
            max_duration=300,
            normalize_loudness=False,
        )


async def test_download_audio_turns_info_timeout_into_download_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def timeout(*_args: object, **_kwargs: object) -> ProcessResult:
        raise TimeoutError

    monkeypatch.setattr(module, "run_process", timeout)
    with pytest.raises(DownloadError, match="Timed out fetching video info"):
        await YouTubeResolver(tmp_path).download_audio(
            "abcDEF123_4", min_duration=30, max_duration=300, normalize_loudness=False
        )


LOUDNORM_OUTPUT = """[Parsed_loudnorm_0 @ 0x1]
{
	"input_i" : "-9.15",
	"input_tp" : "0.42",
	"input_lra" : "6.30",
	"input_thresh" : "-19.40",
	"output_i" : "-16.02",
	"output_tp" : "-1.50",
	"output_lra" : "5.10",
	"output_thresh" : "-26.20",
	"normalization_type" : "linear",
	"target_offset" : "0.02"
}
"""


def _fake_download(
    monkeypatch: pytest.MonkeyPatch, *, measured: str = LOUDNORM_OUTPUT
) -> list[list[str]]:
    """Fake yt-dlp, ffmpeg and ffprobe; return the ffmpeg commands run."""
    ffmpeg: list[list[str]] = []

    async def run(args: list[str], **_kwargs: object) -> ProcessResult:
        if "--dump-json" in args:
            return ProcessResult(0, b'{"duration":120,"title":"Theme"}', "")
        if args[:3] == [sys.executable, "-m", "yt_dlp"]:
            path = Path(args[args.index("-o") + 1].replace(".%(ext)s", ".webm"))
            await asyncio.to_thread(path.write_bytes, b"source audio")
            return ProcessResult(0, b"", "")
        ffmpeg.append(args)
        if "null" in args:
            return ProcessResult(0, b"", measured)
        await asyncio.to_thread(Path(args[-1]).write_bytes, b"mp3 audio")
        return ProcessResult(0, b"", "")

    async def duration(_path: Path) -> float:
        return 120

    monkeypatch.setattr(module, "run_process", run)
    monkeypatch.setattr(module, "ffprobe_duration", duration)
    return ffmpeg


async def test_download_audio_validates_output_and_preserves_metadata(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ffmpeg = _fake_download(monkeypatch)

    assert await YouTubeResolver(tmp_path).download_audio(
        "abcDEF123_4", min_duration=30, max_duration=300, normalize_loudness=False
    ) == ThemeAudio(audio_bytes=b"mp3 audio", title="Theme", duration=120)
    assert not (tmp_path / ".tmp").exists()
    [transcode] = ffmpeg
    options = transcode[transcode.index("-i") + 2 : -1]
    assert options == [
        "-map",
        "0:a:0",
        "-map_metadata",
        "-1",
        "-c:a",
        "libmp3lame",
        "-q:a",
        "2",
        "-id3v2_version",
        "3",
        "-metadata",
        "title=Theme",
        "-metadata",
        "comment=overture:youtube_id=abcDEF123_4",
    ]


async def test_download_audio_levels_loudness_in_two_passes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ffmpeg = _fake_download(monkeypatch)

    await YouTubeResolver(tmp_path).download_audio(
        "abcDEF123_4", min_duration=30, max_duration=300, normalize_loudness=True
    )

    measure, transcode = ffmpeg
    assert measure[measure.index("-af") + 1] == (
        "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json"
    )
    assert transcode[transcode.index("-af") + 1] == (
        "loudnorm=I=-16:TP=-1.5:LRA=11:measured_I=-9.15:measured_TP=0.42"
        ":measured_LRA=6.3:measured_thresh=-19.4:offset=0.02:linear=true"
    )
    assert transcode[transcode.index("-ar") + 1] == "48000"


@pytest.mark.parametrize(
    ("measured", "message"),
    [
        (LOUDNORM_OUTPUT.replace('"-9.15"', '"-inf"'), "too quiet"),
        ("no measurement", "printed no result"),
    ],
)
async def test_download_audio_refuses_a_theme_without_a_loudness(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    measured: str,
    message: str,
) -> None:
    ffmpeg = _fake_download(monkeypatch, measured=measured)

    with pytest.raises(TranscodeError, match=message):
        await YouTubeResolver(tmp_path).download_audio(
            "abcDEF123_4", min_duration=30, max_duration=300, normalize_loudness=True
        )
    assert len(ffmpeg) == 1


async def test_download_audio_reports_the_progress_its_tools_print(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _fake_download(monkeypatch)
    fake_run = module.run_process
    output = {
        "yt_dlp": [
            "[download] Destination: audio.webm",
            "[progress]  50.0%",
            "[progress] N/A",
        ],
        "ffmpeg": ["out_time_us=60000000", "out_time_us=N/A", "progress=end"],
    }

    async def run_printing(args: list[str], **kwargs: Any) -> ProcessResult:
        result = await fake_run(args, **kwargs)
        tool = "yt_dlp" if "yt_dlp" in args else "ffmpeg"
        if on_line := kwargs.get("on_line"):
            for line in output[tool]:
                await on_line(line)
        return result

    monkeypatch.setattr(module, "run_process", run_printing)
    monkeypatch.setattr(progress_module, "_MIN_INTERVAL", 0)
    reported: list[ProgressUpdate] = []

    async def record(update: ProgressUpdate) -> None:
        reported.append(update)

    await YouTubeResolver(tmp_path).download_audio(
        "abcDEF123_4",
        min_duration=30,
        max_duration=300,
        progress_callback=record,
        normalize_loudness=False,
    )

    assert reported == [
        ProgressUpdate(0, "checking", 1, 4),
        ProgressUpdate(25, "downloading", 2, 4),
        ProgressUpdate(38, "downloading", 2, 4),
        ProgressUpdate(50, "transcoding", 3, 4),
        ProgressUpdate(62, "transcoding", 3, 4),
        ProgressUpdate(75, "finalizing", 4, 4),
    ]


def _failing_download(monkeypatch: pytest.MonkeyPatch, step: str) -> None:
    """Fake a download that goes wrong at *step*."""
    _fake_download(monkeypatch)
    fake_run = module.run_process

    async def run(args: list[str], **kwargs: Any) -> ProcessResult:
        if step == "info" and "--dump-json" in args:
            return ProcessResult(1, b"", "")
        if step == "long" and "--dump-json" in args:
            return ProcessResult(0, b'{"duration":900}', "")
        if args[:3] == [sys.executable, "-m", "yt_dlp"] and "--dump-json" not in args:
            if step == "download":
                return ProcessResult(1, b"", "HTTP Error 403 token=secret")
            if step == "no file":
                return ProcessResult(0, b"", "")
        if args[0] == "ffmpeg":
            if step == "transcode":
                return ProcessResult(1, b"", "Invalid data found")
            if step == "no mp3":
                return ProcessResult(0, b"", "")
        return await fake_run(args, **kwargs)

    async def duration(_path: Path) -> float | None:
        return None if step == "output" else 120

    monkeypatch.setattr(module, "run_process", run)
    monkeypatch.setattr(module, "ffprobe_duration", duration)


@pytest.mark.parametrize(
    ("step", "error", "message"),
    [
        ("info", DownloadError, "Failed to get video info"),
        ("long", DurationError, "Duration 900s exceeds maximum 300s"),
        ("download", DownloadError, "Download failed: HTTP Error 403"),
        ("no file", DownloadError, "Downloaded file not found"),
        ("transcode", TranscodeError, "Transcode failed: Invalid data found"),
        ("no mp3", TranscodeError, "MP3 output file not found"),
        ("output", DurationError, "Downloaded audio has invalid duration"),
    ],
)
async def test_download_audio_names_the_step_that_failed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    step: str,
    error: type[Exception],
    message: str,
) -> None:
    _failing_download(monkeypatch, step)

    with pytest.raises(error, match=message) as exc_info:
        await YouTubeResolver(tmp_path).download_audio(
            "abcDEF123_4", min_duration=30, max_duration=300, normalize_loudness=False
        )

    assert "secret" not in str(exc_info.value)
    assert not (tmp_path / ".tmp").exists()


async def test_search_skips_lines_that_are_not_videos(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    video = {"id": "abcDEF123_4", "title": "Theme", "duration": 120}
    lines = ["not json", "[1, 2]", json.dumps({"title": "No id"}), json.dumps(video)]

    async def fake_exec(_args: object, **_kwargs: object) -> ProcessResult:
        return ProcessResult(0, "\n".join([*lines, json.dumps(video)]).encode(), "")

    monkeypatch.setattr(module, "run_process", fake_exec)

    results = await YouTubeResolver(tmp_path).search("theme")

    assert [result.id for result in results] == ["abcDEF123_4"]


async def test_youtube_requests_run_once_per_theme_download_worker(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    running = 0
    peak = 0
    three_running = asyncio.Event()
    release = asyncio.Event()

    async def fake_run(*_args: object, **_kwargs: object) -> ProcessResult:
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        if running == 3:
            three_running.set()
        await release.wait()
        running -= 1
        return ProcessResult(0, b"", "")

    monkeypatch.setattr(module, "run_process", fake_run)
    resolver = YouTubeResolver(tmp_path, download_workers=3)
    searches = [asyncio.create_task(resolver.search(f"theme {n}")) for n in range(5)]
    await asyncio.wait_for(three_running.wait(), timeout=5)
    for _ in range(10):
        await asyncio.sleep(0)
    assert peak == 3
    release.set()
    assert await asyncio.gather(*searches) == [[]] * 5
