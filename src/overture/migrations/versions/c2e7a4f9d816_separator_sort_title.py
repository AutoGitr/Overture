"""A separated group shows the sort title it gives its collections.

Revision ID: c2e7a4f9d816
Revises: b9d4f2a7e135
Create Date: 2026-11-27 15:00:00.000000

A group with a separator and no sort title anywhere sorted its collections as
``{group} {title}`` without saying so. The group now holds that sort title, so
its collections sort as before and the group's settings show why.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2e7a4f9d816"
down_revision: str | Sequence[str] | None = "b9d4f2a7e135"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The sort title, as ``SEPARATED_SORT_TITLE`` names it when this was written.
_SEPARATED = "{group} {title}"


def upgrade() -> None:
    # A global sort title was taken before the separator's, so it still is.
    op.get_bind().exec_driver_sql(
        "UPDATE collection_groups SET sort_title_format = ? "
        "WHERE separator AND sort_title_format IS NULL "
        "AND COALESCE((SELECT collection_sort_title_format FROM app_settings "
        "LIMIT 1), '') = ''",
        (_SEPARATED,),
    )


def downgrade() -> None:
    """The sort title stays: the version before gave the same one unsaid."""
