"""Filesystem asset storage and asset-renamer helper coverage."""

lazy import tempfile
lazy from pathlib import Path
lazy from unittest.mock import patch

lazy import pytest

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.domain import ArtType, MediaType, ServerAsset, ServerType
lazy from overture.services.asset_manager import scan
lazy from overture.services.storage.assets import (
    AssetStorage,
    PathTraversalError,
    TargetDirectoryMissingError,
)
lazy from overture.utils.assets import (
    infer_art_type,
    is_safe_asset_target,
    parse_season_num,
    season_poster_filename,
)
lazy from overture.utils.path import is_within_roots


class TestAssetStoragePath:
    @pytest.fixture(autouse=True)
    def _storage(self, app_config: Settings) -> None:
        self.storage = AssetStorage(app_config=app_config)

    def test_resolves_item_art_paths(self) -> None:
        folder = "/media/Movie"

        assert self.storage.resolve_art_path(folder, ArtType.POSTER, ".png") == str(
            Path(folder) / "poster.png"
        )
        assert self.storage.resolve_art_path(folder, ArtType.BACKGROUND) == str(
            Path(folder) / "background.jpg"
        )

    def test_resolves_theme_path(self) -> None:
        folder = "/media/Movie"

        assert self.storage.resolve_theme_path(folder) == str(
            Path(folder) / "theme.mp3"
        )

    def test_resolves_server_specific_season_paths(
        self, *, app_config: Settings
    ) -> None:
        app_config.MEDIA_SERVER = ServerType.PLEX
        assert self.storage.resolve_art_path(
            "/media/Show",
            ArtType.SEASON_POSTER,
            ".jpg",
            season_folder_path="/media/Show/Season 01",
            season_num=1,
        ) == str(Path("/media/Show/Season 01") / "Season01.jpg")

        app_config.MEDIA_SERVER = ServerType.JELLYFIN
        assert self.storage.resolve_art_path(
            "/media/Show",
            ArtType.SEASON_POSTER,
            ".jpg",
            season_folder_path="/media/Show/Season 01",
            season_num=1,
        ) == str(Path("/media/Show/Season 01") / "poster.jpg")

    @pytest.mark.parametrize("media_server", ["jellyfin", "emby"])
    def test_season_art_requires_a_separate_season_folder(
        self, media_server: str, *, app_config: Settings
    ) -> None:
        app_config.MEDIA_SERVER = ServerType(media_server)
        with tempfile.TemporaryDirectory() as tmp:
            for season_folder in (None, tmp):
                with pytest.raises(TargetDirectoryMissingError, match="Season folder"):
                    self.storage.resolve_art_path(
                        tmp,
                        ArtType.SEASON_POSTER,
                        season_num=1,
                        season_folder_path=season_folder,
                    )

    def test_plex_season_art_round_trips_in_the_show_root(
        self, *, app_config: Settings
    ) -> None:
        app_config.MEDIA_SERVER = ServerType.PLEX
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "poster.jpg").write_bytes(b"show poster")
            item = MediaItem(
                id=1, title="Show", media_type=MediaType.SHOW, folder_path=tmp
            )
            season = Season(media_item_id=1, season_num=1)

            assert (
                self.storage.find_local_art_path(
                    ArtType.SEASON_POSTER, item=item, season=season
                )
                is None
            )

            target = self.storage.resolve_art_path(
                tmp, ArtType.SEASON_POSTER, season_num=1
            )
            self.storage.write_file(target, b"season poster", tmp)

            assert (
                self.storage.find_local_art_path(
                    ArtType.SEASON_POSTER, item=item, season=season
                )
                == root / "Season01.jpg"
            )
            assert (root / "poster.jpg").read_bytes() == b"show poster"

    def test_probe_season_folder_prefers_common_sonarr_names(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Season 01").mkdir()
            (root / "Specials").mkdir()

            assert self.storage.probe_season_folder(str(root), 1) == str(
                root / "Season 01"
            )
            assert self.storage.probe_season_folder(str(root), 0) == str(
                root / "Specials"
            )
            assert self.storage.probe_season_folder(str(root), 2) is None

    def test_write_file_requires_existing_parent_and_returns_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "poster.jpg"
            stored = self.storage.write_file(str(target), b"image-bytes", tmp)

            assert target.is_file()
            assert len(stored.file_hash) == 64
            assert stored.size == len(b"image-bytes")
            assert stored.mtime_ns == target.stat().st_mtime_ns
            assert self.storage.stored_file(target) == stored
            assert self.storage.identical_file(str(target), stored.file_hash) == stored
            assert self.storage.identical_file(str(target), "0" * 64) is None

            with pytest.raises(TargetDirectoryMissingError):
                self.storage.write_file(
                    str(Path(tmp) / "missing" / "poster.jpg"), b"x", tmp
                )

    def test_write_file_leaves_one_file_per_art_slot(self) -> None:
        # Choosing a PNG where a JPEG was saved writes a different filename, so
        # without this both survive and readback - which probes candidates in a
        # fixed order - can hand back the replaced image.
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "poster.jpg").write_bytes(b"old")
            (folder / "background.jpg").write_bytes(b"other slot")

            self.storage.write_file(str(folder / "poster.png"), b"new", tmp)

            assert not (folder / "poster.jpg").exists()
            assert (folder / "poster.png").read_bytes() == b"new"
            assert (folder / "background.jpg").is_file()

    def test_write_file_keeps_non_image_slots_intact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "theme.jpg").write_bytes(b"unrelated")

            self.storage.write_file(str(folder / "theme.mp3"), b"audio", tmp)

            assert (folder / "theme.jpg").is_file()

    @pytest.mark.parametrize(
        "operation",
        [
            "overture.services.storage.assets.os.replace",
            "pathlib.Path.chmod",
            "overture.services.storage.assets.os.fsync",
        ],
    )
    def test_write_file_preserves_existing_file_when_precommit_fails(
        self, operation: str
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "poster.jpg"
            target.write_bytes(b"old")

            with (
                patch(operation, side_effect=OSError("write failed")),
                pytest.raises(OSError, match="write failed"),
            ):
                self.storage.write_file(str(target), b"new", tmp)

            assert target.read_bytes() == b"old"
            assert list(Path(tmp).glob(".poster.jpg.*.tmp")) == []

    def test_write_file_reports_an_alternate_image_cleanup_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "poster.jpg").write_bytes(b"old")
            target = root / "poster.png"

            with (
                patch.object(
                    Path, "unlink", side_effect=PermissionError("cleanup blocked")
                ),
                pytest.raises(PermissionError, match="cleanup blocked"),
            ):
                self.storage.write_file(str(target), b"new", tmp)

            assert target.read_bytes() == b"new"
            assert (root / "poster.jpg").read_bytes() == b"old"

    def test_write_file_rejects_an_untrusted_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "media"
            outside = Path(tmp) / "outside"
            root.mkdir()
            outside.mkdir()

            with pytest.raises(PathTraversalError):
                self.storage.write_file(
                    str(outside / "poster.jpg"), b"image", str(root)
                )


class TestMediaRootAndAssetSafety:
    def test_is_within_roots_allows_root_and_nested_paths_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve() / "library"
            nested = root / "Movie" / "poster.jpg"
            sibling = Path(tmp) / "library-extra" / "poster.jpg"

            assert is_within_roots(root, [root]) is True
            assert is_within_roots(nested, [root]) is True
            assert is_within_roots(sibling, [root]) is False

    def test_safe_asset_target_accepts_only_managed_names(self) -> None:
        accepted = [
            "/media/Movie/poster.jpg",
            "/media/Movie/background.png",
            "/media/Movie/theme.mp3",
            "/media/Show/Season 01/Season01.jpg",
            "/media/Show/Specials/season-specials-poster.png",
        ]
        rejected = [
            "/media/Movie/random.jpg",
            "/media/Movie/logo.png",
            "/media/Movie/poster.gif",
            "/media/Movie/theme.wav",
            "/media/Show/Season 01/Episode-thumb.jpg",
        ]

        for path in accepted:
            assert is_safe_asset_target(path) is True
        for path in rejected:
            assert is_safe_asset_target(path) is False


class TestAssetManagerHelper:
    def test_ratio_and_filename_helpers(self) -> None:
        assert infer_art_type(1000, 1500) == "poster"
        assert infer_art_type(1920, 1080) == "background"
        assert infer_art_type(1000, 1000) is None
        assert infer_art_type(0, 1000) is None

        assert parse_season_num("Season 01") == 1
        assert parse_season_num("Season1") == 1
        assert parse_season_num("Specials") == 0
        assert parse_season_num("Extras") is None

        assert season_poster_filename("plex", 1, ".jpg") == "Season01.jpg"
        assert season_poster_filename("jellyfin", 1, ".jpg") == "poster.jpg"
        assert season_poster_filename("emby", 1, ".jpg") == "poster.jpg"
        assert (
            season_poster_filename("jellyfin", 0, ".png")
            == "season-specials-poster.png"
        )

    def test_scan_media_folder_reports_expected_renames(
        self, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
    ) -> None:
        app_config.MEDIA_SERVER = ServerType.PLEX
        with tempfile.TemporaryDirectory() as tmp:
            show = Path(tmp) / "Show"
            season = show / "Season 01"
            season.mkdir(parents=True)

            (show / "cover.jpg").write_bytes(b"")
            (show / "fanart.jpg").write_bytes(b"")
            (show / "song.mp3").write_bytes(b"")
            (season / "season-cover.jpg").write_bytes(b"")

            def fake_size(path: Path) -> tuple[int, int]:
                if path.name in {"cover.jpg", "season-cover.jpg"}:
                    return 1000, 1500
                if path.name == "fanart.jpg":
                    return 1920, 1080
                return 900, 300

            monkeypatch.setattr(scan, "get_local_image_size", fake_size)
            issues = list(
                scan.scan_media_folder(
                    show,
                    "show",
                    list(ServerAsset),
                    app_config=app_config,
                )
            )

        by_type = {issue.type: issue for issue in issues}
        assert by_type[ServerAsset.POSTER].suggested_filename == "poster.jpg"
        assert by_type[ServerAsset.BACKGROUND].suggested_filename == "background.jpg"
        assert by_type[ServerAsset.THEME].suggested_filename == "theme.mp3"
        assert by_type[ServerAsset.SEASON_POSTER].suggested_filename == "Season01.jpg"

    def test_scan_work_builder_expands_existing_child_directories_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            a_movies = root / "A Movies"
            z_movies = root / "Z Movies"
            a_shows = root / "A Shows"
            z_shows = root / "Z Shows"
            for folder in (a_movies, z_movies, a_shows, z_shows):
                folder.mkdir()
            (a_movies / "Alien").mkdir()
            (z_movies / "Zodiac").mkdir()
            (a_shows / "Atlanta").mkdir()
            (z_shows / "Twin Peaks").mkdir()
            (a_movies / "not-a-folder.txt").write_text("skip")

            count = scan.build_scan_work(
                [str(z_movies), str(root / "missing"), str(a_movies)],
                [str(z_shows), str(a_shows)],
                root / "scan.sqlite",
            )
            assert count == 4
            work = scan.scan_work_batch(root / "scan.sqlite", 0)

        assert work == [
            (a_movies / "Alien", "movie"),
            (z_movies / "Zodiac", "movie"),
            (a_shows / "Atlanta", "show"),
            (z_shows / "Twin Peaks", "show"),
        ]
