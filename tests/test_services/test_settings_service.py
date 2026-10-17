"""Coverage for the application settings route-facing service."""

lazy import pytest
lazy from pydantic import SecretStr, ValidationError
lazy from sqlmodel.ext.asyncio.session import AsyncSession

lazy from overture.config import Settings
lazy from overture.db.models.settings import AppSettings, get_app_settings
lazy from overture.domain import (
    AspectRatioTolerance,
    AutoUnmonitor,
    ServerType,
    TmdbLanguageFilter,
    Workflow,
)
lazy from overture.schemas.settings import AppSettingsUpdate
lazy from overture.services import settings as module
lazy from overture.utils.errors import PublicServiceError
lazy from tests.runtime_helpers import (
    NoopProviderRegistry,
    database_for,
    one_session,
)


class FakeProvider:
    def __init__(self, *, server_type: str = "plex", connected: bool = True) -> None:
        self.server_type = server_type
        self._connected = connected

    async def test_connection(self) -> bool:
        return self._connected


class FakeTmdbClient:
    def __init__(self, *, connected: bool = True) -> None:
        self._connected = connected

    async def test_connection(self) -> bool:
        return self._connected


@pytest.mark.parametrize("workflow", ["art", "art_and_themes", "themes"])
def test_workflow_values(workflow: str) -> None:
    assert AppSettingsUpdate.model_validate({"workflow": workflow}).workflow == workflow


@pytest.mark.parametrize(
    "policy", ["off", "art", "theme", "art_or_theme", "art_and_theme"]
)
def test_auto_unmonitor_values(policy: str) -> None:
    assert (
        AppSettingsUpdate.model_validate({"auto_unmonitor": policy}).auto_unmonitor
        == policy
    )


@pytest.mark.parametrize(
    "payload",
    [
        {"workflow": "invalid"},
        {"auto_unmonitor": "invalid"},
        {"default_tab": "art"},
        {"auto_advance_art_section": True},
        {"auto_advance_to_theme": True},
        {"auto_advance_to_next_item": True},
        {"auto_advance_delay_ms": 300},
    ],
)
def test_workflow_rejects_invalid_and_removed_settings(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AppSettingsUpdate.model_validate(payload)


async def test_get_settings_creates_default_row(
    db_session: AsyncSession, *, app_config: Settings
) -> None:
    result = await module.get_settings(db_session, app_config=app_config)

    assert result.auto_match_art is False
    assert result.theme_search_format == "{title} {year} main theme music ost"
    # No TMDB key configured in the test environment, so the default stays False.
    assert result.skip_media_server_tmdb_urls is False
    assert result.auto_advance is False
    assert result.auto_unmonitor == "off"
    assert result.auto_advance_skip_completed is True


async def test_get_settings_defaults_skip_tmdb_urls_disabled_even_when_tmdb_configured(
    db_session: AsyncSession, *, app_config: Settings
) -> None:
    app_config.TMDB_API_KEY = SecretStr("a" * 32)

    result = await module.get_settings(db_session, app_config=app_config)

    assert result.skip_media_server_tmdb_urls is False


async def test_get_settings_returns_existing_row_without_recreating(
    db_session: AsyncSession, *, app_config: Settings
) -> None:
    first = await module.get_settings(db_session, app_config=app_config)
    second = await module.get_settings(db_session, app_config=app_config)

    assert first.workflow == second.workflow == "art"


async def test_update_settings_creates_row_when_absent_and_applies_all_fields(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    database = database_for(one_session(db_session))
    body = AppSettingsUpdate(
        auto_match_art=True,
        workflow=Workflow.THEMES,
        theme_search_format="{title} theme",
        min_duration_seconds=10,
        max_duration_seconds=60,
        initial_results=8,
        load_more_step=4,
        skip_media_server_tmdb_urls=True,
        disable_media_server_art=True,
        aspect_ratio_tolerance=AspectRatioTolerance.LENIENT,
        plex_collections_enabled=False,
        tmdb_language_filter=TmdbLanguageFilter.ALL,
        auto_advance=True,
        auto_unmonitor=AutoUnmonitor.ART_AND_THEME,
        auto_advance_skip_completed=False,
    )

    result = await module.update_settings(
        body, app_config=app_config, database=database
    )

    assert result.auto_match_art is True
    assert result.workflow == "themes"
    assert result.theme_search_format == "{title} theme"
    assert result.min_duration_seconds == 10
    assert result.max_duration_seconds == 60
    assert result.initial_results == 8
    assert result.load_more_step == 4
    assert result.skip_media_server_tmdb_urls is True
    assert result.disable_media_server_art is True
    assert result.aspect_ratio_tolerance == "lenient"
    assert result.plex_collections_enabled is False
    assert result.tmdb_language_filter == "all"
    assert result.auto_advance is True
    assert result.auto_unmonitor == "art_and_theme"
    assert result.auto_advance_skip_completed is False
    assert result.updated_at is not None


async def test_update_settings_with_no_fields_preserves_existing_row(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    await module.get_settings(db_session, app_config=app_config)

    database = database_for(one_session(db_session))
    result = await module.update_settings(
        AppSettingsUpdate(), app_config=app_config, database=database
    )

    assert result.workflow == "art"
    assert result.auto_match_art is False


def test_update_schema_rejects_overlong_theme_search_format() -> None:
    """The length limit is declared on the persisted field, not restated."""
    with pytest.raises(ValidationError, match="at most 200 characters"):
        AppSettingsUpdate(theme_search_format="x" * 201)


@pytest.mark.parametrize(
    "update",
    [
        AppSettingsUpdate(min_duration_seconds=90),
        AppSettingsUpdate(min_duration_seconds=300, max_duration_seconds=30),
    ],
)
async def test_update_settings_rejects_min_greater_than_max_duration(
    db_session: AsyncSession,
    update: AppSettingsUpdate,
    *,
    app_config: Settings,
) -> None:
    # The range spans two fields, so it is checked against the saved values
    # merged with the update, whether one or both bounds are sent.
    database = database_for(one_session(db_session))
    await module.update_settings(
        AppSettingsUpdate(min_duration_seconds=30, max_duration_seconds=60),
        app_config=app_config,
        database=database,
    )

    with pytest.raises(PublicServiceError) as exc_info:
        await module.update_settings(
            update,
            app_config=app_config,
            database=database,
        )

    assert exc_info.value.status_code == 400
    assert "min_duration_seconds" in exc_info.value.message


@pytest.mark.parametrize("connected", [True, False])
async def test_connectivity_reports_whether_each_service_answers(
    connected: bool,
) -> None:
    registry = NoopProviderRegistry(
        FakeProvider(server_type=ServerType.JELLYFIN, connected=connected)
    )

    status = await module.check_connectivity(
        registry, FakeTmdbClient(connected=not connected)
    )

    assert (status.media_server, status.tmdb) == (connected, not connected)


@pytest.mark.parametrize("saved", [False, True])
async def test_settings_mapping_includes_environment_fields(
    db_session: AsyncSession, app_config: Settings, saved: bool
) -> None:
    app_config.MEDIA_SERVER = ServerType.JELLYFIN
    app_config.TMDB_API_KEY = SecretStr("test-key")
    if saved:
        db_session.add(AppSettings(id=1))
        await db_session.commit()
    result = await module.get_settings(db_session, app_config=app_config)
    assert result.media_server == "jellyfin"
    assert result.tmdb_configured is True


async def test_get_app_settings_returns_defaults_when_unsaved(
    db_session: AsyncSession,
) -> None:
    settings = await get_app_settings(db_session)
    assert settings.skip_media_server_tmdb_urls is False
    assert settings.auto_match_art is False
    assert settings.disable_media_server_art is False
    assert settings.workflow == "art"
