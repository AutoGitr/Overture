"""Security, HTTP hardening, image, and time helper coverage."""

lazy import ipaddress
lazy from datetime import UTC
lazy from typing import Any

lazy import pytest
lazy from starlette.requests import Request

lazy from overture.domain import ArtType, AspectRatioTolerance
lazy from overture.services.public_dataset.schema.contract import ASPECT_TOLERANCE
lazy from overture.utils.http_security import (
    CSRF_COOKIE,
    CSRF_HEADER,
    new_csrf_token,
    validate_mutating_request,
)
lazy from overture.utils.image import (
    UnsupportedImageFormatError,
    encoded_image_extension,
    is_supported_remote_image_type,
    is_valid_aspect_ratio,
    is_valid_image_format,
    normalise_content_type,
)
lazy from overture.utils.security import (
    REDACTED,
    has_sensitive_url_param,
    is_sensitive_field,
    remove_sensitive_url_params,
    sanitise_error,
    sanitise_for_output,
    strip_sensitive_url,
)
lazy from overture.utils.ssrf import is_blocked_ip
lazy from overture.utils.time import format_duration, parse_utc_datetime


def _request(
    method: str,
    path: str = "/api/art/save",
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers or [],
            "client": ("203.0.113.10", 12345),
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


class TestSecurityRedaction:
    def test_sensitive_field_detection_covers_common_secret_names(self) -> None:
        sensitive = [
            "api_key",
            "Authorization",
            "client-secret",
            "x_plex_token",
            "set-cookie",
            "jwt",
            "csrf",
        ]
        for name in sensitive:
            assert is_sensitive_field(name) is True

        assert is_sensitive_field("title") is False
        assert is_sensitive_field("monitored") is False

    def test_url_helpers_remove_credentials_and_sensitive_params(self) -> None:
        assert has_sensitive_url_param("https://example.test/a.jpg?api_key=secret")
        assert (
            strip_sensitive_url("https://example.test/a.jpg?X-Plex-Token=secret")
            is None
        )
        assert (
            strip_sensitive_url("https://example.test/a.jpg?size=w500")
            == "https://example.test/a.jpg?size=w500"
        )
        assert (
            remove_sensitive_url_params(
                "https://example.test/a.jpg?X-Plex-Token=secret&size=w500"
            )
            == "https://example.test/a.jpg?size=w500"
        )

    def test_sanitise_error_redacts_auth_headers_jwts_userinfo_and_params(self) -> None:
        jwt = "eyJaaaaaaaaaaaa.eyJbbbbbbbbbbbb.cccccccccccccccccc"
        message = (
            "authorization: Bearer secret-token "
            "url=https://user:pass@example.test/x?password=secret "
            f"jwt={jwt} "
            "plex=https://192-168-1-2.example.plex.direct:32400/library"
        )
        safe = sanitise_error(message)

        assert "secret-token" not in safe
        assert "user:pass" not in safe
        assert "password=secret" not in safe
        assert jwt not in safe
        assert "[REDACTED]" in safe
        assert "https://[REDACTED].plex.direct" in safe

    def test_sanitise_for_output_recurses_and_handles_cycles(self) -> None:
        payload: dict[str, Any] = {
            "headers": {"Authorization": "Bearer secret-token"},
            "items": ["ok", b"api_key=secret"],
            "nested": {"url": "https://example.test/x?token=secret"},
            "safe": "kept",
        }
        payload["self"] = payload

        safe = sanitise_for_output(payload)

        assert safe["headers"]["Authorization"] == REDACTED
        assert safe["items"][0] == "ok"
        assert safe["items"][1] == f"api_key={REDACTED}"
        assert safe["nested"]["url"] == f"https://example.test/x?token={REDACTED}"
        assert safe["safe"] == "kept"
        assert safe["self"] == REDACTED


class TestHttpSecurity:
    def test_new_csrf_token_is_url_safe_and_non_trivial(self) -> None:
        token = new_csrf_token()

        assert len(token) >= 32
        assert token != new_csrf_token()

    def test_safe_requests_and_login_do_not_require_csrf(self) -> None:
        assert validate_mutating_request(_request("GET")) is None
        assert (
            validate_mutating_request(_request("POST", path="/api/auth/login")) is None
        )
        assert (
            validate_mutating_request(_request("POST", path="/api/auth/logout"))
            is not None
        )

    def test_mutating_requests_require_matching_csrf_cookie_and_header(self) -> None:
        rejection = validate_mutating_request(_request("POST"))
        assert rejection is not None
        assert rejection.status_code == 403

        headers = [
            (b"cookie", f"{CSRF_COOKIE}=same-token".encode()),
            (CSRF_HEADER.lower().encode(), b"same-token"),
        ]
        assert validate_mutating_request(_request("DELETE", headers=headers)) is None


class TestSSRFAndImageHelper:
    def test_blocked_ip_classification_covers_non_public_ranges(self) -> None:
        blocked = [
            "127.0.0.1",
            "10.0.0.1",
            "172.16.0.1",
            "192.168.1.1",
            "169.254.1.1",
            "100.64.0.0",
            "100.100.100.200",
            "100.127.255.255",
            "224.0.0.1",
            "::1",
            "fc00::1",
            "fe80::1",
            "::ffff:100.100.100.200",
            "ff02::1",
        ]
        for value in blocked:
            assert is_blocked_ip(ipaddress.ip_address(value)) is True

        assert is_blocked_ip(ipaddress.ip_address("8.8.8.8")) is False
        assert is_blocked_ip(ipaddress.ip_address("2606:4700:4700::1111")) is False

    def test_aspect_ratio_tolerances_and_checks(self) -> None:
        # Strict is the catalog contract's tolerance, at its boundary.
        assert AspectRatioTolerance.STRICT.fraction == ASPECT_TOLERANCE == 0.01
        assert AspectRatioTolerance.LENIENT.fraction == 0.05
        assert AspectRatioTolerance.OFF.fraction is None

        strict = AspectRatioTolerance.STRICT
        assert is_valid_aspect_ratio(200, 300, ArtType.POSTER, strict)
        assert is_valid_aspect_ratio(1920, 1080, ArtType.BACKGROUND, strict)
        assert is_valid_aspect_ratio(1, 1, ArtType.POSTER, AspectRatioTolerance.OFF)
        assert not is_valid_aspect_ratio(1920, 1080, ArtType.POSTER, strict)
        assert not is_valid_aspect_ratio(0, 1080, ArtType.BACKGROUND, strict)
        assert is_valid_aspect_ratio(990, 1500, ArtType.POSTER, strict)
        assert not is_valid_aspect_ratio(989, 1500, ArtType.POSTER, strict)

    def test_image_format_and_content_type_helpers(self) -> None:
        assert is_valid_image_format("https://example.test/poster.JPG")
        assert is_valid_image_format("https://example.test/poster")
        assert not is_valid_image_format("https://example.test/poster.gif")
        assert is_valid_image_format("https://example.test/season.png?size=large")
        assert is_valid_image_format("https://example.test/season.jpg#preview")

        assert normalise_content_type(" Image/JPEG ; charset=binary ") == "image/jpeg"
        assert is_supported_remote_image_type("image/png")
        assert (
            is_supported_remote_image_type("image/webp", allow_generic_image=True)
            is True
        )
        assert is_supported_remote_image_type("text/html") is False

    def test_unreadable_image_bytes_are_rejected(self) -> None:
        with pytest.raises(UnsupportedImageFormatError, match="Unreadable image bytes"):
            encoded_image_extension(b"not-an-image")


class TestTimeHelper:
    @pytest.mark.parametrize(
        ("seconds", "text"),
        [
            (0.04, "0.0s"),
            (3.25, "3.2s"),
            (12.4, "12s"),
            (72, "1m 12s"),
            (3599.6, "1h 00m"),
            (7265, "2h 01m"),
        ],
    )
    def test_format_duration_is_short_and_readable(
        self, seconds: float, text: str
    ) -> None:
        assert format_duration(seconds) == text

    def test_parse_utc_datetime_returns_aware_utc_datetime(self) -> None:
        parsed = parse_utc_datetime("1970-01-01T01:00:00+01:00")

        assert parsed is not None
        assert parsed.tzinfo is UTC
        assert parsed.isoformat() == "1970-01-01T00:00:00+00:00"
