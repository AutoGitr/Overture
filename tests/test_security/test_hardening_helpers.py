"""Unit coverage for production-hardening helper behavior.

These tests are intentionally focused on pure helper behavior so they can run
without a live media server, database, or frontend build.
"""

lazy from ipaddress import ip_network

lazy import pytest
lazy from pydantic import ValidationError

lazy from overture.config import Settings, normalise_origin
lazy from overture.schemas.asset_manager import ScanRequest
lazy from overture.schemas.bulk import BulkMatchArtRequest
lazy from overture.schemas.server_audit import ServerAuditRequest
lazy from overture.utils.assets import is_safe_asset_target
lazy from overture.utils.path import is_within_roots, real_path
lazy from overture.utils.security import (
    Redactor,
    sanitise_error,
    sanitise_for_output,
)


class TestOriginNormalisation:
    def test_strips_path_query_and_fragment(self) -> None:
        assert (
            normalise_origin("https://Example.test/app?x=1#frag")
            == "https://example.test"
        )

    def test_empty_on_relative_url(self) -> None:
        assert normalise_origin("/just/a/path") == ""

    def test_preserves_non_standard_port(self) -> None:
        assert (
            normalise_origin("http://192.168.1.100:5885/")
            == "http://192.168.1.100:5885"
        )


class TestAppUrlSettings:
    """Verify that browser origin and proxy trust remain independent."""

    def test_no_app_url_uses_insecure_cookies(self, *, app_config: Settings) -> None:
        app_config.APP_URL = ""
        assert app_config.secure_cookies is False

    def test_http_app_url_uses_insecure_cookies(self, *, app_config: Settings) -> None:
        app_config.APP_URL = "http://192.168.1.100:5885"
        assert app_config.secure_cookies is False

    def test_https_app_url_uses_secure_cookies_without_trusting_clients(
        self, *, app_config: Settings
    ) -> None:
        app_config.APP_URL = "https://overture.example.com"
        assert app_config.secure_cookies is True
        assert app_config.is_trusted_proxy("192.0.2.1") is False

    def test_proxy_trust_requires_an_explicit_network(
        self, *, app_config: Settings
    ) -> None:
        app_config.TRUSTED_PROXY_CIDRS = (ip_network("10.0.0.0/8"),)
        assert app_config.is_trusted_proxy("10.1.2.3") is True
        assert app_config.is_trusted_proxy("192.0.2.1") is False


class TestMediaRoot:
    def test_rejects_prefix_siblings(self) -> None:
        assert (
            is_within_roots(
                "/media/movies-extra/poster.jpg", [real_path("/media/movies")]
            )
            is False
        )

    def test_accepts_nested_assets(self) -> None:
        assert (
            is_within_roots(
                "/media/movies/Example/poster.jpg", [real_path("/media/movies")]
            )
            is True
        )

    def test_asset_target_allows_only_canonical_names(self) -> None:
        assert is_safe_asset_target("/media/movies/Example/poster.jpg") is True
        assert is_safe_asset_target("/media/tv/Show/Season 01/Season01.png") is True
        assert (
            is_safe_asset_target("/media/tv/Show/Specials/season-specials-poster.jpg")
            is True
        )
        assert is_safe_asset_target("/media/movies/Example/random.jpg") is False
        assert (
            is_safe_asset_target("/media/tv/Show/Season 01/Episode-thumb.jpg") is False
        )
        assert is_safe_asset_target("/media/movies/Example/poster.gif") is False


class TestRedaction:
    def test_redacts_configured_secret_values(self, *, app_config: Settings) -> None:
        secret = app_config.MEDIA_SERVER_API_KEY.get_secret_value()
        redactor = Redactor([secret])
        assert secret not in redactor.text(f"failed with token {secret}")

    def test_redacts_credential_url_parameters(self) -> None:
        assert (
            sanitise_error("GET /library?X-Plex-Token=secret-value&ok=1")
            == "GET /library?X-Plex-Token=[REDACTED]&ok=1"
        )

    def test_redacts_plex_direct_urls(self) -> None:
        url = "https://192-168-50-60.example.plex.direct:32400/library/metadata/1"
        assert (
            sanitise_error(f"Selected secure Plex URL {url}")
            == "Selected secure Plex URL https://[REDACTED].plex.direct"
        )

    def test_redacts_sensitive_mapping_values_by_key(self) -> None:
        payload = sanitise_for_output(
            {
                "headers": {
                    "Authorization": "Bearer not-a-real-token",
                    "X-Plex-Token": "not-a-real-token",
                },
                "safe": "kept",
            }
        )
        assert payload["headers"]["Authorization"] == "[REDACTED]"
        assert payload["headers"]["X-Plex-Token"] == "[REDACTED]"
        assert payload["safe"] == "kept"


class TestRequestValidation:
    def test_bulk_art_source_order_defaults_to_overturedb_then_local(self) -> None:
        req = BulkMatchArtRequest()
        assert req.source_order == ["overturedb", "local_art_matching"]

    def test_server_audit_rejects_theme_art_type(self) -> None:
        with pytest.raises(ValidationError):
            ServerAuditRequest.model_validate({"art_types": ["poster", "theme"]})

    def test_asset_scan_accepts_all_local_art_types(self) -> None:
        req = ScanRequest.model_validate(
            {"art_types": ["poster", "background", "season_poster", "theme"]}
        )
        assert req.art_types == [
            "poster",
            "background",
            "season_poster",
            "theme",
        ]

    def test_asset_scan_rejects_unsupported_art_types(self) -> None:
        with pytest.raises(ValidationError):
            ScanRequest.model_validate({"art_types": ["unsupported"]})
