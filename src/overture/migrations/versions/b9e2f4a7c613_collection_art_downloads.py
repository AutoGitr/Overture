"""Queue collection art as downloads, with the poster style a link is chosen as.

Revision ID: b9e2f4a7c613
Revises: a4c7e1d9b352
Create Date: 2026-11-18 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b9e2f4a7c613"
down_revision: str | Sequence[str] | None = "a4c7e1d9b352"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STYLES = ("individual", "matte", "overlay")


def _job_types(*values: str) -> str:
    return "job_type IN ({})".format(", ".join(f"'{value}'" for value in values))


def upgrade() -> None:
    with op.batch_alter_table("download_jobs") as batch:
        batch.drop_constraint("ck_download_jobs_job_type", type_="check")
        batch.create_check_constraint(
            "ck_download_jobs_job_type",
            _job_types("art", "theme", "collection_art", "collection_theme"),
        )
        batch.add_column(
            sa.Column(
                "poster_style",
                sa.Enum(*_STYLES, name="collectionposterstyle", native_enum=False),
                nullable=True,
            )
        )
        batch.create_check_constraint(
            "ck_download_jobs_poster_style",
            "poster_style IN ({})".format(", ".join(f"'{s}'" for s in _STYLES)),
        )


def downgrade() -> None:
    """Drop collection art jobs, which the earlier schema cannot hold."""
    op.execute("DELETE FROM download_jobs WHERE job_type = 'collection_art'")
    with op.batch_alter_table("download_jobs") as batch:
        batch.drop_constraint("ck_download_jobs_poster_style", type_="check")
        batch.drop_column("poster_style")
        batch.drop_constraint("ck_download_jobs_job_type", type_="check")
        batch.create_check_constraint(
            "ck_download_jobs_job_type", _job_types("art", "theme", "collection_theme")
        )
