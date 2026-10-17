"""Baseline schema.

Revision ID: 1
Revises:
Create Date: 2026-10-16 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

# revision identifiers, used by Alembic.
revision: str = "1"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "app_settings",
        sa.Column("auto_match_art", sa.Boolean(), nullable=False),
        sa.Column("workflow", auto_string(length=14), nullable=False),
        sa.Column("theme_search_format", auto_string(length=200), nullable=False),
        sa.Column("min_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("normalize_theme_loudness", sa.Boolean(), nullable=False),
        sa.Column("initial_results", sa.Integer(), nullable=False),
        sa.Column("load_more_step", sa.Integer(), nullable=False),
        sa.Column("skip_media_server_tmdb_urls", sa.Boolean(), nullable=False),
        sa.Column("disable_media_server_art", sa.Boolean(), nullable=False),
        sa.Column("aspect_ratio_tolerance", auto_string(length=7), nullable=False),
        sa.Column("plex_collections_enabled", sa.Boolean(), nullable=False),
        sa.Column("tmdb_language_filter", auto_string(length=7), nullable=False),
        sa.Column("auto_advance", sa.Boolean(), nullable=False),
        sa.Column("auto_advance_skip_completed", sa.Boolean(), nullable=False),
        sa.Column("auto_unmonitor", auto_string(length=13), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "auto_unmonitor IN "
            "('off', 'art', 'theme', 'art_or_theme', 'art_and_theme')",
            name="ck_app_settings_auto_unmonitor",
        ),
        sa.CheckConstraint(
            "aspect_ratio_tolerance IN ('strict', 'lenient', 'off')",
            name="ck_app_settings_aspect_ratio_tolerance",
        ),
        sa.CheckConstraint(
            "workflow IN ('art', 'art_and_themes', 'themes')",
            name="ck_app_settings_workflow",
        ),
        sa.CheckConstraint(
            "tmdb_language_filter IN ('en_null', 'all')",
            name="ck_app_settings_tmdb_language_filter",
        ),
        sa.CheckConstraint("id = 1", name="ck_app_settings_singleton"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "auth_sessions",
        sa.Column("token_hash", auto_string(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("oidc_issuer", auto_string(), nullable=True),
        sa.Column("credential_fingerprint", auto_string(), nullable=True),
        sa.Column("id_token", auto_string(), nullable=True),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table(
        "task_schedule",
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cron_expression", auto_string(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("task_name", auto_string(), nullable=False),
        sa.PrimaryKeyConstraint("task_name"),
    )
    op.create_table(
        "saved_schedules",
        sa.Column("kind", auto_string(length=6), nullable=False),
        sa.Column("name", auto_string(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cron_expression", auto_string(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('assets', 'sync')", name="ck_saved_schedules_kind"
        ),
        sa.UniqueConstraint("kind", "name", name="uq_saved_schedules_kind_name"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_saved_schedules_enabled", "saved_schedules", ["enabled"])
    op.create_index(
        "ix_saved_schedules_enabled_kind", "saved_schedules", ["enabled", "kind"]
    )
    op.create_index("ix_saved_schedules_kind", "saved_schedules", ["kind"])
    op.create_index(
        "ix_saved_schedules_kind_created",
        "saved_schedules",
        ["kind", "created_at", "id"],
    )
    op.create_table(
        "job_runs",
        sa.Column("id", auto_string(), nullable=False),
        sa.Column("kind", auto_string(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("event", auto_string(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("total", sa.Integer(), nullable=False),
        sa.Column("cleared", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_runs_kind", "job_runs", ["kind"])
    op.create_index("ix_job_runs_finished_at", "job_runs", ["finished_at"])
    op.create_table(
        "job_results",
        sa.Column("run_id", auto_string(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["job_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "ordinal"),
    )
    op.create_table(
        "media_items",
        sa.Column("media_type", auto_string(length=5), nullable=False),
        sa.Column("title", auto_string(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("tvdb_id", sa.Integer(), nullable=True),
        sa.Column("imdb_id", auto_string(), nullable=True),
        sa.Column("folder_path", auto_string(), nullable=True),
        sa.Column("server_item_id", auto_string(), nullable=True),
        sa.Column("server_link", auto_string(), nullable=True),
        sa.Column("server_verified_at", sa.DateTime(), nullable=True),
        sa.Column("library_id", auto_string(), nullable=True),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("youtube_id", auto_string(), nullable=True),
        sa.Column("youtube_id_source", auto_string(length=12), nullable=True),
        sa.Column("youtube_title", auto_string(), nullable=True),
        sa.Column("youtube_duration", sa.Integer(), nullable=True),
        sa.Column("theme_file_hash", auto_string(), nullable=True),
        sa.Column("director", auto_string(), nullable=True),
        sa.Column("studio", auto_string(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_matched_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("server_added_at", sa.DateTime(), nullable=True),
        sa.Column("server_removed_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("director_etag", auto_string(), nullable=True),
        sa.Column("theme_file_mtime_ns", sa.Integer(), nullable=True),
        sa.Column("theme_file_size", sa.Integer(), nullable=True),
        sa.Column("theme_provenance_cleared", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_media_items_media_type"
        ),
        sa.CheckConstraint(
            "youtube_id_source IN ("
            "'download', 'embedded_id', 'source_url', 'metadata_url', 'selection'"
            ")",
            name="ck_media_items_youtube_id_source",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_media_items_imdb_identity", "media_items", ["media_type", "imdb_id"]
    )
    op.create_index("ix_media_items_folder_path", "media_items", ["folder_path"])
    op.create_index("ix_media_items_library_id", "media_items", ["library_id"])
    op.create_index(
        "ix_media_items_title_year", "media_items", ["media_type", "title", "year"]
    )
    op.create_index(
        "ix_media_items_tmdb_identity", "media_items", ["media_type", "tmdb_id"]
    )
    op.create_index(
        "ix_media_items_monitored_library", "media_items", ["monitored", "library_id"]
    )
    op.create_index("ix_media_items_media_type", "media_items", ["media_type"])
    op.create_index("ix_media_items_tmdb_id", "media_items", ["tmdb_id"])
    op.create_index("ix_media_items_server_item_id", "media_items", ["server_item_id"])
    op.create_index(
        "ix_media_items_tvdb_identity", "media_items", ["media_type", "tvdb_id"]
    )
    op.create_index(
        "ix_media_items_visible_title", "media_items", ["server_removed_at", "title"]
    )
    op.create_index("ix_media_items_title", "media_items", ["title"])
    op.create_index(
        "ix_media_items_server_identity",
        "media_items",
        ["media_type", "server_item_id"],
    )
    op.create_index(
        "ix_media_items_visible_library",
        "media_items",
        ["server_removed_at", "library_id"],
    )
    op.create_table(
        "seasons",
        sa.Column("media_item_id", sa.Integer(), nullable=False),
        sa.Column("season_num", sa.Integer(), nullable=False),
        sa.Column("title", auto_string(), nullable=True),
        sa.Column("server_item_id", auto_string(), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=False),
        sa.Column("folder_path", auto_string(), nullable=True),
        sa.Column("last_matched_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint("media_item_id", "season_num", name="uq_season"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_seasons_item_number_files",
        "seasons",
        ["media_item_id", "season_num", "file_count"],
    )
    op.create_index("ix_seasons_media_item_id", "seasons", ["media_item_id"])
    op.create_index("ix_seasons_item_files", "seasons", ["media_item_id", "file_count"])
    op.create_table(
        "art_slots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_item_id", sa.Integer(), nullable=True),
        sa.Column("season_id", sa.Integer(), nullable=True),
        sa.Column("art_type", auto_string(length=13), nullable=False),
        sa.Column("url", auto_string(), nullable=True),
        sa.Column("file_hash", auto_string(), nullable=True),
        sa.Column("phash", auto_string(), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("file_mtime_ns", sa.Integer(), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "art_type IN ('poster', 'background', 'season_poster')",
            name="ck_art_slots_art_type",
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "media_item_id", "art_type", name="uq_art_slots_media_item"
        ),
        sa.UniqueConstraint("season_id", "art_type", name="uq_art_slots_season"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_art_slots_season_id", "art_slots", ["season_id"])
    op.create_index("ix_art_slots_media_item_id", "art_slots", ["media_item_id"])
    op.create_table(
        "collection_themes",
        sa.Column("server_item_id", auto_string(), nullable=False),
        sa.Column("media_type", auto_string(length=5), nullable=False),
        sa.Column("server_type", auto_string(length=8), nullable=False),
        sa.Column("youtube_id", auto_string(), nullable=True),
        sa.Column("youtube_title", auto_string(), nullable=True),
        sa.Column("youtube_duration", sa.Integer(), nullable=True),
        sa.Column("server_theme_id", auto_string(), nullable=True),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_collection_themes_media_type"
        ),
        sa.CheckConstraint(
            "server_type IN ('plex', 'jellyfin', 'emby')",
            name="ck_collection_themes_server_type",
        ),
        sa.UniqueConstraint(
            "server_item_id", "media_type", name="uq_collection_theme_server_media"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_collection_themes_server_item_id", "collection_themes", ["server_item_id"]
    )
    op.create_index(
        "ix_collection_themes_media_type", "collection_themes", ["media_type"]
    )
    op.create_index(
        "ix_collection_themes_server_media",
        "collection_themes",
        ["server_item_id", "media_type"],
    )
    op.create_table(
        "download_jobs",
        sa.Column("media_item_id", sa.Integer(), nullable=True),
        sa.Column("job_type", auto_string(length=16), nullable=False),
        sa.Column("art_type", auto_string(length=13), nullable=True),
        sa.Column("target_url", auto_string(), nullable=True),
        sa.Column("season_id", sa.Integer(), nullable=True),
        sa.Column("collection_server_id", auto_string(), nullable=True),
        sa.Column("collection_media_type", auto_string(length=5), nullable=True),
        sa.Column("collection_title", auto_string(), nullable=True),
        sa.Column("status", auto_string(length=9), nullable=False),
        sa.Column("progress_percent", sa.Float(), nullable=False),
        sa.Column("error_message", auto_string(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("id", auto_string(), nullable=False),
        sa.Column("selection_state", sa.Text(), nullable=True),
        sa.Column("write_intent", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "collection_media_type IN ('movie', 'show')",
            name="ck_download_jobs_collection_media_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed', 'cancelled')",
            name="ck_download_jobs_status",
        ),
        sa.CheckConstraint(
            "art_type IN ('poster', 'background', 'season_poster')",
            name="ck_download_jobs_art_type",
        ),
        sa.CheckConstraint(
            "job_type IN ('art', 'theme', 'collection_theme')",
            name="ck_download_jobs_job_type",
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_download_jobs_collection_server_id",
        "download_jobs",
        ["collection_server_id"],
    )
    op.create_index(
        "ix_download_jobs_status_created", "download_jobs", ["status", "created_at"]
    )
    op.create_index("ix_download_jobs_status", "download_jobs", ["status"])
    op.create_index(
        "ix_download_jobs_active_equivalent",
        "download_jobs",
        ["media_item_id", "job_type", "art_type", "target_url", "season_id", "status"],
    )
    op.create_index(
        "ix_download_jobs_media_item_id", "download_jobs", ["media_item_id"]
    )
    op.create_table(
        "public_dataset_items",
        sa.Column("media_type", auto_string(length=5), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("tvdb_id", sa.Integer(), nullable=True),
        sa.Column("imdb_id", auto_string(), nullable=True),
        sa.Column("title", auto_string(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("poster_url", auto_string(), nullable=True),
        sa.Column("background_url", auto_string(), nullable=True),
        sa.Column("youtube_id_overturedb", auto_string(), nullable=True),
        sa.Column("youtube_id_themerrdb", auto_string(), nullable=True),
        sa.Column("catalog_synced_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_public_dataset_items_media_type"
        ),
        sa.CheckConstraint(
            "youtube_id_overturedb IS NULL "
            "OR youtube_id_themerrdb IS NULL "
            "OR youtube_id_overturedb != youtube_id_themerrdb",
            name="ck_public_dataset_different_youtube_ids",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_public_dataset_items_media_type", "public_dataset_items", ["media_type"]
    )
    op.create_index(
        "ix_public_dataset_items_tmdb_id", "public_dataset_items", ["tmdb_id"]
    )
    op.create_index(
        "ix_public_dataset_item_tmdb", "public_dataset_items", ["media_type", "tmdb_id"]
    )
    op.create_index(
        "ix_public_dataset_items_tvdb_id", "public_dataset_items", ["tvdb_id"]
    )
    op.create_index(
        "ix_public_dataset_items_imdb_id", "public_dataset_items", ["imdb_id"]
    )
    op.create_index(
        "ix_public_dataset_item_tvdb", "public_dataset_items", ["media_type", "tvdb_id"]
    )
    op.create_index(
        "ix_public_dataset_item_imdb", "public_dataset_items", ["media_type", "imdb_id"]
    )
    op.create_table(
        "public_dataset_seasons",
        sa.Column("public_dataset_item_id", sa.Integer(), nullable=False),
        sa.Column("season_num", sa.Integer(), nullable=False),
        sa.Column("poster_url", auto_string(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["public_dataset_item_id"], ["public_dataset_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_public_dataset_seasons_season_num", "public_dataset_seasons", ["season_num"]
    )
    op.create_index(
        "ix_public_dataset_season_item_number",
        "public_dataset_seasons",
        ["public_dataset_item_id", "season_num"],
        unique=True,
    )
    op.create_index(
        "ix_public_dataset_seasons_public_dataset_item_id",
        "public_dataset_seasons",
        ["public_dataset_item_id"],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(
        "ix_public_dataset_seasons_season_num", table_name="public_dataset_seasons"
    )
    op.drop_index(
        "ix_public_dataset_season_item_number", table_name="public_dataset_seasons"
    )
    op.drop_index(
        "ix_public_dataset_seasons_public_dataset_item_id",
        table_name="public_dataset_seasons",
    )
    op.drop_table("public_dataset_seasons")
    op.drop_index(
        "ix_public_dataset_items_media_type", table_name="public_dataset_items"
    )
    op.drop_index("ix_public_dataset_items_tmdb_id", table_name="public_dataset_items")
    op.drop_index("ix_public_dataset_item_tmdb", table_name="public_dataset_items")
    op.drop_index("ix_public_dataset_items_tvdb_id", table_name="public_dataset_items")
    op.drop_index("ix_public_dataset_items_imdb_id", table_name="public_dataset_items")
    op.drop_index("ix_public_dataset_item_tvdb", table_name="public_dataset_items")
    op.drop_index("ix_public_dataset_item_imdb", table_name="public_dataset_items")
    op.drop_table("public_dataset_items")
    op.drop_index("ix_download_jobs_collection_server_id", table_name="download_jobs")
    op.drop_index("ix_download_jobs_status_created", table_name="download_jobs")
    op.drop_index("ix_download_jobs_status", table_name="download_jobs")
    op.drop_index("ix_download_jobs_active_equivalent", table_name="download_jobs")
    op.drop_index("ix_download_jobs_media_item_id", table_name="download_jobs")
    op.drop_table("download_jobs")
    op.drop_index("ix_collection_themes_server_item_id", table_name="collection_themes")
    op.drop_index("ix_collection_themes_media_type", table_name="collection_themes")
    op.drop_index("ix_collection_themes_server_media", table_name="collection_themes")
    op.drop_table("collection_themes")
    op.drop_index("ix_art_slots_season_id", table_name="art_slots")
    op.drop_index("ix_art_slots_media_item_id", table_name="art_slots")
    op.drop_table("art_slots")
    op.drop_index("ix_seasons_item_number_files", table_name="seasons")
    op.drop_index("ix_seasons_media_item_id", table_name="seasons")
    op.drop_index("ix_seasons_item_files", table_name="seasons")
    op.drop_table("seasons")
    op.drop_index("ix_media_items_imdb_identity", table_name="media_items")
    op.drop_index("ix_media_items_folder_path", table_name="media_items")
    op.drop_index("ix_media_items_library_id", table_name="media_items")
    op.drop_index("ix_media_items_title_year", table_name="media_items")
    op.drop_index("ix_media_items_tmdb_identity", table_name="media_items")
    op.drop_index("ix_media_items_monitored_library", table_name="media_items")
    op.drop_index("ix_media_items_media_type", table_name="media_items")
    op.drop_index("ix_media_items_tmdb_id", table_name="media_items")
    op.drop_index("ix_media_items_server_item_id", table_name="media_items")
    op.drop_index("ix_media_items_tvdb_identity", table_name="media_items")
    op.drop_index("ix_media_items_visible_title", table_name="media_items")
    op.drop_index("ix_media_items_title", table_name="media_items")
    op.drop_index("ix_media_items_server_identity", table_name="media_items")
    op.drop_index("ix_media_items_visible_library", table_name="media_items")
    op.drop_table("media_items")
    op.drop_table("job_results")
    op.drop_index("ix_job_runs_kind", table_name="job_runs")
    op.drop_index("ix_job_runs_finished_at", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_index("ix_saved_schedules_enabled", table_name="saved_schedules")
    op.drop_index("ix_saved_schedules_enabled_kind", table_name="saved_schedules")
    op.drop_index("ix_saved_schedules_kind", table_name="saved_schedules")
    op.drop_index("ix_saved_schedules_kind_created", table_name="saved_schedules")
    op.drop_table("saved_schedules")
    op.drop_table("task_schedule")
    op.drop_index("ix_auth_sessions_expires_at", table_name="auth_sessions")
    op.drop_table("auth_sessions")
    op.drop_table("app_settings")
