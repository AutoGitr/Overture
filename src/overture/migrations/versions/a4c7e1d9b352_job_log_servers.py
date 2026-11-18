"""Record the media server each job log line is about.

Revision ID: a4c7e1d9b352
Revises: f1b8d4e6a273
Create Date: 2026-11-18 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a4c7e1d9b352"
down_revision: str | Sequence[str] | None = "f1b8d4e6a273"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_log_lines") as batch:
        batch.add_column(sa.Column("server", sa.String(), nullable=True))
        batch.create_index(
            "ix_job_log_lines_run_server", ["run_id", "server", "ordinal"]
        )


def downgrade() -> None:
    with op.batch_alter_table("job_log_lines") as batch:
        batch.drop_index("ix_job_log_lines_run_server")
        batch.drop_column("server")
