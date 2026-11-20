"""Forget fingerprints of an earlier format, so they are taken again.

A fingerprint is 64 hexadecimal digits. A shorter one cannot be compared
with one taken now, so it is cleared: a refresh fingerprints a title's file
again, and a collection's image is fingerprinted from the copy Overture keeps
when it is next compared.

Revision ID: c4f8a2e6b913
Revises: b9e2f4a7c613
Create Date: 2026-11-18 21:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4f8a2e6b913"
down_revision: str | Sequence[str] | None = "b9e2f4a7c613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        "UPDATE art_slots SET phash = NULL WHERE phash IS NOT NULL "
        "AND length(phash) != 64"
    )


def downgrade() -> None:
    """Keep the fingerprints: the earlier schema reads the same column."""
