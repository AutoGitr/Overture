"""Tests for FastAPI runtime dependency injection."""

lazy from unittest.mock import MagicMock

lazy import pytest
lazy from starlette.requests import Request

lazy from overture.dependencies import (
    get_art,
    get_asset_manager,
    get_assets,
    get_backups,
    get_collections,
    get_database,
    get_events,
    get_library,
    get_provider_registry,
    get_public_dataset,
    get_runtime,
    get_server_audit,
    get_settings,
    get_stats,
    get_sync,
    get_themes,
    get_tmdb,
    get_tmdb_items,
)
lazy from overture.runtime import RuntimeServices


def test_get_runtime_validation() -> None:
    # Missing runtime raises RuntimeError
    req_no_runtime = MagicMock(spec=Request)
    req_no_runtime.app.state = MagicMock(spec=[])
    with pytest.raises(RuntimeError, match="RuntimeServices is not attached"):
        get_runtime(req_no_runtime)

    # Valid runtime returns instance
    runtime_mock = MagicMock(spec=RuntimeServices)
    req_valid = MagicMock(spec=Request)
    req_valid.app.state.runtime = runtime_mock
    assert get_runtime(req_valid) is runtime_mock


def test_dependency_getters() -> None:
    runtime = MagicMock(spec=RuntimeServices)

    assert get_settings(runtime) is runtime.app_settings
    assert get_database(runtime) is runtime.database
    assert get_art(runtime) is runtime.art
    assert get_library(runtime) is runtime.library
    assert get_sync(runtime) is runtime.sync
    assert get_server_audit(runtime) is runtime.server_audit
    assert get_collections(runtime) is runtime.collections
    assert get_themes(runtime) is runtime.themes
    assert get_tmdb_items(runtime) is runtime.tmdb_items
    assert get_backups(runtime) is runtime.backups
    assert get_public_dataset(runtime) is runtime.public_dataset
    assert get_assets(runtime) is runtime.assets
    assert get_asset_manager(runtime) is runtime.asset_manager
    assert get_stats(runtime) is runtime.stats
    assert get_provider_registry(runtime) is runtime.provider_registry
    assert get_tmdb(runtime) is runtime.tmdb
    assert get_events(runtime) is runtime.events
