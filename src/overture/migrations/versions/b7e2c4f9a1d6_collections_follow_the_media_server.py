"""Collections and groups belong to Overture, not to one media server.

Overture kept a set of collections and groups for each media server it had
synced and showed the active server's. It now keeps one set, which follows the
media server when it changes. The set of the server whose collections synced
last is kept, since that is the one in use; a server changed since then takes
it over at the next start. The others are deleted with everything they hold.

Revision ID: b7e2c4f9a1d6
Revises: 8e103f5cf701
Create Date: 2026-11-11 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7e2c4f9a1d6"
down_revision: str | Sequence[str] | None = "8e103f5cf701"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SERVERS = "('plex', 'jellyfin', 'emby')"
#: The tables holding a collection's parts, which go with it.
_COLLECTION_PARTS = (
    "collection_libraries",
    "collection_rules",
    "media_collection_members",
    "art_slots",
    "download_jobs",
)


def _kept_server(conn: sa.Connection) -> str | None:
    """The server whose collections synced last, else whose group came last."""
    row = (
        conn.exec_driver_sql(
            "SELECT server_type FROM media_collections "
            "ORDER BY last_synced_at IS NULL, last_synced_at DESC, id DESC LIMIT 1"
        ).first()
        or conn.exec_driver_sql(
            "SELECT server_type FROM collection_groups ORDER BY id DESC LIMIT 1"
        ).first()
    )
    return None if row is None else str(row[0])


def upgrade() -> None:
    conn = op.get_bind()
    if (kept := _kept_server(conn)) is not None:
        stale = "SELECT id FROM media_collections WHERE server_type != :kept"
        for table in _COLLECTION_PARTS:
            conn.execute(
                sa.text(f"DELETE FROM {table} WHERE collection_id IN ({stale})"),  # noqa: S608 -- table names are this module's constants
                {"kept": kept},
            )
        conn.execute(
            sa.text("DELETE FROM media_collections WHERE server_type != :kept"),
            {"kept": kept},
        )
        conn.execute(
            sa.text("DELETE FROM collection_groups WHERE server_type != :kept"),
            {"kept": kept},
        )
    with op.batch_alter_table("media_collections") as batch:
        batch.drop_constraint("ck_media_collections_server_type", type_="check")
        batch.drop_column("server_type")
    with op.batch_alter_table("collection_groups") as batch:
        batch.drop_constraint("uq_collection_group", type_="unique")
        batch.drop_constraint("ck_collection_groups_server_type", type_="check")
        batch.drop_column("server_type")
        batch.create_unique_constraint("uq_collection_group", ["name"])


def downgrade() -> None:
    """Restore the column, naming Plex as every row's server.

    Which server the collections belong to is not recorded, so a downgrade on
    Jellyfin or Emby leaves them hidden until they are set to that server.
    """
    with op.batch_alter_table("collection_groups") as batch:
        batch.drop_constraint("uq_collection_group", type_="unique")
        batch.add_column(
            sa.Column(
                "server_type",
                sa.Enum(
                    "plex", "jellyfin", "emby", name="servertype", native_enum=False
                ),
                nullable=False,
                server_default="plex",
            )
        )
        batch.create_check_constraint(
            "ck_collection_groups_server_type", f"server_type IN {_SERVERS}"
        )
        batch.create_unique_constraint("uq_collection_group", ["server_type", "name"])
    with op.batch_alter_table("media_collections") as batch:
        batch.add_column(
            sa.Column(
                "server_type",
                sa.Enum(
                    "plex", "jellyfin", "emby", name="servertype", native_enum=False
                ),
                nullable=False,
                server_default="plex",
            )
        )
        batch.create_check_constraint(
            "ck_media_collections_server_type", f"server_type IN {_SERVERS}"
        )
    for table in ("collection_groups", "media_collections"):
        with op.batch_alter_table(table) as batch:
            batch.alter_column("server_type", server_default=None)
