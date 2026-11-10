"""Finished runs reach the configured service as their rules say, without delay."""

lazy import json

lazy import httpx2
lazy import pytest
lazy from pydantic import SecretStr

lazy from overture.config import Settings
lazy from overture.db.session import Database
lazy from overture.domain import NotifyCompleted
lazy from overture.integrations.notify import NotifyLevel, NotifyMessage, NotifyService
lazy from overture.jobs.kinds import NOTIFIABLE_KINDS, JobKind
lazy from overture.schemas.notifications import (
    NotificationRuleWrite,
    NotificationSettingsUpdate,
)
lazy from overture.services.notifications import (
    NotificationSettings,
    NotifyingPublisher,
    RunNotifier,
)
lazy from overture.utils.errors import PublicServiceError
lazy from tests.http_mock import mock_client_factory
lazy from tests.publishers import NullEventPublisher

_FAILED_SYNC = {
    "job": {
        "kind": "sync",
        "status": "failed",
        "error": {"message": "Plex refused the key secret-key"},
    }
}


def _completed(outcomes: dict[str, int], *, schedule: str | None = None) -> object:
    return {
        "job": {"kind": "sync", "status": "completed"},
        "log_outcomes": outcomes,
        "schedule": schedule,
    }


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[httpx2.Request]:
    requests: list[httpx2.Request] = []

    def handle(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200)

    factory, _transport = mock_client_factory(handle)
    monkeypatch.setattr("overture.services.notifications.create_client", factory)
    return requests


async def _save(database: Database, notifier: RunNotifier, **rule: object) -> None:
    await NotificationSettings(database=database, notifier=notifier).update(
        NotificationSettingsUpdate(
            rules=[NotificationRuleWrite.model_validate({"kind": "sync", **rule})]
        )
    )


async def test_by_default_only_a_failed_run_is_sent_with_its_redacted_error(
    sent: list[httpx2.Request], *, app_config: Settings, database: Database
) -> None:
    app_config.NOTIFY_URL = SecretStr("http://apprise.test/notify/overture")
    app_config.MEDIA_SERVER_API_KEY = SecretStr("secret-key")
    notifier = RunNotifier(app_config=app_config, database=database)
    publisher = NotifyingPublisher(NullEventPublisher(), notifier)

    await publisher.broadcast("sync.completed", _completed({"Added": 2}))
    await publisher.broadcast("sync.stopped", {"job": {"kind": "sync"}})
    await publisher.broadcast("sync.failed", _FAILED_SYNC)
    await notifier.close()

    assert [str(request.url) for request in sent] == [
        "http://apprise.test/notify/overture"
    ]
    assert json.loads(sent[0].content) == {
        "title": "Overture: Library sync failed",
        "body": "Plex refused the key [REDACTED]",
        "type": "failure",
    }


@pytest.mark.parametrize(
    ("completed", "outcomes", "announced"),
    [
        (NotifyCompleted.NEVER, {"Added": 1}, False),
        (NotifyCompleted.ALWAYS, {"Unchanged": 4}, True),
        (NotifyCompleted.CHANGES, {"Unchanged": 4}, False),
        (NotifyCompleted.CHANGES, {"Updated": 1, "Unchanged": 4}, True),
        (NotifyCompleted.ERRORS, {"Updated": 1}, False),
        (NotifyCompleted.ERRORS, {"Error": 1}, True),
    ],
)
async def test_a_completed_run_is_sent_when_its_condition_holds(
    sent: list[httpx2.Request],
    completed: NotifyCompleted,
    outcomes: dict[str, int],
    announced: bool,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    app_config.NOTIFY_URL = SecretStr("http://apprise.test/notify")
    notifier = RunNotifier(app_config=app_config, database=database)
    await _save(database, notifier, completed=completed)

    notifier.observe("sync.completed", _completed(outcomes))
    await notifier.close()

    assert bool(sent) is announced
    if announced:
        body = json.loads(sent[0].content)
        assert body["title"] == "Overture: Library sync completed"
        assert body["type"] == ("warning" if "Error" in outcomes else "success")


async def test_scheduled_only_rules_skip_runs_started_by_hand(
    sent: list[httpx2.Request], *, app_config: Settings, database: Database
) -> None:
    app_config.NOTIFY_URL = SecretStr("http://apprise.test/notify")
    notifier = RunNotifier(app_config=app_config, database=database)
    await _save(
        database, notifier, completed=NotifyCompleted.ALWAYS, scheduled_only=True
    )

    notifier.observe("sync.completed", _completed({"Added": 1}))
    notifier.observe("sync.completed", _completed({"Added": 1}, schedule="Nightly"))
    await notifier.close()

    assert json.loads(sent[0].content)["body"] == "Added 1"
    assert len(sent) == 1


async def test_nothing_is_sent_without_a_url_and_a_failing_service_is_only_logged(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    *,
    app_config: Settings,
    database: Database,
) -> None:
    factory, transport = mock_client_factory(lambda _request: httpx2.Response(500))
    monkeypatch.setattr("overture.services.notifications.create_client", factory)
    silent = RunNotifier(app_config=app_config, database=database)
    silent.observe("sync.failed", _FAILED_SYNC)
    await silent.close()
    assert not transport.called

    app_config.NOTIFY_URL = SecretStr("http://apprise.test/notify/overture?token=x")
    failing = RunNotifier(app_config=app_config, database=database)
    failing.observe("backup.failed", {"job": {"kind": "backup", "status": "failed"}})
    await failing.close()
    assert transport.call_count == 1
    assert "token=x" not in caplog.text
    assert "Could not send the backup notification" in caplog.text


async def test_settings_list_every_kind_and_a_test_reports_what_the_service_said(
    monkeypatch: pytest.MonkeyPatch, *, app_config: Settings, database: Database
) -> None:
    unset = NotificationSettings(
        database=database,
        notifier=RunNotifier(app_config=app_config, database=database),
    )
    read = await unset.get()
    assert read.service is None
    assert [rule.kind for rule in read.rules] == list(NOTIFIABLE_KINDS)
    assert JobKind.DOWNLOAD not in NOTIFIABLE_KINDS
    with pytest.raises(PublicServiceError, match="Set NOTIFY_URL"):
        await unset.test()

    factory, _transport = mock_client_factory(lambda _request: httpx2.Response(403))
    monkeypatch.setattr("overture.services.notifications.create_client", factory)
    app_config.NOTIFY_URL = SecretStr("https://discord.com/api/webhooks/1/abc")
    notifier = RunNotifier(app_config=app_config, database=database)
    refused = NotificationSettings(database=database, notifier=notifier)
    assert (await refused.get()).service_label == "Discord"
    with pytest.raises(PublicServiceError, match="HTTP 403"):
        await refused.test()
    await notifier.close()


def test_one_rule_per_kind_and_never_for_single_downloads() -> None:
    with pytest.raises(ValueError, match="one rule"):
        NotificationSettingsUpdate.model_validate(
            {"rules": [{"kind": "sync"}, {"kind": "sync"}]}
        )
    with pytest.raises(ValueError, match="queue"):
        NotificationSettingsUpdate.model_validate({"rules": [{"kind": "download"}]})


_MESSAGE = NotifyMessage(title="T", body="B", level=NotifyLevel.FAILURE)


@pytest.mark.parametrize(
    ("url", "service", "request_kwargs"),
    [
        (
            "https://discord.com/api/webhooks/1/abc",
            NotifyService.DISCORD,
            {"json": {"content": "**T**\nB", "allowed_mentions": {"parse": []}}},
        ),
        (
            "https://hooks.slack.com/services/A/B/C",
            NotifyService.SLACK,
            {"json": {"text": "*T*\nB"}},
        ),
        (
            "https://api.telegram.org/bot1:x/sendMessage?chat_id=5",
            NotifyService.TELEGRAM,
            {"json": {"text": "T\nB"}},
        ),
        (
            "https://gotify.example.test/message?token=x",
            NotifyService.GOTIFY,
            {"json": {"title": "T", "message": "B", "priority": 8}},
        ),
        (
            "https://ntfy.sh/overture",
            NotifyService.NTFY,
            {"content": b"B", "headers": {"Title": "T", "Tags": "rotating_light"}},
        ),
        (
            "http://apprise.test/notify/overture",
            NotifyService.APPRISE,
            {"json": {"title": "T", "body": "B", "type": "failure"}},
        ),
    ],
)
def test_each_service_gets_the_body_its_api_documents(
    url: str, service: NotifyService, request_kwargs: dict[str, object]
) -> None:
    assert NotifyService.of(url) is service
    assert service.request(_MESSAGE) == request_kwargs


@pytest.mark.parametrize(
    ("url", "service"),
    [
        ("https://discord.com/api/v10/webhooks/1/abc", NotifyService.DISCORD),
        ("https://discord.com/api/users/1", NotifyService.APPRISE),
        ("https://gotify.example.test/message?xtoken=1", NotifyService.APPRISE),
    ],
)
def test_services_are_told_apart_by_their_exact_webhook_address(
    url: str, service: NotifyService
) -> None:
    assert NotifyService.of(url) is service


def test_messages_ping_no_one_keep_their_text_and_fit_each_service() -> None:
    quoted = NotifyMessage(
        title="T",
        body="@everyone <!channel> in <module> & more",
        level=NotifyLevel.FAILURE,
    )
    assert NotifyService.SLACK.request(quoted)["json"]["text"] == (
        "*T*\n@everyone &lt;!channel&gt; in &lt;module&gt; &amp; more"
    )
    discord = NotifyService.DISCORD.request(quoted)["json"]
    assert discord["allowed_mentions"] == {"parse": []}

    long = NotifyMessage(title="T", body="x" * 10_000, level=NotifyLevel.FAILURE)
    content = NotifyService.DISCORD.request(long)["json"]["content"]
    assert len(content) == 2000
    assert content.startswith("**T**\nxxx")
    assert content.endswith("\u2026")
    assert len(NotifyService.TELEGRAM.request(long)["json"]["text"]) == 4096


def test_only_http_notify_urls_are_accepted(app_config: Settings) -> None:
    with pytest.raises(ValueError, match="HTTP or HTTPS"):
        Settings.model_validate(
            {**app_config.model_dump(), "NOTIFY_URL": "mailto:someone@example.test"}
        )
