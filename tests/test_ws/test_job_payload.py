"""Public job metadata and error redaction."""

lazy from overture.utils.job_events import build_job_payload


class TestJobPayload:
    def test_build_job_payload_places_metadata_in_stable_job_envelope(self) -> None:
        payload = build_job_payload(
            "bulk_art",
            "progress",
            event_job_id="job-1",
            target={"item_id": 7},
            done=1,
            total=10,
        )

        assert payload["done"] == 1
        assert payload["total"] == 10
        assert payload["job"] == {
            "kind": "bulk_art",
            "status": "progress",
            "id": "job-1",
            "target": {"item_id": 7},
        }

    def test_build_job_payload_adds_typed_error_metadata(self) -> None:
        payload = build_job_payload(
            "bulk_art",
            "failed",
            error="failed with token=secret",
        )

        assert payload["job"] == {
            "kind": "bulk_art",
            "status": "failed",
            "error": {"message": "failed with token=[REDACTED]"},
        }
