"""YouTubeResolver - download and transcode YouTube audio to MP3."""

lazy import importlib.util
lazy import json
lazy import logging
lazy import math
lazy import re
lazy import shutil
lazy import sys
lazy from asyncio import sleep
lazy from collections.abc import Sequence
lazy from dataclasses import dataclass
lazy from pathlib import Path
lazy from time import monotonic
lazy from typing import Any, cast

lazy from ...schemas.themes import ThemeSearchResult
lazy from ...utils.audio import MAX_REMOTE_AUDIO_BYTES, ffprobe_duration
lazy from ...utils.errors import public_error_message
lazy from ...utils.process import PROBE_SLOTS, ProcessResult, run_process
lazy from ...utils.progress import ProgressCallback, ProgressUpdate, StepProgress
lazy from ...utils.security import sanitise_error
lazy from ...utils.temporary import operation_directory
lazy from ...utils.threads import owned_thread

logger = logging.getLogger(__name__)

# Maximum wall-clock time allowed for each subprocess stage
_INFO_TIMEOUT = 30  # seconds - just a JSON metadata fetch
_DOWNLOAD_TIMEOUT = 300  # seconds - audio download
_TRANSCODE_TIMEOUT = 120  # seconds - ffmpeg transcode

# After YouTube rate-limits a request, every request pauses: first for the
# minimum, doubling on each further rate limit up to the maximum. A successful
# request resets the next pause to the minimum.
_RATE_LIMIT_PAUSE_MIN = 60  # seconds
_RATE_LIMIT_PAUSE_MAX = 900  # seconds

#: Lowercase yt-dlp output that means YouTube is rate-limiting this address.
_RATE_LIMIT_MARKERS = (
    "http error 429",
    "too many requests",
    "this content isn't available, try again later",
    "this content is not available, try again later",
)

#: Longest yt-dlp error line kept in a failure message.
_MAX_ERROR_DETAIL = 1000

#: LAME VBR quality themes are encoded at: V2, LAME's recommended transparent
#: setting. The YouTube source is already lossy, so a higher one only adds bytes.
_MP3_VBR_QUALITY = "2"

#: EBU R128 targets a theme is levelled to when loudness normalisation is on:
#: integrated loudness (LUFS), true peak (dBTP) and loudness range (LU).
_LOUDNORM_TARGET = "I=-16:TP=-1.5:LRA=11"

#: Sample rate a levelled theme is written at. loudnorm works at 192 kHz and
#: would output that rate; YouTube's Opus audio is 48 kHz.
_LEVELLED_SAMPLE_RATE = "48000"

#: The JSON block loudnorm prints after measuring.
_LOUDNORM_JSON_RE = re.compile(r'\{[^{}]*"input_i"[^{}]*\}')

#: Marks yt-dlp's progress lines, so they stand out from its other output.
_PROGRESS_PREFIX = "[progress]"

_YTDLP_COMMAND = (
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
)

#: Programs theme downloads run, each with the flag that prints its version.
THEME_TOOLS = frozendict(
    {"deno": "--version", "ffmpeg": "-version", "ffprobe": "-version"}  # pyright: ignore[reportCallIssue] -- stale frozendict stub
)
#: Python packages theme downloads import or run.
THEME_PACKAGES = ("yt_dlp", "yt_dlp_ejs")


def theme_runtime_available() -> bool:
    """Return whether every local theme-download dependency is available."""
    return all(shutil.which(tool) for tool in THEME_TOOLS) and all(
        importlib.util.find_spec(package) for package in THEME_PACKAGES
    )


def _is_rate_limited(result: ProcessResult) -> bool:
    """Return whether a failed yt-dlp run was refused by YouTube's rate limit."""
    output = result.error_tail.lower()
    return any(marker in output for marker in _RATE_LIMIT_MARKERS)


def _failure_detail(result: ProcessResult) -> str:
    """Return the redacted last ``ERROR:`` line, else last line, of a failed run."""
    lines = [
        line.strip()
        for line in sanitise_error(result.error_tail).splitlines()
        if line.strip()
    ]
    errors = [line for line in lines if line.startswith("ERROR:")]
    explained = errors or lines
    detail = (
        explained[-1][:_MAX_ERROR_DETAIL]
        if explained
        else f"yt-dlp exited with status {result.returncode}"
    )
    if _is_rate_limited(result):
        return f"YouTube is rate limiting requests. {detail}"
    return detail


class DurationError(Exception):
    """Audio duration outside allowed range."""


class DownloadError(Exception):
    """Yt-dlp download failed."""


class TranscodeError(Exception):
    """Ffmpeg transcode failed."""


@dataclass(slots=True, frozen=True)
class ThemeAudio:
    """A downloaded theme, transcoded to MP3."""

    audio_bytes: bytes
    title: str | None
    duration: int


def _parse_search_output(stdout: bytes) -> list[ThemeSearchResult]:
    """Parse yt-dlp flat-playlist JSON output lines."""
    seen_ids: set[str] = set()
    results: list[ThemeSearchResult] = []
    for line in stdout.decode().strip().split("\n"):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        data = cast("dict[str, Any]", raw)
        video_id = data.get("id")
        if not video_id or video_id in seen_ids:
            continue
        seen_ids.add(video_id)
        results.append(
            ThemeSearchResult(
                id=video_id,
                title=data.get("title", ""),
                channel=data.get("channel", data.get("uploader", "")),
                duration=data.get("duration", 0),
                thumbnail=data.get("thumbnail"),
                url=f"https://www.youtube.com/watch?v={video_id}",
            )
        )
    return results


class YouTubeResolver:
    """Downloads audio from YouTube and transcodes it to VBR MP3."""

    def __init__(self, config_dir: Path) -> None:
        self._config_dir = config_dir
        self._paused_until = 0.0
        self._next_pause = _RATE_LIMIT_PAUSE_MIN

    async def _await_pause(self, *, wait: bool) -> None:
        """Hold a request while YouTube is rate-limiting this address.

        Raises:
            ValueError: When paused and the caller cannot *wait*.
        """
        # A request already in flight can extend the pause while this one sleeps.
        while (delay := self._paused_until - monotonic()) > 0:
            if not wait:
                raise ValueError(
                    "YouTube is rate limiting requests; "
                    f"try again in {math.ceil(delay)}s"
                )
            await sleep(delay)

    def _note_result(self, result: ProcessResult) -> None:
        """Start or lengthen the pause on a rate limit; reset it on success."""
        if result.returncode == 0:
            self._next_pause = _RATE_LIMIT_PAUSE_MIN
        elif _is_rate_limited(result):
            pause = self._next_pause
            self._paused_until = max(self._paused_until, monotonic() + pause)
            self._next_pause = min(pause * 2, _RATE_LIMIT_PAUSE_MAX)
            logger.warning("YouTube rate limit; pausing requests for %ss", pause)

    async def search(
        self,
        query: str = "",
        limit: int = 10,
        video_ids: Sequence[str] | None = None,
        *,
        wait: bool = True,
    ) -> list[ThemeSearchResult]:
        """Search YouTube for videos matching query or explicit video IDs.

        Without *wait*, a rate-limit pause fails the search instead of
        holding it, so someone waiting on the answer is told at once.

        Raises:
            ValueError: When the search fails or is paused without *wait*.
        """
        targets: list[str] = []
        cleaned_query = query.strip()
        if cleaned_query:
            targets.append(f"ytsearch{limit}:{cleaned_query}")
        if video_ids:
            for vid in video_ids:
                cleaned_vid = vid.strip()
                if cleaned_vid:
                    targets.append(f"https://www.youtube.com/watch?v={cleaned_vid}")

        if not targets:
            return []

        cmd = [
            *_YTDLP_COMMAND,
            *targets,
            "--dump-json",
            "--flat-playlist",
            "--no-download",
            "--ignore-errors",
        ]
        try:
            await self._await_pause(wait=wait)
            async with PROBE_SLOTS:
                result = await run_process(cmd, deadline=_INFO_TIMEOUT)
            self._note_result(result)
            if result.returncode != 0:
                raise ValueError(f"YouTube search failed: {_failure_detail(result)}")
            stdout = result.stdout

            return _parse_search_output(stdout)
        except (OSError, UnicodeDecodeError) as e:
            raise ValueError(f"YouTube search failed: {public_error_message(e)}") from e

    async def download_audio(
        self,
        youtube_id: str,
        min_duration: int,
        max_duration: int,
        progress_callback: ProgressCallback | None = None,
        *,
        normalize_loudness: bool,
    ) -> ThemeAudio:
        """
        Download audio from YouTube, validate duration, transcode to MP3.

        With *normalize_loudness*, the theme is levelled to
        :data:`_LOUDNORM_TARGET` on the way.

        Raises:
            DownloadError: When the audio cannot be fetched.
            DurationError: When the audio is outside the allowed range.
            TranscodeError: When the transcode fails.
        """
        progress = StepProgress(
            progress_callback or _discard_progress,
            (
                "checking",
                "downloading",
                *(("measuring",) if normalize_loudness else ()),
                "transcoding",
                "finalizing",
            ),
        )
        url = f"https://www.youtube.com/watch?v={youtube_id}"

        await progress.enter("checking")
        info = await self._video_info(url)
        duration = int(info.get("duration") or 0)
        if duration < min_duration:
            raise DurationError(
                f"Duration {duration}s is below minimum {min_duration}s"
            )
        if duration > max_duration:
            raise DurationError(f"Duration {duration}s exceeds maximum {max_duration}s")

        title = info.get("title", "")
        with operation_directory(self._config_dir) as tmp_dir:
            source = await self._download_source(url, tmp_dir, progress)
            mp3_path = await self._transcode(
                source,
                tmp_dir,
                duration,
                progress,
                youtube_id=youtube_id,
                title=title or None,
                normalize_loudness=normalize_loudness,
            )
            if (await owned_thread(mp3_path.stat)).st_size > MAX_REMOTE_AUDIO_BYTES:
                raise DownloadError("Theme output exceeds 50 MiB limit")
            actual_duration = await ffprobe_duration(mp3_path)
            if (
                actual_duration is None
                or not min_duration <= actual_duration <= max_duration
            ):
                raise DurationError("Downloaded audio has invalid duration")
            duration = round(actual_duration)
            await progress.enter("finalizing")
            return ThemeAudio(
                audio_bytes=await owned_thread(mp3_path.read_bytes),
                title=title or None,
                duration=duration,
            )

    async def _video_info(self, url: str) -> dict[str, Any]:
        """Return yt-dlp's metadata for one video.

        Raises:
            DownloadError: When the metadata cannot be fetched.
        """
        try:
            await self._await_pause(wait=True)
            async with PROBE_SLOTS:
                result = await run_process(
                    [*_YTDLP_COMMAND, "--dump-json", "--no-download", url],
                    deadline=_INFO_TIMEOUT,
                )
        except TimeoutError as exc:
            raise DownloadError("Timed out fetching video info") from exc
        self._note_result(result)
        if result.returncode != 0:
            raise DownloadError(f"Failed to get video info: {_failure_detail(result)}")
        return json.loads(result.stdout)

    async def _download_source(
        self,
        url: str,
        tmp_dir: Path,
        progress: StepProgress,
    ) -> Path:
        """Download the audio stream, reporting the progress yt-dlp prints.

        Raises:
            DownloadError: When the download fails, times out, or writes no file.
        """
        await progress.enter("downloading")

        async def on_line(line: str) -> None:
            if (fraction := _ytdlp_fraction(line)) is not None:
                await progress.report(fraction)

        try:
            await self._await_pause(wait=True)
            result = await run_process(
                [
                    *_YTDLP_COMMAND,
                    "--max-filesize",
                    str(MAX_REMOTE_AUDIO_BYTES),
                    "-x",  # extract audio
                    "--audio-format",
                    "best",
                    "--newline",  # one progress line per update
                    "--progress-template",
                    f"download:{_PROGRESS_PREFIX} %(progress._percent_str)s",
                    "-o",
                    f"{tmp_dir / 'audio'}.%(ext)s",
                    url,
                ],
                deadline=_DOWNLOAD_TIMEOUT,
                on_line=on_line,
                capture=False,
            )
        except TimeoutError as exc:
            raise DownloadError("Timed out downloading audio") from exc
        self._note_result(result)
        if result.returncode != 0:
            raise DownloadError(f"Download failed: {_failure_detail(result)}")

        def _find_audio() -> Path | None:
            for path in tmp_dir.iterdir():
                if path.stem == "audio":
                    return path
            return None

        audio_path = await owned_thread(_find_audio)
        if audio_path is not None:
            if (await owned_thread(audio_path.stat)).st_size > MAX_REMOTE_AUDIO_BYTES:
                raise DownloadError("Theme source exceeds 50 MiB limit")
            return audio_path
        raise DownloadError("Downloaded file not found")

    @staticmethod
    async def _transcode(
        source: Path,
        tmp_dir: Path,
        duration: int,
        progress: StepProgress,
        *,
        youtube_id: str | None = None,
        title: str | None = None,
        normalize_loudness: bool,
    ) -> Path:
        """Transcode to VBR MP3, reporting the progress ffmpeg prints.

        Only the first audio stream is kept, and only Overture's own tags are
        written, so the file does not depend on what the source carried.

        Raises:
            TranscodeError: When the transcode fails, times out, or writes no file.
        """
        levelling: list[str] = []
        if normalize_loudness:
            await progress.enter("measuring")
            measured = await _measure_loudness(source)
            levelling = [
                "-af",
                f"loudnorm={_LOUDNORM_TARGET}:{measured}:linear=true",
                "-ar",
                _LEVELLED_SAMPLE_RATE,
            ]
        await progress.enter("transcoding")
        mp3_path = tmp_dir / "theme.mp3"

        async def on_line(line: str) -> None:
            if (fraction := _ffmpeg_fraction(line, duration)) is not None:
                await progress.report(fraction)

        cmd = [
            "ffmpeg",
            "-y",
            "-nostats",
            "-progress",
            "pipe:1",  # machine-readable progress, one key per line
            "-i",
            str(source),
            "-map",
            "0:a:0",
            "-map_metadata",
            "-1",
            *levelling,
            "-c:a",
            "libmp3lame",
            "-q:a",
            _MP3_VBR_QUALITY,
            "-id3v2_version",
            "3",
        ]
        if title:
            cmd.extend(["-metadata", f"title={title}"])
        if youtube_id:
            cmd.extend(["-metadata", f"comment=overture:youtube_id={youtube_id}"])
        cmd.append(str(mp3_path))

        try:
            result = await run_process(
                cmd, deadline=_TRANSCODE_TIMEOUT, on_line=on_line, capture=False
            )
        except TimeoutError as exc:
            raise TranscodeError("Timed out transcoding audio") from exc
        if result.returncode != 0:
            raise TranscodeError(
                f"Transcode failed: {sanitise_error(result.error_tail)[:200]}"
            )
        mp3_exists = await owned_thread(mp3_path.is_file)
        if not mp3_exists:
            raise TranscodeError("MP3 output file not found")
        return mp3_path


async def _measure_loudness(source: Path) -> str:
    """Measure *source* against the loudnorm target; return the second pass's options.

    Raises:
        TranscodeError: When ffmpeg fails, times out, or measures no loudness.
    """
    try:
        result = await run_process(
            [
                "ffmpeg",
                "-hide_banner",
                "-nostdin",
                "-nostats",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-af",
                f"loudnorm={_LOUDNORM_TARGET}:print_format=json",
                "-f",
                "null",
                "-",
            ],
            deadline=_TRANSCODE_TIMEOUT,
        )
    except TimeoutError as exc:
        raise TranscodeError("Timed out measuring loudness") from exc
    if result.returncode != 0:
        raise TranscodeError(
            f"Loudness measurement failed: {sanitise_error(result.error_tail)[:200]}"
        )
    return _loudnorm_measurement(result.error_tail)


def _loudnorm_measurement(output: str) -> str:
    """Return the measured-value options from loudnorm's printed JSON.

    Raises:
        TranscodeError: When the output holds no finite measurement, as for
            silent audio.
    """
    blocks = _LOUDNORM_JSON_RE.findall(output)
    if not blocks:
        raise TranscodeError("Loudness measurement printed no result")
    measured = cast("dict[str, str]", json.loads(blocks[-1]))
    options = {
        "measured_I": measured.get("input_i"),
        "measured_TP": measured.get("input_tp"),
        "measured_LRA": measured.get("input_lra"),
        "measured_thresh": measured.get("input_thresh"),
        "offset": measured.get("target_offset"),
    }
    try:
        values = {name: float(value or "nan") for name, value in options.items()}
    except ValueError as exc:
        raise TranscodeError("Loudness measurement is not a number") from exc
    if not all(math.isfinite(value) for value in values.values()):
        raise TranscodeError("Audio is too quiet to measure its loudness")
    return ":".join(f"{name}={value}" for name, value in values.items())


async def _discard_progress(update: ProgressUpdate) -> None:
    """Ignore progress, for a caller that asked for none."""


def _ytdlp_fraction(line: str) -> float | None:
    """Return how far along one yt-dlp progress line is, if it is one."""
    if not line.startswith(_PROGRESS_PREFIX):
        return None
    try:
        return float(line.removeprefix(_PROGRESS_PREFIX).strip().rstrip("%")) / 100
    except ValueError:
        return None


def _ffmpeg_fraction(line: str, duration: int) -> float | None:
    """Return how far along one ffmpeg progress line is, if it is one."""
    key, _, value = line.partition("=")
    if key != "out_time_us" or not duration:
        return None
    try:
        return int(value) / (duration * 1_000_000)
    except ValueError:
        return None
