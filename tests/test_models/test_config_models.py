"""Configuration and model serialization coverage."""

lazy from ipaddress import ip_address, ip_network
lazy from typing import Any

lazy import pytest
lazy from pydantic import ValidationError

lazy from overture.config import Settings
lazy from overture.db.models.schedule import TaskSchedule
lazy from overture.db.models.settings import (
    SETTINGS_ROW_ID,
    AppSettings,
    AppSettingsBase,
)
lazy from overture.domain import AspectRatioTolerance, ServerType, Workflow
lazy from overture.schemas.settings import AppSettingsRead, AppSettingsUpdate

ARGON2_HASH = (
    "$argon2id$v=19$m=19456,t=2,p=1$Y96qqNb5fWisYsjxPJH7rw$"
    "tmT2xh96T8fz3H2p6jD3VzxKyFZzHeUFucJGxjvSlM0"
)


def _settings_kwargs(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "APP_PASSWORD_HASH": ARGON2_HASH,
        "MEDIA_SERVERS": "Plex",
        "MEDIA_SERVER_PLEX_TYPE": "plex",
        "MEDIA_SERVER_PLEX_URL": "http://127.0.0.1:32400",
        "MEDIA_SERVER_PLEX_API_KEY": "k" * 32,
    }
    data.update(overrides)
    return data


class TestSettingsValidation:
    def test_accepts_and_normalises_valid_runtime_settings(self) -> None:
        configured = Settings(
            **_settings_kwargs(
                APP_PASSWORD_HASH=f" {ARGON2_HASH} ",
                APP_URL="HTTPS://Example.test/app?q=1",
                TRUSTED_PROXY_CIDRS="10.0.0.9, 172.16.0.0/12",
                LOG_LEVEL="WARNING",
                TZ="Europe/Stockholm",
            )
        )

        assert configured.APP_PASSWORD_HASH.get_secret_value() == ARGON2_HASH
        assert configured.APP_URL == "https://example.test"
        assert configured.LOG_LEVEL == "warning"
        assert configured.secure_cookies is True
        assert (
            ip_network("10.0.0.9/32"),
            ip_network("172.16.0.0/12"),
        ) == configured.TRUSTED_PROXY_CIDRS
        assert configured.is_trusted_proxy(ip_address("10.0.0.9")) is True
        assert configured.is_trusted_proxy(ip_address("192.0.2.1")) is False

    def test_rejects_missing_required_secret_material(self) -> None:
        with pytest.raises(ValidationError):
            Settings(**_settings_kwargs(APP_PASSWORD_HASH=""))

    def test_rejects_invalid_service_and_worker_settings(self) -> None:
        invalid_cases = [
            {"MEDIA_SERVERS": ""},
            {"MEDIA_SERVER_PLEX_TYPE": "kodi"},
            {"MEDIA_SERVER_PLEX_URL": ""},
            {"MEDIA_SERVER_PLEX_API_KEY": ""},
            {"MEDIA_SERVER_PLEX_URL": "127.0.0.1:32400"},
            {"LOG_LEVEL": "verbose"},
            {"TZ": "Not/AZone"},
            {"PHASH_WORKERS": 0},
            {"PHASH_WORKERS": 33},
            {"ART_DOWNLOAD_WORKERS": 0},
            {"ART_DOWNLOAD_WORKERS": 11},
            {"THEME_DOWNLOAD_WORKERS": 0},
            {"THEME_DOWNLOAD_WORKERS": 5},
            {"SESSION_EXPIRY_DAYS": 0},
            {"APP_URL": "ftp://example.test"},
            {"TRUSTED_PROXY_CIDRS": "not-a-network"},
            {"MEDIA_SERVER_PLEX_URL": "http://user:pass@media.test"},
            {"MEDIA_SERVER_PLEX_URL": "http://media.test/path?token=secret"},
            {"MEDIA_SERVER_PLEX_URL": "http://media.test/a/../b"},
            {"MEDIA_SERVER_PLEX_URL": "http://media.test/a/%2e%2e/b"},
        ]

        for overrides in invalid_cases:
            with pytest.raises(ValidationError):
                Settings(**_settings_kwargs(**overrides))

    def test_media_server_tls_override_is_limited_to_the_configured_origin(
        self,
    ) -> None:
        configured = Settings(
            **_settings_kwargs(
                MEDIA_SERVER_PLEX_URL="https://media.internal:32400",
                MEDIA_SERVER_PLEX_VERIFY_TLS=False,
            )
        )

        assert configured.MEDIA_SERVERS[0].verify_tls_for() is False
        assert (
            configured.media_server_verify_tls("https://media.internal:32400/art")
            is False
        )
        assert (
            configured.media_server_verify_tls("https://images.example.test/art")
            is True
        )
        assert (
            configured.media_server_verify_tls("https://host.plex.direct:32400/art")
            is True
        )
        assert (
            configured.is_trusted_media_server_url("https://media.internal:32400/art")
            is True
        )
        assert (
            configured.is_trusted_media_server_url("https://images.example.test/art")
            is False
        )
        assert (
            configured.is_trusted_media_server_url(
                "https://unverified.example.plex.direct:32400/art"
            )
            is False
        )

        secure_origin = configured.MEDIA_SERVERS[0].trust_plex_secure_url(
            "https://verified.example.plex.direct:32400"
        )
        assert secure_origin == "https://verified.example.plex.direct:32400"
        assert (
            configured.is_trusted_media_server_url(
                "https://verified.example.plex.direct:32400/art"
            )
            is True
        )
        assert configured.media_server_verify_tls(f"{secure_origin}/art") is True

    def test_accepts_emby_as_a_media_server(self) -> None:
        configured = Settings(
            **_settings_kwargs(
                MEDIA_SERVERS="Emby",
                MEDIA_SERVER_EMBY_TYPE="emby",
                MEDIA_SERVER_EMBY_URL="http://127.0.0.1:8096",
                MEDIA_SERVER_EMBY_API_KEY="emby-key",
            )
        )

        [server] = configured.MEDIA_SERVERS
        assert (server.type, server.name) == (ServerType.EMBY, "Emby")

    def test_names_several_servers_with_their_own_variables(self) -> None:
        configured = Settings(
            **_settings_kwargs(
                MEDIA_SERVERS="Plex, Jelly_4K",
                MEDIA_SERVER_PLEX_TYPE="plex",
                MEDIA_SERVER_PLEX_URL="http://plex.lan:32400/",
                MEDIA_SERVER_PLEX_API_KEY="plex-token",
                MEDIA_SERVER_JELLY_4K_TYPE="JELLYFIN",
                MEDIA_SERVER_JELLY_4K_URL="http://jellyfin.lan:8096",
                MEDIA_SERVER_JELLY_4K_API_KEY="jellyfin-key",
                MEDIA_SERVER_JELLY_4K_PATH_MAP="/data=/media, D:\\4K=/media/4k",
            )
        )

        plex, jellyfin = configured.MEDIA_SERVERS
        assert (plex.key, plex.type, plex.url) == (
            "plex",
            ServerType.PLEX,
            "http://plex.lan:32400",
        )
        assert (jellyfin.key, jellyfin.title, jellyfin.type) == (
            "jelly_4k",
            "Jelly 4K",
            ServerType.JELLYFIN,
        )
        assert jellyfin.local_path("/data/Movies/Alien") == "/media/Movies/Alien"
        assert jellyfin.local_path("d:\\4k\\Alien") == "/media/4k/Alien"
        assert jellyfin.local_path("/elsewhere") == "/elsewhere"
        assert {"plex-token", "jellyfin-key"} <= set(configured.secret_values())

    @pytest.mark.parametrize(
        ("variables", "message"),
        [
            ({"MEDIA_SERVERS": "Plex"}, "MEDIA_SERVER_PLEX_TYPE"),
            (
                {"MEDIA_SERVERS": "Plex", "MEDIA_SERVER_PLEX_TYPE": "plex"},
                "MEDIA_SERVER_PLEX_URL",
            ),
            ({"MEDIA_SERVERS": "plex,Plex"}, "more than once"),
            ({"MEDIA_SERVERS": "4k"}, "must start with a letter"),
        ],
    )
    def test_refuses_misconfigured_servers_naming_what_to_fix(
        self, variables: dict[str, str], message: str
    ) -> None:
        defaults = {
            "MEDIA_SERVER_PLEX_TYPE": "",
            "MEDIA_SERVER_PLEX_URL": "",
            "MEDIA_SERVER_PLEX_API_KEY": "",
        }
        with pytest.raises(ValidationError, match=message):
            Settings(**_settings_kwargs(**(defaults | variables)))


class TestAppSettingsModel:
    def test_defaults_come_from_the_shared_field_declaration(self) -> None:
        """The table and the read schema inherit one declaration."""
        row = AppSettings()

        assert row.id == SETTINGS_ROW_ID
        assert row.workflow == Workflow.ART_AND_THEMES
        assert row.aspect_ratio_tolerance == AspectRatioTolerance.STRICT
        assert row.auto_match_art is False
        assert row.auto_advance_skip_completed is True
        assert set(AppSettingsBase.model_fields) <= set(AppSettingsRead.model_fields)
        assert AppSettingsBase.defaults() == {
            name: field.default for name, field in AppSettingsBase.model_fields.items()
        }

    def test_update_schema_offers_every_setting_as_optional(self) -> None:
        """A setting added to the model cannot be forgotten in the update schema."""
        update_fields = AppSettingsUpdate.model_fields
        assert set(update_fields) == set(AppSettingsBase.model_fields)
        for name, field in AppSettingsBase.model_fields.items():
            # A TypeForm is opaque to the checker; at runtime it supports ``|``.
            annotation: Any = field.annotation
            assert annotation is not None
            assert update_fields[name].annotation == annotation | None, name
            assert update_fields[name].default is None, name

    def test_update_schema_accepts_valid_preferences(self) -> None:
        update = AppSettingsUpdate(
            workflow=Workflow.THEMES,
            aspect_ratio_tolerance=AspectRatioTolerance.LENIENT,
        )

        assert update.workflow == "themes"
        assert update.aspect_ratio_tolerance == "lenient"

    def test_update_schema_rejects_invalid_preferences(self) -> None:
        invalid_cases: list[dict[str, Any]] = [
            {"workflow": "database"},
            {"aspect_ratio_tolerance": "medium"},
            {"tmdb_language_filter": "sv"},
            {"min_duration_seconds": -1},
            {"max_duration_seconds": 3601},
            {"theme_search_format": ""},
            {"disable_plex_resolution_sniff": True},
        ]

        for payload in invalid_cases:
            with pytest.raises(ValidationError):
                AppSettingsUpdate(**payload)


class TestTaskScheduleModel:
    def test_payload_helpers_return_dicts_only(self) -> None:
        schedule = TaskSchedule(task_name="sync")
        schedule.payload = {"library_ids": ["1:1"]}

        assert schedule.payload == {"library_ids": ["1:1"]}

        schedule.payload = {}
        assert schedule.payload == {}
