"""Collections reference their group by key; every group is a row.

Revision ID: c2f9a7d4e815
Revises: b8e3f5a0c612
Create Date: 2026-11-08 12:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "c2f9a7d4e815"
down_revision: str | Sequence[str] | None = "b8e3f5a0c612"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The group a managed collection without one joins, as the app assigns it.
_UNGROUPED = "Ungrouped"


def upgrade() -> None:
    """Give every named group a row and point each managed collection at it.

    Collections Overture does not manage belong to no group, as the app keeps
    them; a managed one without a name joins Ungrouped, as the app assigns it.
    """
    # A collection is managed while it has a rule.
    op.execute(
        "UPDATE media_collections SET collection_group = NULL "
        "WHERE id NOT IN (SELECT collection_id FROM collection_rules)"
    )
    op.execute(
        sa.text(
            "UPDATE media_collections SET collection_group = :name "
            "WHERE id IN (SELECT collection_id FROM collection_rules) "
            "AND TRIM(COALESCE(collection_group, '')) = ''"
        ).bindparams(name=_UNGROUPED)
    )
    op.execute(
        "INSERT INTO collection_groups (server_type, name) "
        "SELECT DISTINCT server_type, collection_group FROM media_collections AS c "
        "WHERE collection_group IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "
        "collection_groups AS g WHERE g.server_type = c.server_type "
        "AND g.name = c.collection_group)"
    )
    with op.batch_alter_table("collection_groups") as batch:
        batch.create_unique_constraint(
            "uq_collection_groups_typed", ["id", "server_type"]
        )
    with op.batch_alter_table("media_collections") as batch:
        batch.add_column(sa.Column("group_id", sa.Integer(), nullable=True))
    op.execute(
        "UPDATE media_collections SET group_id = (SELECT g.id FROM "
        "collection_groups AS g WHERE g.server_type = media_collections.server_type "
        "AND g.name = media_collections.collection_group)"
    )
    with op.batch_alter_table("media_collections") as batch:
        batch.drop_index("ix_media_collections_collection_group")
        batch.drop_column("collection_group")
        batch.create_index("ix_media_collections_group_id", ["group_id"])
        batch.create_foreign_key(
            "fk_media_collections_group",
            "collection_groups",
            ["group_id", "server_type"],
            ["id", "server_type"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    """Name each collection's group again; group rows without defaults stay."""
    with op.batch_alter_table("media_collections") as batch:
        batch.add_column(sa.Column("collection_group", auto_string(), nullable=True))
    op.execute(
        "UPDATE media_collections SET collection_group = (SELECT g.name FROM "
        "collection_groups AS g WHERE g.id = media_collections.group_id)"
    )
    with op.batch_alter_table("media_collections") as batch:
        batch.drop_constraint("fk_media_collections_group", type_="foreignkey")
        batch.drop_index("ix_media_collections_group_id")
        batch.drop_column("group_id")
        batch.create_index(
            "ix_media_collections_collection_group", ["collection_group"]
        )
    with op.batch_alter_table("collection_groups") as batch:
        batch.drop_constraint("uq_collection_groups_typed", type_="unique")
