"""Helpers for consistent websocket job payloads."""

lazy from collections.abc import Mapping
lazy from typing import cast

lazy from pydantic_core import to_jsonable_python

lazy from .errors import public_error_message
lazy from .types import JsonValue


def build_job_payload(
    kind: str,
    status: str,
    *,
    event_job_id: str | None = None,
    target: Mapping[str, JsonValue] | None = None,
    **payload: object,
) -> dict[str, JsonValue]:
    """Return a websocket payload with a stable top-level ``job`` envelope.

    Values may be schema models (a log entry, collected results); they become
    plain JSON here, so the payload can be published and stored alike.
    """
    job: dict[str, JsonValue] = {"kind": kind, "status": status}
    if event_job_id:
        job["id"] = event_job_id
    if target:
        job["target"] = dict(target)

    data = cast("dict[str, JsonValue]", to_jsonable_python(payload))
    error = data.pop("error", None)
    if isinstance(error, str) and error:
        job["error"] = {"message": public_error_message(error)}
    data["job"] = job
    return data
