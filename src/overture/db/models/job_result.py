"""Small durable run summaries and ordered scan/match/audit findings."""

lazy from datetime import datetime
lazy from typing import Any, ClassVar

lazy from sqlalchemy import JSON
lazy from sqlmodel import Field, SQLModel


class JobRun(SQLModel, table=True):
    __tablename__: ClassVar[Any] = "job_runs"

    id: str = Field(primary_key=True)
    kind: str = Field(index=True)
    started_at: datetime
    finished_at: datetime | None = Field(default=None, index=True)
    event: str
    summary: dict[str, Any] = Field(default_factory=dict, sa_type=JSON)
    total: int = 0
    cleared: bool = False


class JobResult(SQLModel, table=True):
    __tablename__: ClassVar[Any] = "job_results"

    run_id: str = Field(primary_key=True, foreign_key="job_runs.id", ondelete="CASCADE")
    ordinal: int = Field(primary_key=True)
    payload: dict[str, Any] = Field(sa_type=JSON)
