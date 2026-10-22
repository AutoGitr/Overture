"""Request model and pure router helper coverage."""

lazy from collections.abc import Sequence
lazy from pathlib import Path
lazy from typing import Any

lazy import pytest
lazy from fastapi import FastAPI
lazy from fastapi.routing import APIRoute
lazy from pydantic import ValidationError
lazy from starlette.routing import BaseRoute

lazy from overture.config import Settings
lazy from overture.db.models.media_item import MediaItem
lazy from overture.db.models.season import Season
lazy from overture.db.session import Database
lazy from overture.domain import (
    ASSETS_MATCH_THRESHOLD_DEFAULT,
    DEFAULT_ART_SOURCE_ORDER,
    DEFAULT_THEME_SOURCE_ORDER,
    MATCH_THRESHOLD_DEFAULT,
    MATCH_THRESHOLD_MAX,
    ArtBulkSource,
    ArtType,
    MediaType,
    RecentUnit,
    ThemeBulkSource,
)
lazy from overture.integrations.tmdb import TMDBClient
lazy from overture.main import health_router
lazy from overture.media_servers.registry import ProviderRegistry
lazy from overture.routers import art as art_router
lazy from overture.routers import collections as collections_router
lazy from overture.routers import library as library_router
lazy from overture.routers import media_server as media_server_router
lazy from overture.routers import settings as settings_router
lazy from overture.routers.art import SaveArtRequest
lazy from overture.routers.sync import SyncRunRequest, SyncScheduleWrite
lazy from overture.schemas.app import HealthResponse, ReadinessResponse
lazy from overture.schemas.bulk import (
    BulkAssetsArtConfig,
    BulkAssetsRequest,
    BulkAssetsThemeConfig,
    BulkMatchArtRequest,
    BulkThemeRequest,
)
lazy from overture.schemas.collections import (
    CollectionThemeStatusResponse,
    collection_read_from_provider,
    collection_theme_status_response,
)
lazy from overture.schemas.common import SaveSelectionResponse
lazy from overture.schemas.library import (
    LibrarySectionRead,
    MediaItemListResponse,
    folder_roots_response,
    media_item_read_from_model,
    season_read_from_model,
)
lazy from overture.schemas.media_server import ServerLibraryRead
lazy from overture.schemas.server_audit import (
    AuditStatus,
    FixAuditRequest,
    ServerAuditRefreshTarget,
    ServerAuditRequest,
    ServerAuditThemeDeleteTarget,
)
lazy from overture.schemas.settings import ConnectivityStatusResponse
lazy from overture.schemas.themes import (
    SearchRequest,
    SelectThemeRequest,
)
lazy from overture.services import settings as settings_service
lazy from overture.services.art.bulk_work import split_art_types
lazy from overture.services.art.targets import target_label
lazy from overture.services.server_audit.work import (
    AuditTarget,
    item_audit_work,
    item_in_selected_roots,
)
lazy from overture.services.storage.assets import AssetStorage
lazy from overture.utils.assets import season_poster_candidates
lazy from overture.utils.path import real_path
lazy from tests.factories import MediaItemFactory, SeasonFactory
lazy from tests.runtime_helpers import make_runtime


class TestRestResponseContracts:
    def test_remaining_generic_json_routes_use_explicit_response_models(self) -> None:
        libraries_route = _route_by_path(
            media_server_router.router.routes,
            "/media-server/libraries",
        )
        connectivity_route = _route_by_path(
            settings_router.router.routes,
            "/settings/connectivity",
        )

        assert libraries_route.response_model == list[ServerLibraryRead]
        assert connectivity_route.response_model is ConnectivityStatusResponse

    def test_app_level_json_routes_use_explicit_response_models(self) -> None:
        health_route = _route_by_path(health_router.routes, "/health")
        ready_route = _route_by_path(health_router.routes, "/ready")

        assert health_route.response_model is HealthResponse
        assert ready_route.response_model is ReadinessResponse

    def test_openapi_renders_without_dependency_parameters(
        self, *, test_app: FastAPI
    ) -> None:
        schema = test_app.openapi()

        leaked_parameters = [
            (path, method, parameter["name"])
            for path, operations in schema["paths"].items()
            for method, operation in operations.items()
            for parameter in operation.get("parameters", [])
            if parameter["name"]
            in {
                "db",
                "runtime",
                "art",
                "library",
                "sync",
                "audit",
                "collections",
                "themes",
                "backups",
                "dataset",
                "schedules",
                "asset_manager",
                "provider_registry",
                "tmdb",
                "events",
                "database",
                "app_config",
                "auth",
            }
        ]

        assert leaked_parameters == []

    def test_non_json_routes_are_documented_response_model_exemptions(self) -> None:
        non_json_paths = {
            "/library/items/{item_id}/provider-art",
            "/library/seasons/{season_id}/provider-art",
            "/library/seasons/{season_id}/local-image",
            "/library/items/{item_id}/local-image/{art_type}",
            "/collections/{collection_id}/image/{art_type}",
        }
        routes = [
            route
            for module in (
                media_server_router,
                settings_router,
                art_router,
                library_router,
                collections_router,
            )
            for route in module.router.routes
            if isinstance(route, APIRoute)
        ]

        missing_response_models = {
            route.path for route in routes if route.response_model is None
        }

        assert missing_response_models == non_json_paths

    def test_public_response_models_reject_unknown_fields(self) -> None:
        with pytest.raises(ValidationError):
            ServerLibraryRead.model_validate(
                {"key": "1", "title": "Movies", "type": "movie", "unknown": True}
            )

        with pytest.raises(ValidationError):
            ConnectivityStatusResponse.model_validate(
                {"media_server": True, "tmdb": True, "api_key": "secret"}
            )

    async def test_settings_connectivity_returns_the_probed_status(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        *,
        app_config: Settings,
        database: Database,
    ) -> None:
        async def fake_status(
            _provider_registry: ProviderRegistry,
            _tmdb_client: TMDBClient,
        ) -> ConnectivityStatusResponse:
            return ConnectivityStatusResponse(media_server=True, tmdb=False)

        monkeypatch.setattr(settings_service, "get_service_status", fake_status)

        runtime = make_runtime(
            config_dir=tmp_path, app_config=app_config, database=database
        )
        response = await settings_router.check_connectivity(
            runtime.provider_registry, runtime.tmdb
        )

        assert response == ConnectivityStatusResponse(media_server=True, tmdb=False)


class TestLibraryResponseMappers:
    def test_media_item_mapper_redacts_asset_urls(
        self, media_item_factory: MediaItemFactory
    ) -> None:
        read = media_item_read_from_model(
            media_item_factory(
                id=7,
                media_type=MediaType.MOVIE,
                title="Movie",
                server_item_id="plex-7",
                art={
                    "poster": {
                        "url": "https://images.test/poster.jpg?X-Plex-Token=secret"
                    },
                    "background": {"url": "https://images.test/background.jpg"},
                },
            ),
            public_dataset_complete=True,
            seasons=[],
        )

        assert read.poster_url is None
        assert read.background_url == "https://images.test/background.jpg"
        assert read.public_dataset_complete is True

    def test_media_item_mapper_flattens_every_art_slot_field(
        self, media_item_factory: MediaItemFactory
    ) -> None:
        """Art slots are flattened at the public API boundary."""
        read = media_item_read_from_model(
            media_item_factory(
                id=7,
                art={
                    "poster": {
                        "url": "https://images.test/poster.jpg",
                        "file_hash": "p-hash",
                        "phash": "p-phash",
                        "width": 600,
                        "height": 900,
                    },
                    "background": {
                        "url": "https://images.test/bg.jpg",
                        "file_hash": "b-hash",
                        "phash": "b-phash",
                        "width": 1920,
                        "height": 1080,
                    },
                },
            ),
            seasons=[],
        )

        assert read.poster_url == "https://images.test/poster.jpg"
        assert read.poster_hash == "p-hash"
        assert read.poster_phash == "p-phash"
        assert (read.poster_width, read.poster_height) == (600, 900)
        assert read.background_url == "https://images.test/bg.jpg"
        assert read.background_hash == "b-hash"
        assert read.background_phash == "b-phash"
        assert (read.background_width, read.background_height) == (1920, 1080)
        assert read.poster_status == "complete"
        assert read.art_status == "complete"

    def test_media_item_mapper_reports_empty_art_as_null(
        self, media_item_factory: MediaItemFactory
    ) -> None:
        """An item with no art rows must serialise as nulls, not raise."""
        read = media_item_read_from_model(media_item_factory(id=8), seasons=[])

        assert read.poster_url is None
        assert read.poster_hash is None
        assert read.background_width is None
        assert read.art_status == "missing"
        assert read.theme_status == "missing"

    @pytest.mark.parametrize(
        ("file_hash", "status"), [(None, "partial"), ("h", "complete")]
    )
    def test_season_mapper_reports_poster_completeness(
        self, season_factory: SeasonFactory, file_hash: str | None, status: str
    ) -> None:
        read = season_read_from_model(
            season_factory(
                id=2,
                art={
                    "season_poster": {"url": "https://x/s.jpg", "file_hash": file_hash}
                },
            ),
            files=True,
        )
        assert read.poster_status == status

    def test_library_collection_mappers_build_stable_response_models(
        self, media_item_factory: MediaItemFactory, season_factory: SeasonFactory
    ) -> None:
        item = media_item_read_from_model(
            media_item_factory(id=1, media_type=MediaType.MOVIE, title="Movie"),
            seasons=[],
        )
        season = season_read_from_model(
            season_factory(
                id=2,
                media_item_id=1,
                season_num=1,
                file_count=3,
                art={"season_poster": {"url": "https://images.test/s.jpg?token=x"}},
            ),
            files=True,
        )

        assert MediaItemListResponse(items=[item], total=1).total == 1
        assert LibrarySectionRead(id="movies", title="Movies", count=5).count == 5
        assert folder_roots_response({"movies": ["/movies"]}).shows == []
        assert season.file_count == 3
        assert season.poster_url is None


class TestCollectionResponseMappers:
    def test_collection_mapper_combines_provider_state_and_provenance(self) -> None:
        read = collection_read_from_provider(
            {
                "id": "abc",
                "title": "Collection",
                "summary": "Summary",
                "thumb_url": "provider-thumb",
                "art_url": "provider-art",
                "child_count": 3,
                "media_type": "movie",
                "server_type": "plex",
                "server_link": "https://server/collection/abc",
                "theme_id": "/themes/abc",
            },
            youtube_id="abcDEF12345",
            youtube_title="Collection Theme",
            youtube_duration=120,
            monitored=False,
        )

        assert read.thumb_url is not None
        assert read.thumb_url.startswith("/api/collections/abc/image/poster?t=")
        assert read.art_url is not None
        assert read.art_url.startswith("/api/collections/abc/image/background?t=")
        assert "provider" not in read.thumb_url + read.art_url
        # A replaced server image gets a new URL; the same one keeps its URL.
        renamed = collection_read_from_provider(
            {
                "id": "abc",
                "thumb_url": "provider-thumb-2",
                "art_url": "provider-art",
                "media_type": "movie",
                "server_type": "plex",
            },
            youtube_id=None,
            youtube_title=None,
            youtube_duration=None,
            monitored=True,
        )
        assert renamed.thumb_url != read.thumb_url
        assert renamed.art_url == read.art_url
        assert read.has_theme is True
        assert read.youtube_id == "abcDEF12345"
        assert read.youtube_title == "Collection Theme"
        assert read.youtube_duration == 120
        assert read.monitored is False

    def test_collection_theme_status_mapper_uses_reconciled_collection(self) -> None:
        read = collection_read_from_provider(
            {
                "id": "abc",
                "title": "Collection",
                "theme_id": None,
                "media_type": "movie",
                "server_type": "plex",
            },
            youtube_id=None,
            youtube_title=None,
            youtube_duration=None,
            monitored=True,
        )
        assert collection_theme_status_response(read) == (
            CollectionThemeStatusResponse(
                has_theme=False,
                youtube_id=None,
            )
        )


class TestThemeResponseMappers:
    @pytest.mark.parametrize(
        ("job_id", "created", "status"),
        [
            ("job-1", True, "enqueued"),
            ("job-1", False, "existing"),
            (None, False, "selected"),
        ],
    )
    def test_save_selection_mapper_reports_the_job_or_a_bare_selection(
        self, job_id: str | None, *, created: bool, status: str
    ) -> None:
        assert SaveSelectionResponse.of(
            job_id, created=created
        ) == SaveSelectionResponse.model_validate({"job_id": job_id, "status": status})


def _route_by_path(routes: Sequence[BaseRoute], path: str) -> APIRoute:
    """Return a route from a router route list."""
    for route in routes:
        if isinstance(route, APIRoute) and route.path == path:
            return route
    raise AssertionError(f"Missing route: {path}")


class TestArtRequestContract:
    """Which slot an art request names is settled by the route, not a body field.

    The art type and the match threshold are route parameters, so FastAPI
    rejects a bad one before any handler runs - there is no hand-written
    validator left to test.
    """

    @staticmethod
    def _parameter(
        path: str, method: str, name: str, *, test_app: FastAPI
    ) -> dict[str, Any]:
        operation = test_app.openapi()["paths"][path][method]
        return next(
            parameter
            for parameter in operation["parameters"]
            if parameter["name"] == name
        )

    def test_art_type_is_a_path_enum_of_exactly_the_known_slots(
        self, *, test_app: FastAPI
    ) -> None:
        schema = test_app.openapi()
        art_type = self._parameter(
            "/api/art/{item_id}/{art_type}", "put", "art_type", test_app=test_app
        )
        enum_name = art_type["schema"]["$ref"].rsplit("/", 1)[-1]
        declared = schema["components"]["schemas"][enum_name]["enum"]

        assert set(declared) == {art_type.value for art_type in ArtType}

    def test_match_threshold_is_bounded_by_the_route(
        self, *, test_app: FastAPI
    ) -> None:
        threshold = self._parameter(
            "/api/art/{item_id}/{art_type}/match",
            "post",
            "threshold",
            test_app=test_app,
        )

        assert threshold["schema"]["minimum"] == 0
        assert threshold["schema"]["maximum"] == MATCH_THRESHOLD_MAX
        assert threshold["schema"]["default"] == MATCH_THRESHOLD_DEFAULT

    def test_save_body_carries_only_the_picture(self) -> None:
        assert set(SaveArtRequest.model_fields) == {"url", "width", "height"}


class TestBulkRequestContract:
    def test_bulk_assets_request_shares_libraries_and_skip_settings(self) -> None:
        request = BulkAssetsRequest(
            library_ids=["1", "1", "2"],
            skip_recent_val=2,
            skip_recent_unit=RecentUnit.DAYS,
            art=BulkAssetsArtConfig(source_order=[ArtBulkSource.OVERTUREDB]),
            themes=BulkAssetsThemeConfig(source_order=[ThemeBulkSource.YOUTUBE_SEARCH]),
        )

        assert request.library_ids == ["1", "2"]
        assert request.art_request() == BulkMatchArtRequest(
            library_ids=["1", "2"],
            skip_recent_val=2,
            skip_recent_unit=RecentUnit.DAYS,
            art_types=[ArtType.POSTER, ArtType.BACKGROUND],
            source_order=[ArtBulkSource.OVERTUREDB],
            threshold=ASSETS_MATCH_THRESHOLD_DEFAULT,
        )
        assert request.theme_request() == BulkThemeRequest(
            library_ids=["1", "2"],
            skip_recent_val=2,
            skip_recent_unit=RecentUnit.DAYS,
            source_order=[ThemeBulkSource.YOUTUBE_SEARCH],
        )

    def test_bulk_assets_request_requires_a_selected_workflow(self) -> None:
        with pytest.raises(ValidationError):
            BulkAssetsRequest()

    def test_bulk_art_request_defaults_and_deduplicates_library_ids(self) -> None:
        request = BulkMatchArtRequest(library_ids=["1", "1", "2"])

        assert request.library_ids == ["1", "2"]
        assert request.art_types == ["poster", "background"]
        assert request.source_order == list(DEFAULT_ART_SOURCE_ORDER)

    def test_bulk_art_request_deduplicates_source_order(self) -> None:
        request = BulkMatchArtRequest(
            source_order=[
                ArtBulkSource.OVERTUREDB,
                ArtBulkSource.LOCAL_ART_MATCHING,
                ArtBulkSource.OVERTUREDB,
            ],
        )

        assert request.source_order == ["overturedb", "local_art_matching"]

    def test_bulk_art_request_rejects_invalid_values(self) -> None:
        invalid_cases: list[dict[str, Any]] = [
            {"art_types": ["theme"]},
            {"library_ids": [""]},
            {"library_ids": ["x" * 129]},
            {"library_ids": [str(i) for i in range(201)]},
            {"skip_recent_val": -1},
            {"skip_recent_unit": "weeks"},
            {"source_order": []},
            {"source_order": ["remote_first"]},
            {"threshold": -2},
            {"threshold": 33},
        ]
        for payload in invalid_cases:
            with pytest.raises(ValidationError):
                BulkMatchArtRequest.model_validate(payload)

    def test_bulk_theme_request_deduplicates_and_validates_library_ids(self) -> None:
        assert BulkThemeRequest(library_ids=["movies", "movies", "tv"]).library_ids == [
            "movies",
            "tv",
        ]
        assert BulkThemeRequest().source_order == list(DEFAULT_THEME_SOURCE_ORDER)
        assert BulkThemeRequest().skip_recent_val == 0
        assert BulkThemeRequest().skip_recent_unit == "hours"
        assert BulkThemeRequest(
            source_order=[
                ThemeBulkSource.OVERTUREDB,
                ThemeBulkSource.YOUTUBE_SEARCH,
                ThemeBulkSource.OVERTUREDB,
            ],
        ).source_order == ["overturedb", "youtube_search"]

        for library_ids in ([""], ["x" * 129], [str(i) for i in range(201)]):
            with pytest.raises(ValidationError):
                BulkThemeRequest(library_ids=library_ids)
        for source_order in ([], ["local_art_matching"]):
            with pytest.raises(ValidationError):
                BulkThemeRequest.model_validate({"source_order": source_order})
        for payload in ({"skip_recent_val": -1}, {"skip_recent_unit": "weeks"}):
            with pytest.raises(ValidationError):
                BulkThemeRequest.model_validate(payload)

    def test_bulk_label_helper_covers_item_and_season_scope(self) -> None:
        item = MediaItem(
            id=1,
            media_type=MediaType.SHOW,
            title="Show",
        )
        season = Season(season_num=2, media_item_id=1)

        assert target_label(item) == "Show"
        assert target_label(item, season=season) == "Show S02"

    def test_split_art_types_lists_poster_before_background(self) -> None:
        assert split_art_types(
            [ArtType.SEASON_POSTER, ArtType.BACKGROUND, ArtType.POSTER]
        ) == (
            [ArtType.POSTER, ArtType.BACKGROUND],
            [ArtType.SEASON_POSTER],
        )


class TestSyncAndThemeRequestContract:
    def test_sync_requests_validate_library_ids_and_interval(self) -> None:
        assert SyncRunRequest(library_ids=["1", "1"]).library_ids == ["1"]
        valid_config: dict[str, object] = {
            "mode": "incremental",
            "library_ids": ["1", "1"],
            "download_overturedb_art": True,
            "download_themes": "overturedb_themerrdb",
        }
        valid_schedule = {
            "name": " Hourly  poll ",
            "enabled": True,
            "cron_expression": "0 * * * *",
            "config": valid_config,
        }
        schedule = SyncScheduleWrite.model_validate(valid_schedule)
        assert schedule.name == "Hourly poll"
        assert schedule.config.library_ids == ["1"]
        assert schedule.config.download_overturedb_art is True
        assert schedule.config.download_themes == "overturedb_themerrdb"

        def with_config(**changes: object) -> dict[str, object]:
            return {**valid_schedule, "config": {**valid_config, **changes}}

        invalid_cases = [
            lambda: SyncRunRequest.model_validate({"direction": "pull"}),
            lambda: SyncRunRequest(library_ids=[""]),
            lambda: SyncRunRequest(library_ids=["x" * 129]),
            lambda: SyncRunRequest(library_ids=[str(i) for i in range(201)]),
            lambda: SyncScheduleWrite.model_validate({}),
            lambda: SyncScheduleWrite.model_validate(
                {**valid_schedule, "direction": "pull"}
            ),
            lambda: SyncScheduleWrite.model_validate({**valid_schedule, "name": " "}),
            lambda: SyncScheduleWrite.model_validate(with_config(library_ids=[""])),
            lambda: SyncScheduleWrite.model_validate(
                with_config(library_ids=["x" * 129])
            ),
            lambda: SyncScheduleWrite.model_validate(
                with_config(library_ids=[str(i) for i in range(201)])
            ),
            lambda: SyncScheduleWrite.model_validate(with_config(mode="hourly")),
            lambda: SyncScheduleWrite.model_validate(with_config(mode="full")),
        ]
        for factory in invalid_cases:
            with pytest.raises(ValidationError):
                factory()

    def test_theme_requests_validate_limit_and_youtube_id(self) -> None:
        assert SearchRequest(query="theme", limit=50).limit == 50
        assert SelectThemeRequest(youtube_id="abcDEF123_4").youtube_id == "abcDEF123_4"

        for factory in (
            lambda: SearchRequest(query="theme", limit=0),
            lambda: SearchRequest(query="theme", limit=51),
            lambda: SelectThemeRequest(youtube_id="too-short"),
            lambda: SelectThemeRequest(youtube_id="invalid!!!!"),
        ):
            with pytest.raises(ValidationError):
                factory()


class TestServerAuditContract:
    def test_server_audit_request_deduplicates_and_rejects_invalid(self) -> None:
        request = ServerAuditRequest(
            art_types=[ArtType.POSTER, ArtType.POSTER, ArtType.SEASON_POSTER]
        )

        assert request.art_types == ["poster", "season_poster"]
        for art_type in ("theme", "unsupported"):
            with pytest.raises(ValidationError):
                ServerAuditRequest.model_validate({"art_types": [art_type]})

    def test_fix_request_preserves_both_target_lists(self) -> None:
        fix = FixAuditRequest.model_validate(
            {
                "targets": [{"item_id": 1, "art_type": "poster"}],
                "themes": [{"item_id": 1, "server_item_id": "s", "theme_id": "t"}],
                "snapshot_finished_at": "finish",
            }
        )

        assert fix.targets == [
            ServerAuditRefreshTarget(item_id=1, art_type=ArtType.POSTER)
        ]
        assert fix.themes == [
            ServerAuditThemeDeleteTarget(item_id=1, server_item_id="s", theme_id="t")
        ]

    def test_fix_request_needs_a_finding(self) -> None:
        with pytest.raises(ValidationError, match="at least one finding"):
            FixAuditRequest.model_validate({"snapshot_finished_at": "finish"})

    def test_selected_root_and_target_label_helpers(self) -> None:
        item = MediaItem(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
            folder_path=str(Path("/media/movies/Movie")),
        )
        season = Season(media_item_id=1, season_num=1)

        movies, tv = (Path(real_path(root)) for root in ("/media/movies", "/media/tv"))
        assert item_in_selected_roots(item, [movies]) is True
        assert item_in_selected_roots(item, [tv]) is False
        assert (
            item_in_selected_roots(
                MediaItem(media_type=MediaType.MOVIE, title="No Folder"), [movies]
            )
            is False
        )

        assert target_label(item, season=season) == "Movie S01"
        assert target_label(item) == "Movie"

    def test_only_matching_audit_findings_need_no_fix(self) -> None:
        assert {status for status in AuditStatus if status.matched} == {
            AuditStatus.PHASH_MATCH,
            AuditStatus.THEME_MATCH,
        }

    def test_item_audit_work_lists_local_assets_in_result_order(
        self, tmp_path: Path, *, app_config: Settings
    ) -> None:
        folder = tmp_path / "Show"
        season_folder = folder / "Season 01"
        season_folder.mkdir(parents=True)
        for name in ("theme.mp3", "background.jpg", "poster.jpg"):
            (folder / name).write_bytes(b"asset")
        poster_name = season_poster_candidates(app_config.MEDIA_SERVER, 1)[0]
        (season_folder / poster_name).write_bytes(b"season")
        item = MediaItem(
            id=1, media_type=MediaType.SHOW, title="Show", folder_path=str(folder)
        )
        seasons = [
            Season(id=7, media_item_id=1, season_num=1),
            # No local poster, so no target.
            Season(id=8, media_item_id=1, season_num=2),
        ]

        # Whatever order the art types were chosen in.
        assert item_audit_work(
            item,
            [ArtType.BACKGROUND, ArtType.SEASON_POSTER, ArtType.POSTER],
            check_themes=True,
            seasons=seasons,
            asset_storage=AssetStorage(app_config=app_config),
        ) == [
            AuditTarget(1, ArtType.POSTER),
            AuditTarget(1, ArtType.BACKGROUND),
            AuditTarget(1, ArtType.SEASON_POSTER, 7),
            AuditTarget(1),
        ]

    def test_item_audit_work_includes_only_local_assets(
        self, tmp_path: Path, *, app_config: Settings
    ) -> None:
        folder = tmp_path / "Movie"
        folder.mkdir()
        (folder / "poster.jpg").write_bytes(b"poster")
        (folder / "theme.mp3").write_bytes(b"theme")
        item = MediaItem(
            id=1,
            media_type=MediaType.MOVIE,
            title="Movie",
            folder_path=str(folder),
        )

        assert item_audit_work(
            item,
            [ArtType.POSTER, ArtType.BACKGROUND],
            check_themes=True,
            seasons=[],
            asset_storage=AssetStorage(app_config=app_config),
        ) == [
            AuditTarget(1, ArtType.POSTER),
            AuditTarget(1),
        ]
