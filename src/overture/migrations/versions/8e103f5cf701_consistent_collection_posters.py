"""Consistent collection posters from OvertureDB, and the choice between them.

A catalog collection keeps the poster in the layout every consistent
collection poster shares beside its own; the next catalog sync fills it.
Which of the two a collection takes is a collection setting: global, with
group and collection overrides. The global choice starts at the
collection's own poster, which is what OvertureDB gave until now.

Revision ID: 8e103f5cf701
Revises: e8a3c5d1f702
Create Date: 2026-11-11 12:20:52.571065

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "8e103f5cf701"
down_revision: str | Sequence[str] | None = "e8a3c5d1f702"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STYLES = "('individual', 'consistent')"
#: The tables holding a nullable override, which inherits the next tier's.
_OVERRIDES = ("collection_groups", "collection_rules")


def _style() -> sa.Enum:
    return sa.Enum(
        "individual", "consistent", name="collectionposterstyle", native_enum=False
    )


def upgrade() -> None:
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "collection_overturedb_posters",
                _style(),
                nullable=False,
                server_default="individual",
            )
        )
        batch_op.create_check_constraint(
            "ck_app_settings_collection_overturedb_posters",
            f"collection_overturedb_posters IN {_STYLES}",
        )
    # The model defaults new rows; the server default only fills the existing one.
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.alter_column("collection_overturedb_posters", server_default=None)
    for table in _OVERRIDES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.add_column(
                sa.Column("overturedb_posters", _style(), nullable=True)
            )
            batch_op.create_check_constraint(
                f"ck_{table}_overturedb_posters",
                f"overturedb_posters IN {_STYLES}",
            )
    with op.batch_alter_table("public_dataset_collections") as batch_op:
        batch_op.add_column(
            sa.Column("consistent_poster_url", sa.String(), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("public_dataset_collections") as batch_op:
        batch_op.drop_column("consistent_poster_url")
    for table in _OVERRIDES:
        with op.batch_alter_table(table) as batch_op:
            batch_op.drop_constraint(f"ck_{table}_overturedb_posters", type_="check")
            batch_op.drop_column("overturedb_posters")
    with op.batch_alter_table("app_settings") as batch_op:
        batch_op.drop_constraint(
            "ck_app_settings_collection_overturedb_posters", type_="check"
        )
        batch_op.drop_column("collection_overturedb_posters")
