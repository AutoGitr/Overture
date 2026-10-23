"""Stable collection targets, local theme facts and source provenance.

Revision ID: 3
Revises: 2
"""

import json
import re
from collections.abc import Sequence
from typing import Any, cast

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "3"
down_revision: str | Sequence[str] | None = "2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _collection_id(server_id: str, media_type: str, title: str = "") -> int:
    connection = op.get_bind()
    found = connection.execute(
        sa.text(
            "SELECT id FROM media_collections WHERE "
            "server_item_id=:server_id AND media_type=:media_type"
        ),
        {"server_id": server_id, "media_type": media_type},
    ).scalar_one_or_none()
    if found is not None:
        return int(found)
    # Keep historical targets even if an earlier sync removed their collection.
    server_type = (
        "jellyfin" if re.fullmatch(r"[0-9a-fA-F-]{32,36}", server_id) else "plex"
    )
    connection.execute(
        sa.text(
            "INSERT INTO media_collections (server_item_id, media_type, "
            "server_type, title, child_count, tmdb_match, monitored) VALUES "
            "(:server_id, :media_type, :server_type, :title, 0, 'auto', 1)"
        ),
        {
            "server_id": server_id,
            "media_type": media_type,
            "server_type": server_type,
            "title": title,
        },
    )
    return int(connection.execute(sa.text("SELECT last_insert_rowid()")).scalar_one())


def _rewrite(value: Any, *, upgrade: bool) -> Any:
    if isinstance(value, list):
        return [_rewrite(item, upgrade=upgrade) for item in cast("list[Any]", value)]
    if not isinstance(value, dict):
        return value
    result = {
        key: _rewrite(item, upgrade=upgrade)
        for key, item in cast("dict[str, Any]", value).items()
    }
    if upgrade and result.get("collection_server_id") is not None:
        result["collection_id"] = _collection_id(
            str(result.pop("collection_server_id")),
            str(result.pop("media_type", "movie")),
            str(result.get("title") or ""),
        )
    elif (
        not upgrade
        and result.get("target_type") == "collection_theme"
        and result.get("collection_id") is not None
    ):
        row = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT server_item_id, media_type FROM "
                    "media_collections WHERE id=:id"
                ),
                {"id": result.pop("collection_id")},
            )
            .first()
        )
        if row is not None:
            result.update(collection_server_id=row[0], media_type=row[1])
    return result


def _history(*, upgrade: bool) -> None:
    connection = op.get_bind()
    for row in connection.execute(
        sa.text("SELECT run_id, ordinal, payload FROM job_results")
    ).all():
        payload = json.loads(row[2])
        changed = _rewrite(payload, upgrade=upgrade)
        if changed != payload:
            connection.execute(
                sa.text(
                    "UPDATE job_results SET payload=:payload WHERE "
                    "run_id=:run_id AND ordinal=:ordinal"
                ),
                {"payload": json.dumps(changed), "run_id": row[0], "ordinal": row[1]},
            )


def upgrade() -> None:
    """Preserve theme choices and history while linking jobs to collections."""
    with op.batch_alter_table("media_collections") as batch:
        batch.add_column(
            sa.Column("youtube_id_source", auto_string(length=14), nullable=True)
        )
        batch.add_column(sa.Column("theme_file_hash", auto_string(), nullable=True))
        batch.add_column(sa.Column("theme_file_mtime_ns", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("theme_file_size", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("theme_file_duration", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("last_matched_at", sa.DateTime(), nullable=True))
        batch.create_check_constraint(
            "ck_media_collections_youtube_id_source",
            "youtube_id_source IN ('overturedb', 'themerrdb', 'youtube_search')",
        )
    # A stat fingerprint is not a hash. Preserve the selection and re-inspect
    # Jellyfin files on the next sync, without putting it in the Plex field.
    op.execute(
        "UPDATE media_collections SET server_theme_id=NULL WHERE server_type='jellyfin'"
    )
    with op.batch_alter_table("download_jobs") as batch:
        batch.add_column(sa.Column("collection_id", sa.Integer(), nullable=True))
    connection = op.get_bind()
    for row in connection.execute(
        sa.text(
            "SELECT id, collection_server_id, collection_media_type, "
            "collection_title FROM download_jobs WHERE collection_server_id "
            "IS NOT NULL"
        )
    ).all():
        collection_id = _collection_id(row[1], row[2] or "movie", row[3] or "")
        connection.execute(
            sa.text(
                "UPDATE download_jobs SET collection_id=:collection_id WHERE id=:id"
            ),
            {"collection_id": collection_id, "id": row[0]},
        )
    _history(upgrade=True)
    with op.batch_alter_table("download_jobs") as batch:
        batch.drop_index("ix_download_jobs_collection_server_id")
        batch.drop_constraint("ck_download_jobs_collection_media_type", type_="check")
        batch.drop_column("collection_server_id")
        batch.drop_column("collection_media_type")
        batch.create_foreign_key(
            "fk_download_jobs_collection_id",
            "media_collections",
            ["collection_id"],
            ["id"],
            ondelete="CASCADE",
        )
        batch.create_index("ix_download_jobs_collection_id", ["collection_id"])
    with op.batch_alter_table("media_collections") as batch:
        batch.drop_constraint("uq_media_collection_server_media", type_="unique")
        batch.create_unique_constraint(
            "uq_media_collection_server_item", ["server_type", "server_item_id"]
        )
    with op.batch_alter_table("app_settings") as batch:
        batch.drop_column("collections_enabled")


def downgrade() -> None:
    """Restore provider targets; revision 2 has no theme-file/source columns."""
    _history(upgrade=False)
    with op.batch_alter_table("app_settings") as batch:
        batch.add_column(
            sa.Column(
                "collections_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            )
        )
    with op.batch_alter_table("download_jobs") as batch:
        batch.add_column(
            sa.Column("collection_server_id", auto_string(), nullable=True)
        )
        batch.add_column(
            sa.Column("collection_media_type", auto_string(length=5), nullable=True)
        )
        batch.create_check_constraint(
            "ck_download_jobs_collection_media_type",
            "collection_media_type IN ('movie', 'show')",
        )
    op.execute(
        "UPDATE download_jobs SET collection_server_id=(SELECT "
        "server_item_id FROM media_collections WHERE id=collection_id), "
        "collection_media_type=(SELECT media_type FROM media_collections "
        "WHERE id=collection_id) WHERE collection_id IS NOT NULL"
    )
    with op.batch_alter_table("download_jobs") as batch:
        batch.drop_index("ix_download_jobs_collection_id")
        batch.drop_constraint("fk_download_jobs_collection_id", type_="foreignkey")
        batch.drop_column("collection_id")
        batch.create_index(
            "ix_download_jobs_collection_server_id", ["collection_server_id"]
        )
    with op.batch_alter_table("media_collections") as batch:
        batch.drop_constraint("uq_media_collection_server_item", type_="unique")
        batch.create_unique_constraint(
            "uq_media_collection_server_media", ["server_item_id", "media_type"]
        )
        batch.drop_constraint("ck_media_collections_youtube_id_source", type_="check")
        for name in (
            "youtube_id_source",
            "theme_file_hash",
            "theme_file_mtime_ns",
            "theme_file_size",
            "theme_file_duration",
            "last_matched_at",
        ):
            batch.drop_column(name)
