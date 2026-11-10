"""Notification REST schemas."""

lazy from typing import Annotated, Self

lazy from pydantic import Field, model_validator

lazy from ..domain import NotifyCompleted
lazy from ..integrations.notify import NotifyService
lazy from ..jobs.kinds import JobKind
lazy from .base import StrictBaseModel


class NotificationRuleWrite(StrictBaseModel):
    """When runs of one kind are announced."""

    kind: JobKind
    failed: bool = True
    stopped: bool = False
    completed: NotifyCompleted = NotifyCompleted.NEVER
    #: Announce only runs a saved schedule started, not ones started by hand.
    scheduled_only: bool = False


class NotificationRuleRead(NotificationRuleWrite):
    """When runs of one kind are announced, and how the kind is named."""

    #: How the kind is named to users.
    label: str


class NotificationSettingsRead(StrictBaseModel):
    """Where notifications go, and when each kind of run sends one."""

    #: The service ``NOTIFY_URL`` names; none when it is not set.
    service: NotifyService | None
    #: How that service is named to users.
    service_label: str | None
    #: One rule per kind of run, in a fixed order.
    rules: list[NotificationRuleRead]


class NotificationSettingsUpdate(StrictBaseModel):
    """The rules to save; a kind left out keeps its saved rule."""

    rules: Annotated[list[NotificationRuleWrite], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_kinds(self) -> Self:
        """Each kind of run once, and only kinds that can be announced."""
        kinds = [rule.kind for rule in self.rules]
        if len(set(kinds)) != len(kinds):
            raise ValueError("Give each kind of run one rule")
        if any(not kind.notifiable for kind in kinds):
            raise ValueError("Single downloads are reported in the queue")
        return self
