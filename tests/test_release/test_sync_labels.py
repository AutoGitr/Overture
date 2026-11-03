"""Label reconciliation must make drift visible before changing anything."""

lazy import json
lazy from unittest.mock import MagicMock

lazy import pytest

lazy from scripts import sync_labels

SAMPLE_LABEL: sync_labels.Label = {
    "name": "ci",
    "color": "ededed",
    "description": "Automation",
}


def test_empty_reply_is_none_and_method_is_passed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gh = MagicMock(return_value="")
    monkeypatch.setattr(sync_labels, "gh", gh)

    assert sync_labels.api("endpoint", method="DELETE") is None
    gh.assert_called_once_with("api", "endpoint", "--method", "DELETE", payload=None)


def test_pagination_preserves_every_page(monkeypatch: pytest.MonkeyPatch) -> None:
    gh = MagicMock(return_value=json.dumps([[{"number": 1}], [{"number": 2}]]))
    monkeypatch.setattr(sync_labels, "gh", gh)

    assert sync_labels.pages("endpoint") == [{"number": 1}, {"number": 2}]
    gh.assert_called_once_with("api", "endpoint", "--paginate", "--slurp")


def test_preview_never_writes(monkeypatch: pytest.MonkeyPatch) -> None:
    api = MagicMock()
    monkeypatch.setattr(sync_labels, "pages", MagicMock(return_value=[]))
    monkeypatch.setattr(sync_labels, "api", api)

    assert sync_labels.sync("owner/repo", [SAMPLE_LABEL], apply=False) is True
    api.assert_not_called()


def test_unknown_labels_are_previewed_and_deleted_on_apply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = MagicMock()
    monkeypatch.setattr(
        sync_labels,
        "pages",
        MagicMock(return_value=[dict(SAMPLE_LABEL), {"name": "unmanaged"}]),
    )
    monkeypatch.setattr(sync_labels, "api", api)

    assert sync_labels.sync("owner/repo", [SAMPLE_LABEL], apply=False) is True
    api.assert_not_called()

    assert sync_labels.sync("owner/repo", [SAMPLE_LABEL], apply=True) is True
    api.assert_called_once_with("repos/owner/repo/labels/unmanaged", method="DELETE")


def test_create_update_and_idempotence(monkeypatch: pytest.MonkeyPatch) -> None:
    pages = MagicMock(return_value=[])
    api = MagicMock()
    monkeypatch.setattr(sync_labels, "pages", pages)
    monkeypatch.setattr(sync_labels, "api", api)

    assert sync_labels.sync("owner/repo", [SAMPLE_LABEL], apply=True) is True
    assert api.call_args_list[-1].kwargs["method"] == "POST"

    pages.return_value = [{**SAMPLE_LABEL, "description": "Outdated"}]
    assert sync_labels.sync("owner/repo", [SAMPLE_LABEL], apply=True) is True
    assert api.call_args_list[-1].kwargs["method"] == "PATCH"

    api.reset_mock()
    pages.return_value = [dict(SAMPLE_LABEL)]
    assert sync_labels.sync("owner/repo", [SAMPLE_LABEL], apply=True) is False
    api.assert_not_called()


def test_check_fails_on_drift_without_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sync = MagicMock(return_value=True)
    monkeypatch.setattr(sync_labels, "sync", sync)
    monkeypatch.setattr("sys.argv", ["sync_labels.py", "--check"])

    assert sync_labels.main() == 1
    assert sync.call_args_list[-1].kwargs["apply"] is False

    sync.return_value = False
    assert sync_labels.main() == 0


def test_invalid_repository_never_reaches_github(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = MagicMock()
    monkeypatch.setattr(sync_labels, "pages", pages)

    with pytest.raises(ValueError, match="Repository must be OWNER/REPO"):
        sync_labels.sync("owner/repo?query", [SAMPLE_LABEL], apply=True)
    pages.assert_not_called()
