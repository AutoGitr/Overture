"""Record the media server a job log line is about by its number.

A line named its server by its MEDIA_SERVERS name; it now also holds the
server's number, which a rename leaves alone, and the log is filtered by it.
A stored line takes the number of the server with its name.

Revision ID: e2a6c8f4d137
Revises: d7b3e9a1c524
Create Date: 2026-11-18 21:20:00.000000

"""

import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2a6c8f4d137"
down_revision: str | Sequence[str] | None = "d7b3e9a1c524"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("job_log_lines") as batch:
        batch.add_column(sa.Column("server_id", sa.Integer(), nullable=True))
    connection = op.get_bind()
    numbers = {
        title: server_id
        for server_id, title in connection.execute(
            sa.text("SELECT id, title FROM media_servers")
        )
    }
    for run_id, ordinal, server, entry in connection.execute(
        sa.text(
            "SELECT run_id, ordinal, server, entry FROM job_log_lines "
            "WHERE server IS NOT NULL"
        )
    ).all():
        server_id = numbers.get(server)
        connection.execute(
            sa.text(
                "UPDATE job_log_lines SET server_id = :server_id, entry = :entry "
                "WHERE run_id = :run_id AND ordinal = :ordinal"
            ),
            {
                "server_id": server_id,
                "entry": json.dumps({**json.loads(entry), "server_id": server_id}),
                "run_id": run_id,
                "ordinal": ordinal,
            },
        )
    with op.batch_alter_table("job_log_lines") as batch:
        batch.drop_index("ix_job_log_lines_run_server")
        batch.drop_column("server")
        batch.create_index(
            "ix_job_log_lines_run_server", ["run_id", "server_id", "ordinal"]
        )


def downgrade() -> None:
    with op.batch_alter_table("job_log_lines") as batch:
        batch.add_column(sa.Column("server", sa.String(), nullable=True))
    # The earlier entries name no number.
    op.execute(
        "UPDATE job_log_lines SET server = json_extract(entry, '$.server'), "
        "entry = json_remove(entry, '$.server_id')"
    )
    with op.batch_alter_table("job_log_lines") as batch:
        batch.drop_index("ix_job_log_lines_run_server")
        batch.drop_column("server_id")
        batch.create_index(
            "ix_job_log_lines_run_server", ["run_id", "server", "ordinal"]
        )
