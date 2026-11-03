"""Pure local asset naming, classification, and validation helpers."""

lazy import re
lazy from pathlib import Path

lazy from ..domain import ArtType

SAVED_EXTENSIONS = (".jpg", ".png")
IMAGE_EXTENSIONS = {*SAVED_EXTENSIONS, ".jpeg"}
AUDIO_EXTENSIONS = {".mp3"}
THEME_FILENAME = "theme.mp3"
ITEM_ASSET_CANDIDATES: frozendict[str, tuple[str, ...]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        ArtType.POSTER: tuple(f"poster{ext}" for ext in SAVED_EXTENSIONS),
        ArtType.BACKGROUND: tuple(f"background{ext}" for ext in SAVED_EXTENSIONS),
        "theme": (THEME_FILENAME,),
    }
)

POSTER_MAX_RATIO = 0.85
BACKGROUND_MIN_RATIO = 1.20

_SEASON_FOLDER_RE = re.compile(
    r"(?:Season\s*(?P<num>\d+)|Specials|Season\s*Specials)",
    re.IGNORECASE,
)
_SEASON_POSTER_RE = re.compile(r"Season\d{2}\.(?:jpg|jpeg|png)", re.IGNORECASE)
_SEASON_SPECIALS_RE = re.compile(
    r"season-specials-poster\.(?:jpg|jpeg|png)", re.IGNORECASE
)

_CANONICAL_ASSET_NAMES = {
    filename.lower()
    for candidates in ITEM_ASSET_CANDIDATES.values()
    for filename in candidates
}
_CANONICAL_ASSET_NAMES.update({"poster.jpeg", "background.jpeg"})


def season_poster_filename(
    provider_type: str,
    season_num: int | None,
    ext: str,
) -> str:
    """Return the canonical season-poster filename for a media server."""
    if season_num == 0:
        return f"season-specials-poster{ext}"
    if provider_type == "plex":
        return f"Season{season_num:02d}{ext}"
    return f"poster{ext}"


def season_poster_candidate_bases(provider_type: str, season_num: int) -> list[str]:
    """Return accepted season-poster stems, preferred first."""
    if season_num == 0:
        return ["season-specials-poster"]
    if provider_type in {"jellyfin", "emby"}:
        return [
            "poster",
            f"Season{season_num:02d}",
            f"season{season_num:02d}-poster",
        ]
    return [
        f"Season{season_num:02d}",
        "poster",
        f"season{season_num:02d}-poster",
    ]


def season_poster_candidates(provider_type: str, season_num: int) -> list[str]:
    """Return accepted season-poster filenames, preferred first."""
    return [
        f"{base}{ext}"
        for base in season_poster_candidate_bases(provider_type, season_num)
        for ext in SAVED_EXTENSIONS
    ]


def parse_season_num(folder_name: str) -> int | None:
    """Parse a season number from a Sonarr-style season-folder name."""
    match = _SEASON_FOLDER_RE.fullmatch(folder_name.strip())
    if not match:
        return None
    number = match.group("num")
    return 0 if number is None else int(number)


def infer_art_type(width: int, height: int) -> ArtType | None:
    """Infer poster or background from image dimensions."""
    if not width or not height:
        return None
    ratio = width / height
    if ratio <= POSTER_MAX_RATIO:
        return ArtType.POSTER
    if ratio >= BACKGROUND_MIN_RATIO:
        return ArtType.BACKGROUND
    return None


def is_safe_asset_target(path: str | Path) -> bool:
    """Return whether a path uses an accepted managed-asset filename."""
    candidate = Path(path)
    if candidate.suffix.lower() not in IMAGE_EXTENSIONS | AUDIO_EXTENSIONS:
        return False
    if candidate.name.lower() in _CANONICAL_ASSET_NAMES:
        return True
    if _SEASON_POSTER_RE.fullmatch(candidate.name):
        return True
    return bool(_SEASON_SPECIALS_RE.fullmatch(candidate.name))
