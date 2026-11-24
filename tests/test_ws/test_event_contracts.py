"""Typed WebSocket event registry contracts."""

lazy from copy import deepcopy
lazy from typing import Any

lazy import pytest
lazy from pydantic import ValidationError

lazy from overture.db.models.media_item import MediaItem
lazy from overture.domain import MediaType
lazy from overture.schemas.catalog import CatalogStatus
lazy from overture.schemas.library import (
    LibraryItemUpsertedEvent,
    media_item_read_from_model,
)
lazy from overture.ws.events import EVENT_REGISTRY, validate_event_payload


def _validated_payload(event: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a validated object payload for events with schema models."""
    validated = validate_event_payload(event, payload)
    assert validated is not None
    return validated


def test_event_payload_validation_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        validate_event_payload(
            "schedules.changed", {"kind": "sync", "api_key": "secret"}
        )


@pytest.mark.parametrize(
    "invalid", [{"art_type": "typo"}, {"job_type": "collection_theme"}]
)
def test_item_download_targets_reject_unknown_or_collection_asset_kinds(
    invalid: dict[str, str],
) -> None:
    with pytest.raises(ValidationError):
        validate_event_payload(
            "download.started",
            {
                "job": {
                    "id": "download",
                    "kind": "download",
                    "status": "started",
                    "target": {"target_type": "item", "media_item_id": 1, **invalid},
                }
            },
        )


def test_sync_events_use_domain_specific_contract() -> None:
    payload = _validated_payload(
        "sync.progress",
        {
            "job": {"kind": "sync", "status": "progress"},
            "done": 1,
            "total": 2,
            "log_targets": {"Added": 1},
        },
    )
    assert (payload["job"]["kind"], payload["job"]["status"]) == ("sync", "progress")
    assert payload["log_targets"] == {"Added": 1}

    with pytest.raises(ValidationError):
        validate_event_payload("sync.progress", {"unexpected": True})


def test_job_envelopes_accept_typed_public_error_metadata() -> None:
    payload = _validated_payload(
        "sync.failed",
        {
            "job": {
                "kind": "sync",
                "status": "failed",
                "error": {"message": "failed safely"},
            },
        },
    )

    assert payload["job"]["error"] == {"message": "failed safely"}


def test_bulk_events_point_at_their_persisted_log() -> None:
    payload = _validated_payload(
        "match.progress",
        {
            "job": {"kind": "bulk_art", "status": "progress"},
            "done": 1,
            "total": 2,
            "log_targets": {"Adopted": 1},
            "run_id": "run-1",
            "log_total": 3,
        },
    )
    assert (payload["run_id"], payload["log_total"]) == ("run-1", 3)
    with pytest.raises(ValidationError):
        validate_event_payload("match.progress", {"result": {"title": "Movie"}})


def test_every_registry_event_validates_payload_and_rejects_unknown_fields() -> None:
    for event_name in EVENT_REGISTRY:
        definition = EVENT_REGISTRY[event_name]
        payload = _sample_payload(event_name)
        validated = validate_event_payload(event_name, payload)

        if definition.payload_model is None:
            # Null-payload events (e.g. ping) return None; there is no schema
            # to validate against so the unknown-field check does not apply.
            assert validated is None
            continue

        assert validated is not None

        bad_payload = dict(payload)
        bad_payload["unexpected"] = True
        with pytest.raises(ValidationError):
            validate_event_payload(event_name, bad_payload)


def test_asset_scan_payload_contract_accepts_snapshots() -> None:
    payload = _validated_payload(
        "assets.scan.completed",
        {
            "issues": [
                {
                    "folder": "/media/Movie",
                    "current_path": "/media/Movie/cover.jpg",
                    "current_filename": "cover.jpg",
                    "suggested_path": "/media/Movie/poster.jpg",
                    "suggested_filename": "poster.jpg",
                    "type": "poster",
                    "conflict": False,
                    "width": 1000,
                    "height": 1500,
                    "potential_false_positive": False,
                }
            ],
            "total_folders": 1,
            "finished_at": "2026-05-21T00:00:00+00:00",
        },
    )

    assert payload["issues"][0]["suggested_filename"] == "poster.jpg"
    assert payload["total_folders"] == 1


# Sample payloads keyed the way the event registry is: exact event names first,
# then the lifecycle prefix shared by every status of one job.
_EXACT_SAMPLE_PAYLOADS: frozendict[str, dict[str, Any]] = frozendict(
    {  # pyright: ignore[reportCallIssue] -- stale frozendict stub
        "ping": {},
        "realtime.snapshot": {
            "epoch": "epoch-1",
            "sequence": 3,
            "server_time": "2026-05-21T00:00:00+00:00",
            "jobs": [],
            "downloads": [],
            "catalog_status": {
                "enabled": False,
                "repo_url": "https://example.test/repo.git",
                "catalog_url": "https://example.test/catalog.jsonl",
                "timezone": "UTC",
            },
            "media_servers": [
                {"server_id": 1, "title": "Plex", "state": "reachable", "message": ""}
            ],
            "app_version": "1.0.0",
        },
        "collections.changed": {},
        "collection.updated": {"collection_id": 1, "titles": False},
        "collection.monitored": {"collection_id": 1, "monitored": True},
        "library.item.upserted": {
            "item": media_item_read_from_model(
                MediaItem(id=1, media_type=MediaType.MOVIE, title="Movie"), seasons=[]
            ).model_dump(mode="json")
        },
        "library.item.removed": {"media_item_id": 1},
        "library.items.changed": {"item_ids": [1, 2], "operation": "artwork"},
        "catalog.updated": {
            "enabled": True,
            "repo_url": "https://example.test/repo.git",
            "catalog_url": "https://example.test/catalog.jsonl",
            "timezone": "UTC",
        },
        "item.updated": {"media_item_id": 1},
        "job.snapshot.cleared": {
            "kind": "asset_scan",
            "finished_at": "2026-05-31T00:00:00+00:00",
        },
        "schedules.changed": {"kind": "sync"},
        "media-server.status": {
            "server_id": 1,
            "title": "Plex",
            "state": "unreachable",
            "message": "The media server is unavailable",
        },
    }
)

_PREFIX_SAMPLE_PAYLOADS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("sync.", {"job": {"kind": "sync", "status": "progress"}, "done": 0}),
    ("match.", {"job": {"kind": "bulk_art", "status": "progress"}, "done": 0}),
    ("theme.", {"job": {"kind": "bulk_theme", "status": "progress"}, "done": 0}),
    ("assets.scan.", {"done": 0, "total": 1}),
    ("server.audit.", {"done": 0, "total": 1}),
    (
        "download.",
        {
            "job": {
                "kind": "download",
                "status": "progress",
                "id": "download-1",
                "target": {"target_type": "item", "media_item_id": 1},
            },
        },
    ),
    (
        "catalog.sync.",
        {
            "job": {"kind": "catalog_sync", "status": "progress"},
            "stats": {"entries": 1, "errors": 0},
        },
    ),
    (
        "backup.",
        {
            "job": {"kind": "backup", "status": "completed"},
            "filename": "overture_20260522_000000.db",
            "scheduled": False,
        },
    ),
)


def _sample_payload(event_name: str) -> dict[str, Any]:
    """Return a valid sample payload for one registered event."""
    if event_name in _EXACT_SAMPLE_PAYLOADS:
        return deepcopy(_EXACT_SAMPLE_PAYLOADS[event_name])
    for prefix, payload in _PREFIX_SAMPLE_PAYLOADS:
        if event_name.startswith(prefix):
            return deepcopy(payload)
    raise AssertionError(f"Missing sample payload for {event_name}")


def test_every_event_carries_every_field_of_its_payload() -> None:
    """The generated types name every field, so none is left out, null or not."""
    for event_name, definition in EVENT_REGISTRY.items():
        if definition.payload_model is None:
            continue
        payload = _validated_payload(event_name, _sample_payload(event_name))
        assert set(payload) == set(definition.payload_model.model_fields), event_name


def test_a_download_event_names_the_step_it_has_not_reached() -> None:
    payload = _validated_payload(
        "download.started",
        {
            "job": {
                "kind": "download",
                "status": "started",
                "id": "1",
                "target": {
                    "target_type": "collection",
                    "collection_id": 1,
                    "title": "Saga",
                    "job_type": "collection_art",
                    "art_type": "poster",
                },
            }
        },
    )

    assert (payload["step"], payload["steps"]) == (None, None)


def test_library_item_event_carries_every_field_including_nulls() -> None:
    read = media_item_read_from_model(
        MediaItem(id=1, media_type=MediaType.MOVIE, title="Alien"), seasons=[]
    )
    payload = validate_event_payload(
        "library.item.upserted",
        LibraryItemUpsertedEvent(item=read),
    )

    assert payload is not None
    item = payload["item"]
    assert isinstance(item, dict)
    assert set(item) == set(type(read).model_fields)
    assert item["year"] is None
    assert read.assets.poster.url is None
    assert item["assets"] == read.assets.model_dump(mode="json")


def test_catalog_event_carries_every_field_including_nulls() -> None:

    status = CatalogStatus(
        enabled=False,
        repo_url="https://example.test/repo.git",
        catalog_url="https://example.test/catalog.jsonl",
        timezone="UTC",
    )
    payload = validate_event_payload("catalog.updated", status)

    assert payload is not None
    assert set(payload) == set(CatalogStatus.model_fields)
    assert payload["last_synced_at"] is None
