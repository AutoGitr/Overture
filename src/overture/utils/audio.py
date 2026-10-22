"""Reusable audio duration inspection helpers."""

lazy import json
lazy import logging
lazy import re
lazy from collections.abc import AsyncGenerator
lazy from contextlib import asynccontextmanager
lazy from dataclasses import dataclass
lazy from pathlib import Path
lazy from typing import Any, cast

lazy import httpx2

lazy from ..domain import ThemeIdSource
lazy from ..services.public_dataset.schema.contract import YOUTUBE_ID_PATTERN
lazy from .process import PROBE_SLOTS, run_process
lazy from .temporary import operation_directory
lazy from .threads import owned_thread

logger = logging.getLogger(__name__)

FFPROBE_TIMEOUT_SECONDS = 20
MAX_REMOTE_AUDIO_BYTES = 50 * 1024 * 1024

#: A YouTube ID inside longer text: the contract's pattern without its anchors.
_EMBEDDED_ID = (
    rf"(?P<id>{YOUTUBE_ID_PATTERN.pattern.removeprefix('^').removesuffix('$')})"
    r"(?![a-zA-Z0-9_-])"
)
_OVERTURE_YOUTUBE_RE = re.compile(
    rf"\boverture:youtube_id={_EMBEDDED_ID}", re.IGNORECASE
)
_YOUTUBE_URL_RE = re.compile(
    r"(?<![\w./@:-])(?:https?://)?(?:www\.)?"
    rf"(?:youtube\.com/watch\?v=|youtu\.be/){_EMBEDDED_ID}",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ThemeAudioMetadata:
    """Metadata extracted from a theme audio file."""

    duration: float | None = None
    youtube_id: str | None = None
    youtube_id_source: ThemeIdSource | None = None
    title: str | None = None


def extract_youtube_source_from_tags(
    tags: dict[str, str],
) -> tuple[str, ThemeIdSource] | None:
    """Recover an unambiguous ID, preferring source tags over incidental URLs."""
    explicit_ids = {
        match.group("id")
        for value in tags.values()
        for match in _OVERTURE_YOUTUBE_RE.finditer(value)
    }
    explicit_ids.update(
        value.strip()
        for key in ("youtube_id", "overture_youtube_id")
        if (value := tags.get(key)) and YOUTUBE_ID_PATTERN.fullmatch(value.strip())
    )
    source_ids = {
        match.group("id")
        for key in ("purl", "comment", "pcommon")
        for match in _YOUTUBE_URL_RE.finditer(tags.get(key, ""))
    }
    candidates = explicit_ids | source_ids
    if candidates:
        if len(candidates) != 1:
            return None
        source = ThemeIdSource.EMBEDDED_ID if explicit_ids else ThemeIdSource.SOURCE_URL
        return next(iter(candidates)), source

    candidates = {
        match.group("id")
        for value in tags.values()
        for match in _YOUTUBE_URL_RE.finditer(value)
    }
    if len(candidates) == 1:
        return next(iter(candidates)), ThemeIdSource.METADATA_URL
    return None


async def ffprobe_theme_metadata(path: Path) -> ThemeAudioMetadata | None:
    """Read audio duration and metadata tags with ffprobe."""
    try:
        async with PROBE_SLOTS:
            result = await run_process(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-show_entries",
                    "format=duration:format_tags",
                    "-of",
                    "json",
                    str(path),
                ],
                deadline=FFPROBE_TIMEOUT_SECONDS,
            )
        if result.returncode != 0:
            return None
        stdout = result.stdout
        payload = json.loads(stdout.decode() or "{}")
        format_dict = payload.get("format", {})
        raw_duration = float(format_dict.get("duration") or 0)
        duration = raw_duration if raw_duration > 0 else None
        raw_tags = format_dict.get("tags")
        tags: dict[str, str] = {}
        if isinstance(raw_tags, dict):
            typed_tags = cast("dict[object, object]", raw_tags)
            tags = {
                str(k).lower(): str(v) for k, v in typed_tags.items() if v is not None
            }
        youtube_source = extract_youtube_source_from_tags(tags)
        title = tags.get("title")
        return ThemeAudioMetadata(
            duration=duration,
            youtube_id=youtube_source[0] if youtube_source else None,
            youtube_id_source=youtube_source[1] if youtube_source else None,
            title=title,
        )
    except (
        TimeoutError,
        json.JSONDecodeError,
        UnicodeDecodeError,
        OSError,
        ValueError,
    ) as exc:
        logger.debug("ffprobe could not read the metadata: %s", exc)
        return None


async def ffprobe_duration(path: Path) -> float | None:
    """Read audio duration with ffprobe."""
    metadata = await ffprobe_theme_metadata(path)
    return metadata.duration if metadata else None


async def audio_hash(path: Path) -> str | None:
    """Hash the audio packets of *path* with ffmpeg, without decoding them.

    Tags and other container metadata are left out, so a retagged copy of the
    same audio hashes equal while different audio of the same length does not.
    The result depends on the ffmpeg build, so compare it only within a run.
    """
    try:
        async with PROBE_SLOTS:
            result = await run_process(
                [
                    "ffmpeg",
                    "-v",
                    "error",
                    "-nostdin",
                    "-i",
                    str(path),
                    "-map",
                    "0:a",
                    "-c",
                    "copy",
                    "-f",
                    "hash",
                    "-hash",
                    "sha256",
                    "-",
                ],
                deadline=FFPROBE_TIMEOUT_SECONDS,
            )
    except (TimeoutError, OSError, ValueError) as exc:
        logger.debug("ffmpeg could not hash the audio: %s", exc)
        return None
    algorithm, _, digest = result.stdout.decode(errors="replace").strip().partition("=")
    if result.returncode != 0 or algorithm != "SHA256" or not digest:
        return None
    return digest


@asynccontextmanager
async def downloaded_audio(
    client: httpx2.AsyncClient,
    url: str,
    headers: dict[str, Any],
    *,
    config_dir: Path,
) -> AsyncGenerator[Path]:
    """Download audio to a temporary file and yield it; it is removed on exit.

    Raises:
        httpx2.HTTPError: The download failed.
        ValueError: The audio is larger than ``MAX_REMOTE_AUDIO_BYTES``.
        OSError: The temporary file could not be written.
    """
    with operation_directory(config_dir) as tmp:
        path = tmp / "theme.mp3"
        total = 0
        with path.open("wb") as stream:
            async with client.stream("GET", url, headers=headers) as response:
                response.raise_for_status()
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_REMOTE_AUDIO_BYTES:
                    raise ValueError("Remote audio exceeds 50 MiB limit")
                async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                    total += len(chunk)
                    if total > MAX_REMOTE_AUDIO_BYTES:
                        raise ValueError("Remote audio exceeds 50 MiB limit")
                    await owned_thread(stream.write, chunk)
        yield path
