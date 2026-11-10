"""Which runs of each kind are announced at ``NOTIFY_URL``."""

lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, SQLModel

lazy from ...domain import NotifyCompleted
lazy from ..columns import enum_type, typed_columns


class NotificationRule(SQLModel, table=True):
    """When runs of one kind are announced; a kind without a row uses the defaults."""

    __tablename__: ClassVar[Any] = "notification_rules"

    #: The kind of run, as ``JobKind`` names it.
    kind: str = Field(primary_key=True)
    failed: bool = True
    stopped: bool = False
    completed: NotifyCompleted = Field(
        default=NotifyCompleted.NEVER, sa_type=enum_type(NotifyCompleted)
    )
    #: Announce only runs a saved schedule started, not ones started by hand.
    scheduled_only: bool = False


typed_columns(NotificationRule)
