"""Named read-only credentials for scripts and dashboards."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlmodel import Field, SQLModel

lazy from ...utils.time import utc_now


class ApiKey(SQLModel, table=True):
    """Only a digest of the key is persisted; the key is shown once, at creation."""

    __tablename__: ClassVar[Any] = "api_keys"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    key_hash: str = Field(unique=True, repr=False)
    created_at: datetime = Field(default_factory=utc_now)
