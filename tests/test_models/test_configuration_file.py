"""The configuration file holds literal values that the environment overrides."""

lazy import os
lazy from pathlib import Path

lazy import pytest

lazy from overture import config
lazy from overture.config import (
    RuntimeSettings,
    Settings,
    load_configuration,
    read_configuration,
    write_configuration,
)
lazy from overture.passwords import hash_password


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("OVERTURE_CONFIG_FILE", raising=False)


def test_configuration_precedence_and_literal_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "overture.env"
    write_configuration(
        path, {"OVERTURE_PORT": "6000", "MEDIA_SERVER_API_KEY": "a'\\${HOME}$b"}
    )
    assert read_configuration(path)["MEDIA_SERVER_API_KEY"] == "a'\\${HOME}$b"
    monkeypatch.chdir(tmp_path.parent)
    assert load_configuration(RuntimeSettings, path).OVERTURE_PORT == 6000
    monkeypatch.setenv("OVERTURE_PORT", "6001")
    assert load_configuration(RuntimeSettings, path).OVERTURE_PORT == 6001


def test_failed_write_preserves_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "overture.env"
    path.write_text("original")

    def fail_replace(self: Path, target: Path) -> Path:
        raise OSError("replacement failed")

    monkeypatch.setattr(Path, "replace", fail_replace)
    with pytest.raises(OSError, match="replacement failed"):
        write_configuration(path, {"KEY": "replacement"})
    assert path.read_text() == "original"
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.skipif(os.name != "posix", reason="POSIX ownership and permissions")
def test_write_preserves_private_permissions_and_owner(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.touch(mode=0o600)
    previous = path.stat()
    write_configuration(path, {"KEY": "updated"})
    current = path.stat()
    assert current.st_mode & 0o777 == 0o600
    assert (current.st_uid, current.st_gid) == (previous.st_uid, previous.st_gid)


def test_compose_secrets_fill_settings_the_environment_leaves_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    encoded = hash_password("a long simple password")
    (tmp_path / "app_password_hash").write_text(f"{encoded}\n")
    (tmp_path / "tmdb_api_key").write_text("from-secret")
    monkeypatch.setattr(config, "SECRETS_DIR", tmp_path)
    monkeypatch.setenv("MEDIA_SERVER", "plex")
    monkeypatch.setenv("MEDIA_SERVER_URL", "http://127.0.0.1:32400")
    monkeypatch.setenv("MEDIA_SERVER_API_KEY", "test-key")
    # Compose passes an unset optional variable as an empty string.
    monkeypatch.setenv("APP_PASSWORD_HASH", "")
    monkeypatch.setenv("TMDB_API_KEY", "from-environment")
    settings = load_configuration(Settings, tmp_path / "absent.env")
    assert settings.APP_PASSWORD_HASH.get_secret_value() == encoded
    assert settings.TMDB_API_KEY.get_secret_value() == "from-environment"
