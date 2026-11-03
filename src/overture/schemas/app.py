"""Application-level REST schemas."""

lazy from typing import Literal

lazy from .base import StrictBaseModel


class HealthResponse(StrictBaseModel):
    """Liveness response."""

    status: Literal["ok"]
    version: str
    python: str


class ReadinessResponse(StrictBaseModel):
    """Readiness response."""

    status: Literal["ready", "not_ready"]
    checks: dict[str, bool]
