"""Which files the Renamer suggests, and which it leaves alone."""

lazy from pathlib import Path

lazy import pytest

lazy from overture.config import Settings
lazy from overture.domain import MediaType, ServerAsset, ServerType
lazy from overture.schemas.asset_manager import AssetIssue
lazy from overture.services.asset_manager import scan

POSTER = (1000, 1500)
BACKGROUND = (1920, 1080)


def _scan(
    folder: Path,
    monkeypatch: pytest.MonkeyPatch,
    sizes: dict[str, tuple[int, int]],
    *,
    app_config: Settings,
    media_type: str = "show",
) -> dict[str, AssetIssue]:
    """Create *sizes* (paths under *folder*; ``(0, 0)`` is no image) and scan."""
    for name in sizes:
        path = folder / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"")

    def size(path: Path) -> tuple[int, int]:
        return sizes[path.relative_to(folder).as_posix()]

    monkeypatch.setattr(scan, "get_local_image_size", size)
    issues = scan.scan_media_folder(
        folder,
        media_type,
        list(ServerAsset),
        app_config=app_config,
    )
    return {issue.current_filename: issue for issue in issues}


def test_season_artwork_and_other_artwork_in_the_show_folder_are_left_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.MEDIA_SERVER = ServerType.PLEX

    issues = _scan(
        tmp_path,
        monkeypatch,
        {
            "Season01.jpg": POSTER,
            "season-specials-poster.jpg": POSTER,
            "season02-poster.png": POSTER,
            "banner.jpg": (758, 140),
            "clearlogo.png": (800, 310),
            "landscape.jpg": BACKGROUND,
        },
        app_config=app_config,
    )

    assert issues == {}


def test_one_file_is_suggested_per_slot_and_the_rest_conflict_with_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    issues = _scan(
        tmp_path,
        monkeypatch,
        {"IMG_0001.jpg": (3840, 2160), "fanart.jpg": BACKGROUND},
        app_config=app_config,
    )

    # A file named for the slot beats a larger one only its shape suggests.
    assert issues["fanart.jpg"].conflict is False
    assert issues["fanart.jpg"].potential_false_positive is False
    assert issues["IMG_0001.jpg"].conflict is True
    assert issues["IMG_0001.jpg"].conflict_with == "fanart.jpg"
    assert issues["IMG_0001.jpg"].potential_false_positive is True


def test_a_slot_held_in_another_image_format_conflicts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    issues = _scan(
        tmp_path,
        monkeypatch,
        {"poster.png": POSTER, "cover.jpg": POSTER},
        app_config=app_config,
        media_type=MediaType.MOVIE,
    )

    assert list(issues) == ["cover.jpg"]
    assert issues["cover.jpg"].suggested_filename == "poster.jpg"
    assert issues["cover.jpg"].conflict_with == "poster.png"


def test_names_differing_only_in_case_are_suggested_under_their_exact_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    issues = _scan(
        tmp_path,
        monkeypatch,
        {"Poster.JPG": POSTER, "Theme.MP3": (0, 0), "track01.mp3": (0, 0)},
        app_config=app_config,
        media_type=MediaType.MOVIE,
    )

    assert issues["Poster.JPG"].suggested_filename == "poster.jpg"
    assert issues["Poster.JPG"].conflict is False
    assert issues["Theme.MP3"].suggested_filename == "theme.mp3"
    assert issues["Theme.MP3"].conflict is False
    assert issues["track01.mp3"].conflict_with == "Theme.MP3"
    assert issues["track01.mp3"].potential_false_positive is True


@pytest.mark.parametrize(
    ("server", "files", "suggested", "conflicting"),
    [
        # The canonical name in the wrong case wins; JPEG files count too.
        ("plex", {"Season01.JPG", "folder.jpeg"}, "Season01.jpg", "folder.jpeg"),
        # Jellyfin also reads Season01.jpg, so the slot is already held.
        ("jellyfin", {"Season01.jpg", "cover.jpg"}, None, "cover.jpg"),
    ],
)
def test_season_folders_follow_the_names_overture_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    server: str,
    files: set[str],
    suggested: str | None,
    conflicting: str,
    *,
    app_config: Settings,
) -> None:
    app_config.MEDIA_SERVER = ServerType(server)

    issues = _scan(
        tmp_path,
        monkeypatch,
        {f"Season 01/{name}": POSTER for name in files},
        app_config=app_config,
    )
    season_issues = {
        name: issue for name, issue in issues.items() if issue.type == "season_poster"
    }

    assert season_issues[conflicting].conflict is True
    chosen = [issue for issue in season_issues.values() if not issue.conflict]
    assert [issue.suggested_filename for issue in chosen] == (
        [suggested] if suggested else []
    )


def test_a_folder_lists_poster_background_season_posters_then_theme(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    issues = _scan(
        tmp_path,
        monkeypatch,
        {
            # Names that sort in the opposite order of the listing.
            "a-song.mp3": (0, 0),
            "b-fanart.jpg": BACKGROUND,
            "c-cover.jpg": POSTER,
            "Season 01/cover.jpg": POSTER,
        },
        app_config=app_config,
    )

    assert [issue.type for issue in issues.values()] == [
        "poster",
        "background",
        "season_poster",
        "theme",
    ]
