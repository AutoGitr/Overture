"""Failed runs reach the configured webhook, without holding up the run."""

lazy import json

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.services.notifications import FailureNotifier, NotifyingPublisher
lazy from tests.http_mock import mock_client_factory
lazy from tests.publishers import NullEventPublisher

_FAILED_SYNC = {
    "job": {
        "kind": "sync",
        "status": "failed",
        "error": {"message": "Plex refused the key secret-key"},
    }
}


async def test_a_failed_run_is_sent_once_with_its_error_and_others_are_not(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings
) -> None:
    app_config.NOTIFY_URL = SecretStr("http://apprise.test/notify/overture")
    app_config.MEDIA_SERVER_API_KEY = SecretStr("secret-key")
    factory, transport = mock_client_factory(lambda _request: httpx2.Response(200))
    monkeypatch.setattr("overture.services.notifications.create_client", factory)
    notifier = FailureNotifier(app_config=app_config)
    publisher = NotifyingPublisher(NullEventPublisher(), notifier)

    await publisher.broadcast("sync.completed", {"job": {"kind": "sync"}})
    await publisher.broadcast("sync.failed", _FAILED_SYNC)
    await notifier.close()

    assert transport.call_count == 1
    assert str(transport.last_request.url) == "http://apprise.test/notify/overture"
    assert json.loads(transport.last_request.content) == {
        "title": "Overture: Library sync failed",
        "body": "Plex refused the key [REDACTED]",
        "type": "failure",
    }


async def test_nothing_is_sent_without_a_url_and_a_failing_webhook_is_only_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    *,
    app_config: Settings,
) -> None:
    factory, transport = mock_client_factory(lambda _request: httpx2.Response(500))
    monkeypatch.setattr("overture.services.notifications.create_client", factory)
    silent = FailureNotifier(app_config=app_config)
    silent.observe("sync.failed", _FAILED_SYNC)
    await silent.close()
    assert not transport.called

    app_config.NOTIFY_URL = SecretStr("http://apprise.test/notify/overture?token=x")
    failing = FailureNotifier(app_config=app_config)
    failing.observe("backup.failed", {"job": {"kind": "backup", "status": "failed"}})
    await failing.close()
    assert transport.call_count == 1
    assert "token=x" not in caplog.text
    assert "Could not send the backup failure notification" in caplog.text


def test_only_http_notify_urls_are_accepted(app_config: Settings) -> None:
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        Settings.model_validate(
            {**app_config.model_dump(), "NOTIFY_URL": "mailto:someone@example.test"}
        )
