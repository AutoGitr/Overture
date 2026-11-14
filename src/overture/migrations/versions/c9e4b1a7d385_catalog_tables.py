"""Name OvertureDB's tables, job kind and schedule after the catalog.

The catalog's tables, their indexes and constraints, the job kind its sync
runs as, and the schedule that starts the sync take the name ``catalog``.
Run history and notification rules keep their rows under the new kind.

Revision ID: c9e4b1a7d385
Revises: d2a7f5c3e9b1
Create Date: 2026-11-13 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9e4b1a7d385"
down_revision: str | Sequence[str] | None = "d2a7f5c3e9b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: A name before and after this revision.
type Names = tuple[str, str]
type Check = tuple[Names, str]
type IndexSpec = tuple[Names, tuple[str, ...], bool]

_YOUTUBE_IDS_DIFFER = (
    "youtube_id_overturedb IS NULL OR youtube_id_themerrdb IS NULL "
    "OR youtube_id_overturedb != youtube_id_themerrdb"
)
#: The seasons' link to their item, renamed with its table.
_ITEM_COLUMN: Names = ("public_dataset_item_id", "catalog_item_id")
_SEASONS: Names = ("public_dataset_seasons", "catalog_item_seasons")

_TABLES: tuple[tuple[Names, tuple[Check, ...], tuple[IndexSpec, ...]], ...] = (
    (
        ("public_dataset_items", "catalog_items"),
        (
            (
                ("ck_public_dataset_items_media_type", "ck_catalog_items_media_type"),
                "media_type IN ('movie', 'show')",
            ),
            (
                (
                    "ck_public_dataset_different_youtube_ids",
                    "ck_catalog_item_different_youtube_ids",
                ),
                _YOUTUBE_IDS_DIFFER,
            ),
        ),
        (
            (
                ("ix_public_dataset_item_imdb", "ix_catalog_item_imdb"),
                ("media_type", "imdb_id"),
                False,
            ),
            (
                ("ix_public_dataset_item_tmdb", "ix_catalog_item_tmdb"),
                ("media_type", "tmdb_id"),
                False,
            ),
            (
                ("ix_public_dataset_item_tvdb", "ix_catalog_item_tvdb"),
                ("media_type", "tvdb_id"),
                False,
            ),
            (
                ("ix_public_dataset_items_imdb_id", "ix_catalog_items_imdb_id"),
                ("imdb_id",),
                False,
            ),
            (
                ("ix_public_dataset_items_media_type", "ix_catalog_items_media_type"),
                ("media_type",),
                False,
            ),
            (
                ("ix_public_dataset_items_tmdb_id", "ix_catalog_items_tmdb_id"),
                ("tmdb_id",),
                False,
            ),
            (
                ("ix_public_dataset_items_tvdb_id", "ix_catalog_items_tvdb_id"),
                ("tvdb_id",),
                False,
            ),
        ),
    ),
    (
        _SEASONS,
        (),
        (
            (
                (
                    "ix_public_dataset_season_item_number",
                    "ix_catalog_item_season_number",
                ),
                ("{item}", "season_num"),
                True,
            ),
            (
                (
                    "ix_public_dataset_seasons_public_dataset_item_id",
                    "ix_catalog_item_seasons_catalog_item_id",
                ),
                ("{item}",),
                False,
            ),
            (
                (
                    "ix_public_dataset_seasons_season_num",
                    "ix_catalog_item_seasons_season_num",
                ),
                ("season_num",),
                False,
            ),
        ),
    ),
    (
        ("public_dataset_collections", "catalog_collections"),
        (
            (
                (
                    "ck_public_dataset_collection_different_youtube_ids",
                    "ck_catalog_collection_different_youtube_ids",
                ),
                _YOUTUBE_IDS_DIFFER,
            ),
        ),
        (),
    ),
    (
        ("public_dataset_drafts", "catalog_drafts"),
        (
            (
                ("ck_public_dataset_drafts_media_type", "ck_catalog_drafts_media_type"),
                "media_type IN ('movie', 'show', 'collection')",
            ),
            (
                ("ck_public_dataset_drafts_entry_json", "ck_catalog_drafts_entry_json"),
                "json_valid(entry)",
            ),
        ),
        (
            (
                ("ix_public_dataset_drafts_imdb_id", "ix_catalog_drafts_imdb_id"),
                ("imdb_id",),
                False,
            ),
            (
                ("ix_public_dataset_drafts_media_type", "ix_catalog_drafts_media_type"),
                ("media_type",),
                False,
            ),
            (
                ("ix_public_dataset_drafts_tmdb_id", "ix_catalog_drafts_tmdb_id"),
                ("tmdb_id",),
                False,
            ),
            (
                ("ix_public_dataset_drafts_tvdb_id", "ix_catalog_drafts_tvdb_id"),
                ("tvdb_id",),
                False,
            ),
        ),
    ),
)
_JOB_KIND: Names = ("public_dataset_sync", "catalog_sync")
_EVENT_PREFIX: Names = ("public-dataset.", "catalog.")
_SCHEDULE: Names = ("public_dataset", "catalog")


def _rename(old: int, new: int) -> None:
    """Rename everything from its name at index *old* to its name at *new*."""
    for table, checks, indexes in _TABLES:
        for names, _, _ in indexes:
            op.drop_index(names[old], table_name=table[old])
        op.rename_table(table[old], table[new])
        with op.batch_alter_table(table[new], recreate="always") as batch:
            if table == _SEASONS:
                batch.alter_column(_ITEM_COLUMN[old], new_column_name=_ITEM_COLUMN[new])
            for names, rule in checks:
                batch.drop_constraint(names[old], type_="check")
                batch.create_check_constraint(names[new], rule)
        for names, columns, unique in indexes:
            op.create_index(
                names[new],
                table[new],
                [column.format(item=_ITEM_COLUMN[new]) for column in columns],
                unique=unique,
            )
    kinds = {"old_kind": _JOB_KIND[old], "new_kind": _JOB_KIND[new]}
    op.execute(
        sa.text(
            "UPDATE job_runs SET kind = :new_kind, "
            "event = :new_prefix || substr(event, length(:old_prefix) + 1) "
            "WHERE kind = :old_kind"
        ).bindparams(
            **kinds, old_prefix=_EVENT_PREFIX[old], new_prefix=_EVENT_PREFIX[new]
        )
    )
    op.execute(
        sa.text(
            "UPDATE notification_rules SET kind = :new_kind WHERE kind = :old_kind"
        ).bindparams(**kinds)
    )
    op.execute(
        sa.text(
            "UPDATE task_schedule SET task_name = :new WHERE task_name = :old"
        ).bindparams(old=_SCHEDULE[old], new=_SCHEDULE[new])
    )


def upgrade() -> None:
    _rename(0, 1)


def downgrade() -> None:
    _rename(1, 0)
