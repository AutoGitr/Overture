"""Baseline schema.

Revision ID: d55c703635bb
Revises:
Create Date: 2026-11-03 17:38:09.819982

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from overture.migrations.sqltypes import auto_string

revision: str = "d55c703635bb"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", auto_string(), nullable=False),
        sa.Column("key_hash", auto_string(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key_hash"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "app_settings",
        sa.Column(
            "collection_sync_mode",
            sa.Enum("sync", "append", name="syncmode", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "collection_mode_default",
            sa.Enum(
                "default",
                "hide_items",
                "show_items",
                "hide",
                name="collectionmode",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "collection_order_default",
            sa.Enum(
                "custom",
                "release.asc",
                "release.desc",
                "title.asc",
                "title.desc",
                "added.desc",
                "added.asc",
                "critic_rating.desc",
                "critic_rating.asc",
                "audience_rating.desc",
                "audience_rating.asc",
                "user_rating.desc",
                "user_rating.asc",
                "duration.desc",
                "duration.asc",
                "plays.desc",
                "plays.asc",
                "last_played.desc",
                "last_played.asc",
                "random",
                name="collectionorder",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "collection_filtering_default",
            sa.Enum("admin", "user", name="collectionfiltering", native_enum=False),
            nullable=False,
        ),
        sa.Column("collection_visible_home", sa.Boolean(), nullable=False),
        sa.Column("collection_visible_shared", sa.Boolean(), nullable=False),
        sa.Column("collection_visible_library", sa.Boolean(), nullable=False),
        sa.Column("collection_minimum_items", sa.Integer(), nullable=False),
        sa.Column("collection_delete_below_minimum", sa.Boolean(), nullable=False),
        sa.Column("collection_auto_match_art", sa.Boolean(), nullable=False),
        sa.Column("collection_auto_match_theme", sa.Boolean(), nullable=False),
        sa.Column(
            "collection_sort_title_format", auto_string(length=200), nullable=False
        ),
        sa.Column(
            "collection_summary_format", auto_string(length=2000), nullable=False
        ),
        sa.Column("collection_delete_when_inactive", sa.Boolean(), nullable=False),
        sa.Column("collection_sync_schedule", auto_string(length=100), nullable=False),
        sa.Column("collection_sync_enabled", sa.Boolean(), nullable=False),
        sa.Column("collection_request_missing", sa.Boolean(), nullable=False),
        sa.Column("collection_import_unmanaged", sa.Boolean(), nullable=False),
        sa.Column("overturedb_no_theme", sa.Boolean(), nullable=False),
        sa.Column("overturedb_browse", sa.Boolean(), nullable=False),
        sa.Column("tmdb_region", auto_string(length=2), nullable=False),
        sa.Column("radarr_root_folder", auto_string(length=500), nullable=False),
        sa.Column("radarr_quality_profile_id", sa.Integer(), nullable=True),
        sa.Column("radarr_search", sa.Boolean(), nullable=False),
        sa.Column("sonarr_root_folder", auto_string(length=500), nullable=False),
        sa.Column("sonarr_quality_profile_id", sa.Integer(), nullable=True),
        sa.Column("sonarr_search", sa.Boolean(), nullable=False),
        sa.Column("auto_match_art", sa.Boolean(), nullable=False),
        sa.Column(
            "workflow",
            sa.Enum(
                "art", "art_and_themes", "themes", name="workflow", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column("theme_search_format", auto_string(length=200), nullable=False),
        sa.Column("min_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("max_duration_seconds", sa.Integer(), nullable=False),
        sa.Column("normalize_theme_loudness", sa.Boolean(), nullable=False),
        sa.Column("skip_media_server_tmdb_urls", sa.Boolean(), nullable=False),
        sa.Column("disable_media_server_art", sa.Boolean(), nullable=False),
        sa.Column(
            "aspect_ratio_tolerance",
            sa.Enum(
                "strict",
                "lenient",
                "off",
                name="aspectratiotolerance",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "tmdb_language_filter",
            sa.Enum("en_null", "all", name="tmdblanguagefilter", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "auto_advance",
            sa.Enum(
                "off", "slots", "slots_and_items", name="autoadvance", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column("auto_advance_skip_completed", sa.Boolean(), nullable=False),
        sa.Column(
            "auto_unmonitor",
            sa.Enum(
                "off",
                "art",
                "theme",
                "art_or_theme",
                "art_and_theme",
                name="autounmonitor",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "aspect_ratio_tolerance IN ('strict', 'lenient', 'off')",
            name="ck_app_settings_aspect_ratio_tolerance",
        ),
        sa.CheckConstraint(
            "auto_advance IN ('off', 'slots', 'slots_and_items')",
            name="ck_app_settings_auto_advance",
        ),
        sa.CheckConstraint(
            "auto_unmonitor IN "
            "('off', 'art', 'theme', 'art_or_theme', 'art_and_theme')",
            name="ck_app_settings_auto_unmonitor",
        ),
        sa.CheckConstraint(
            "collection_filtering_default IN ('admin', 'user')",
            name="ck_app_settings_collection_filtering_default",
        ),
        sa.CheckConstraint(
            "collection_mode_default IN "
            "('default', 'hide_items', 'show_items', 'hide')",
            name="ck_app_settings_collection_mode_default",
        ),
        sa.CheckConstraint(
            "collection_order_default IN ('custom', 'release.asc', 'release.desc', "
            "'title.asc', 'title.desc', 'added.desc', 'added.asc', "
            "'critic_rating.desc', 'critic_rating.asc', 'audience_rating.desc', "
            "'audience_rating.asc', 'user_rating.desc', 'user_rating.asc', "
            "'duration.desc', 'duration.asc', 'plays.desc', 'plays.asc', "
            "'last_played.desc', 'last_played.asc', 'random')",
            name="ck_app_settings_collection_order_default",
        ),
        sa.CheckConstraint(
            "collection_sync_mode IN ('sync', 'append')",
            name="ck_app_settings_collection_sync_mode",
        ),
        sa.CheckConstraint(
            "tmdb_language_filter IN ('en_null', 'all')",
            name="ck_app_settings_tmdb_language_filter",
        ),
        sa.CheckConstraint(
            "workflow IN ('art', 'art_and_themes', 'themes')",
            name="ck_app_settings_workflow",
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
        "collection_groups",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "server_type",
            sa.Enum("plex", "jellyfin", "emby", name="servertype", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "media_type",
            sa.Enum("movie", "show", name="mediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column("name", auto_string(), nullable=False),
        sa.Column(
            "sync_mode",
            sa.Enum("sync", "append", name="syncmode", native_enum=False),
            nullable=True,
        ),
        sa.Column("minimum_items", sa.Integer(), nullable=True),
        sa.Column("delete_below_minimum", sa.Boolean(), nullable=True),
        sa.Column(
            "collection_mode",
            sa.Enum(
                "default",
                "hide_items",
                "show_items",
                "hide",
                name="collectionmode",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "order_type",
            sa.Enum(
                "custom",
                "release.asc",
                "release.desc",
                "title.asc",
                "title.desc",
                "added.desc",
                "added.asc",
                "critic_rating.desc",
                "critic_rating.asc",
                "audience_rating.desc",
                "audience_rating.asc",
                "user_rating.desc",
                "user_rating.asc",
                "duration.desc",
                "duration.asc",
                "plays.desc",
                "plays.asc",
                "last_played.desc",
                "last_played.asc",
                "random",
                name="collectionorder",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "collection_filtering",
            sa.Enum("admin", "user", name="collectionfiltering", native_enum=False),
            nullable=True,
        ),
        sa.Column("visible_home", sa.Boolean(), nullable=True),
        sa.Column("visible_shared", sa.Boolean(), nullable=True),
        sa.Column("visible_library", sa.Boolean(), nullable=True),
        sa.Column("sort_title_format", auto_string(), nullable=True),
        sa.Column("summary_format", auto_string(), nullable=True),
        sa.Column("active_start_mmdd", auto_string(), nullable=True),
        sa.Column("active_end_mmdd", auto_string(), nullable=True),
        sa.Column("delete_when_inactive", sa.Boolean(), nullable=True),
        sa.Column("auto_match_art", sa.Boolean(), nullable=True),
        sa.Column("auto_match_theme", sa.Boolean(), nullable=True),
        sa.Column("sync_schedule", auto_string(), nullable=True),
        sa.Column("sync_enabled", sa.Boolean(), nullable=True),
        sa.Column("request_missing", sa.Boolean(), nullable=True),
        sa.Column("member_label", auto_string(), nullable=True),
        sa.Column("arr_tag", auto_string(), nullable=True),
        sa.Column("home_order", sa.Integer(), nullable=True),
        sa.Column("generator_json", auto_string(), nullable=True),
        sa.Column("generated_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "collection_filtering IN ('admin', 'user')",
            name="ck_collection_groups_collection_filtering",
        ),
        sa.CheckConstraint(
            "collection_mode IN ('default', 'hide_items', 'show_items', 'hide')",
            name="ck_collection_groups_collection_mode",
        ),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_collection_groups_media_type"
        ),
        sa.CheckConstraint(
            "order_type IN ('custom', 'release.asc', 'release.desc', 'title.asc', "
            "'title.desc', 'added.desc', 'added.asc', 'critic_rating.desc', "
            "'critic_rating.asc', 'audience_rating.desc', 'audience_rating.asc', "
            "'user_rating.desc', 'user_rating.asc', 'duration.desc', 'duration.asc', "
            "'plays.desc', 'plays.asc', 'last_played.desc', 'last_played.asc', "
            "'random')",
            name="ck_collection_groups_order_type",
        ),
        sa.CheckConstraint(
            "server_type IN ('plex', 'jellyfin', 'emby')",
            name="ck_collection_groups_server_type",
        ),
        sa.CheckConstraint(
            "sync_mode IN ('sync', 'append')", name="ck_collection_groups_sync_mode"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("server_type", "media_type", "name"),
    )
    op.create_table(
        "collection_presets",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "media_type",
            sa.Enum("movie", "show", name="mediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column("label", auto_string(), nullable=False),
        sa.Column("description", auto_string(), nullable=False),
        sa.Column("payload_json", auto_string(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_collection_presets_media_type"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_type", "label"),
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
        sa.Column("log_total", sa.Integer(), nullable=False),
        sa.Column("cleared", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_job_runs_finished_at", "job_runs", ["finished_at"])
    op.create_index("ix_job_runs_kind", "job_runs", ["kind"])
    op.create_table(
        "media_collections",
        sa.Column("server_item_id", auto_string(), nullable=True),
        sa.Column(
            "media_type",
            sa.Enum("movie", "show", name="mediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "server_type",
            sa.Enum("plex", "jellyfin", "emby", name="servertype", native_enum=False),
            nullable=False,
        ),
        sa.Column(
            "kind",
            sa.Enum("regular", "smart", name="collectionkind", native_enum=False),
            nullable=False,
        ),
        sa.Column("title", auto_string(), nullable=False),
        sa.Column("summary", auto_string(), nullable=True),
        sa.Column("summary_source", auto_string(), nullable=True),
        sa.Column("sort_title", auto_string(), nullable=True),
        sa.Column("sort_title_format", auto_string(), nullable=True),
        sa.Column("summary_format", auto_string(), nullable=True),
        sa.Column("collection_group", auto_string(), nullable=True),
        sa.Column(
            "collection_mode",
            sa.Enum(
                "default",
                "hide_items",
                "show_items",
                "hide",
                name="collectionmode",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "order_type",
            sa.Enum(
                "custom",
                "release.asc",
                "release.desc",
                "title.asc",
                "title.desc",
                "added.desc",
                "added.asc",
                "critic_rating.desc",
                "critic_rating.asc",
                "audience_rating.desc",
                "audience_rating.asc",
                "user_rating.desc",
                "user_rating.asc",
                "duration.desc",
                "duration.asc",
                "plays.desc",
                "plays.asc",
                "last_played.desc",
                "last_played.asc",
                "random",
                name="collectionorder",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "collection_filtering",
            sa.Enum("admin", "user", name="collectionfiltering", native_enum=False),
            nullable=True,
        ),
        sa.Column("visible_home", sa.Boolean(), nullable=False),
        sa.Column("visible_shared", sa.Boolean(), nullable=False),
        sa.Column("visible_library", sa.Boolean(), nullable=False),
        sa.Column("active_start_mmdd", auto_string(), nullable=True),
        sa.Column("active_end_mmdd", auto_string(), nullable=True),
        sa.Column("delete_when_inactive", sa.Boolean(), nullable=True),
        sa.Column("library_id", auto_string(), nullable=True),
        sa.Column("child_count", sa.Integer(), nullable=False),
        sa.Column("thumb_url", auto_string(), nullable=True),
        sa.Column("art_url", auto_string(), nullable=True),
        sa.Column("server_link", auto_string(), nullable=True),
        sa.Column("server_path", auto_string(), nullable=True),
        sa.Column("server_added_at", sa.DateTime(), nullable=True),
        sa.Column("provider_tmdb_id", sa.Integer(), nullable=True),
        sa.Column("tmdb_collection_id", sa.Integer(), nullable=True),
        sa.Column("generated_value", auto_string(), nullable=True),
        sa.Column("youtube_id", auto_string(), nullable=True),
        sa.Column(
            "youtube_id_source",
            sa.Enum(
                "overturedb",
                "themerrdb",
                "youtube_search",
                name="themebulksource",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("youtube_title", auto_string(), nullable=True),
        sa.Column("youtube_duration", sa.Integer(), nullable=True),
        sa.Column("server_theme_id", auto_string(), nullable=True),
        sa.Column("theme_file_hash", auto_string(), nullable=True),
        sa.Column("theme_file_mtime_ns", sa.Integer(), nullable=True),
        sa.Column("theme_file_size", sa.Integer(), nullable=True),
        sa.Column("theme_file_duration", sa.Integer(), nullable=True),
        sa.Column("last_matched_at", sa.DateTime(), nullable=True),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("unsynced", sa.Boolean(), nullable=False),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "collection_filtering IN ('admin', 'user')",
            name="ck_media_collections_collection_filtering",
        ),
        sa.CheckConstraint(
            "collection_mode IN ('default', 'hide_items', 'show_items', 'hide')",
            name="ck_media_collections_collection_mode",
        ),
        sa.CheckConstraint(
            "kind IN ('regular', 'smart')", name="ck_media_collections_kind"
        ),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_media_collections_media_type"
        ),
        sa.CheckConstraint(
            "order_type IN ('custom', 'release.asc', 'release.desc', 'title.asc', "
            "'title.desc', 'added.desc', 'added.asc', 'critic_rating.desc', "
            "'critic_rating.asc', 'audience_rating.desc', 'audience_rating.asc', "
            "'user_rating.desc', 'user_rating.asc', 'duration.desc', 'duration.asc', "
            "'plays.desc', 'plays.asc', 'last_played.desc', 'last_played.asc', "
            "'random')",
            name="ck_media_collections_order_type",
        ),
        sa.CheckConstraint(
            "server_type IN ('plex', 'jellyfin', 'emby')",
            name="ck_media_collections_server_type",
        ),
        sa.CheckConstraint(
            "youtube_id_source IN ('overturedb', 'themerrdb', 'youtube_search')",
            name="ck_media_collections_youtube_id_source",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "server_type", "server_item_id", name="uq_media_collection_server_item"
        ),
    )
    op.create_index(
        "ix_media_collections_collection_group",
        "media_collections",
        ["collection_group"],
    )
    op.create_index(
        "ix_media_collections_library_id", "media_collections", ["library_id"]
    )
    op.create_index(
        "ix_media_collections_media_type", "media_collections", ["media_type"]
    )
    op.create_index(
        "ix_media_collections_server_item_id", "media_collections", ["server_item_id"]
    )
    op.create_index(
        "ix_media_collections_tmdb_collection_id",
        "media_collections",
        ["tmdb_collection_id"],
    )
    op.create_table(
        "media_items",
        sa.Column(
            "media_type",
            sa.Enum("movie", "show", name="mediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column("title", auto_string(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("tvdb_id", sa.Integer(), nullable=True),
        sa.Column("imdb_id", auto_string(), nullable=True),
        sa.Column("tmdb_collection_id", sa.Integer(), nullable=True),
        sa.Column("folder_path", auto_string(), nullable=True),
        sa.Column("server_item_id", auto_string(), nullable=True),
        sa.Column("server_link", auto_string(), nullable=True),
        sa.Column("server_verified_at", sa.DateTime(), nullable=True),
        sa.Column("library_id", auto_string(), nullable=True),
        sa.Column("monitored", sa.Boolean(), nullable=False),
        sa.Column("youtube_id", auto_string(), nullable=True),
        sa.Column(
            "youtube_id_source",
            sa.Enum(
                "download",
                "embedded_id",
                "source_url",
                "metadata_url",
                "selection",
                name="themeidsource",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("youtube_title", auto_string(), nullable=True),
        sa.Column("youtube_duration", sa.Integer(), nullable=True),
        sa.Column("theme_file_hash", auto_string(), nullable=True),
        sa.Column("director", auto_string(), nullable=True),
        sa.Column("studio", auto_string(), nullable=True),
        sa.Column("genres", sa.JSON(), nullable=False),
        sa.Column("actors", sa.JSON(), nullable=False),
        sa.Column("writers", sa.JSON(), nullable=False),
        sa.Column("producers", sa.JSON(), nullable=False),
        sa.Column("countries", sa.JSON(), nullable=False),
        sa.Column("labels", sa.JSON(), nullable=False),
        sa.Column("content_rating", auto_string(), nullable=True),
        sa.Column("edition", auto_string(), nullable=True),
        sa.Column("resolution", auto_string(), nullable=True),
        sa.Column("critic_rating", sa.Float(), nullable=True),
        sa.Column("audience_rating", sa.Float(), nullable=True),
        sa.Column("user_rating", sa.Float(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("plays", sa.Integer(), nullable=True),
        sa.Column("last_played_at", sa.DateTime(), nullable=True),
        sa.Column("unplayed", sa.Boolean(), nullable=True),
        sa.Column("in_progress", sa.Boolean(), nullable=True),
        sa.Column("release_date", auto_string(), nullable=True),
        sa.Column("versions", sa.Integer(), nullable=True),
        sa.Column("original_language", auto_string(), nullable=True),
        sa.Column("origin_countries", sa.JSON(), nullable=False),
        sa.Column("tmdb_rating", sa.Float(), nullable=True),
        sa.Column("tmdb_votes", sa.Integer(), nullable=True),
        sa.Column("tmdb_keywords", sa.JSON(), nullable=False),
        sa.Column("companies", sa.JSON(), nullable=False),
        sa.Column("networks", sa.JSON(), nullable=False),
        sa.Column("streaming", sa.JSON(), nullable=False),
        sa.Column("show_status", auto_string(), nullable=True),
        sa.Column("last_aired", auto_string(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_matched_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("server_added_at", sa.DateTime(), nullable=True),
        sa.Column("server_removed_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("director_etag", auto_string(), nullable=True),
        sa.Column("theme_file_mtime_ns", sa.Integer(), nullable=True),
        sa.Column("theme_file_size", sa.Integer(), nullable=True),
        sa.Column("theme_file_duration", sa.Integer(), nullable=True),
        sa.Column("theme_provenance_cleared", sa.Boolean(), nullable=False),
        sa.Column("tmdb_checked_id", sa.Integer(), nullable=True),
        sa.Column("tmdb_checked_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_media_items_media_type"
        ),
        sa.CheckConstraint(
            "youtube_id_source IN ('download', 'embedded_id', 'source_url', "
            "'metadata_url', 'selection')",
            name="ck_media_items_youtube_id_source",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_media_items_folder_path", "media_items", ["folder_path"])
    op.create_index(
        "ix_media_items_imdb_identity", "media_items", ["media_type", "imdb_id"]
    )
    op.create_index("ix_media_items_library_id", "media_items", ["library_id"])
    op.create_index("ix_media_items_media_type", "media_items", ["media_type"])
    op.create_index(
        "ix_media_items_monitored_library", "media_items", ["monitored", "library_id"]
    )
    op.create_index(
        "ix_media_items_server_identity",
        "media_items",
        ["media_type", "server_item_id"],
    )
    op.create_index("ix_media_items_server_item_id", "media_items", ["server_item_id"])
    op.create_index("ix_media_items_title", "media_items", ["title"])
    op.create_index(
        "ix_media_items_title_year", "media_items", ["media_type", "title", "year"]
    )
    op.create_index(
        "ix_media_items_tmdb_collection_id", "media_items", ["tmdb_collection_id"]
    )
    op.create_index("ix_media_items_tmdb_id", "media_items", ["tmdb_id"])
    op.create_index(
        "ix_media_items_tmdb_identity", "media_items", ["media_type", "tmdb_id"]
    )
    op.create_index(
        "ix_media_items_tvdb_identity", "media_items", ["media_type", "tvdb_id"]
    )
    op.create_index(
        "ix_media_items_visible_library",
        "media_items",
        ["server_removed_at", "library_id"],
    )
    op.create_index(
        "ix_media_items_visible_title", "media_items", ["server_removed_at", "title"]
    )
    op.create_table(
        "public_dataset_collections",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("title", auto_string(), nullable=False),
        sa.Column("poster_url", auto_string(), nullable=True),
        sa.Column("background_url", auto_string(), nullable=True),
        sa.Column("youtube_id_overturedb", auto_string(), nullable=True),
        sa.Column("youtube_id_themerrdb", auto_string(), nullable=True),
        sa.Column("no_theme", sa.Boolean(), nullable=False),
        sa.Column("catalog_synced_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "youtube_id_overturedb IS NULL OR youtube_id_themerrdb IS NULL"
            " OR youtube_id_overturedb != youtube_id_themerrdb",
            name="ck_public_dataset_collection_different_youtube_ids",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tmdb_id"),
    )
    op.create_table(
        "public_dataset_drafts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "media_type",
            sa.Enum(
                "movie",
                "show",
                "collection",
                name="catalogmediatype",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("tvdb_id", sa.Integer(), nullable=True),
        sa.Column("imdb_id", auto_string(), nullable=True),
        sa.Column("entry", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show', 'collection')",
            name="ck_public_dataset_drafts_media_type",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_public_dataset_drafts_imdb_id", "public_dataset_drafts", ["imdb_id"]
    )
    op.create_index(
        "ix_public_dataset_drafts_media_type", "public_dataset_drafts", ["media_type"]
    )
    op.create_index(
        "ix_public_dataset_drafts_tmdb_id", "public_dataset_drafts", ["tmdb_id"]
    )
    op.create_index(
        "ix_public_dataset_drafts_tvdb_id", "public_dataset_drafts", ["tvdb_id"]
    )
    op.create_table(
        "public_dataset_items",
        sa.Column(
            "media_type",
            sa.Enum("movie", "show", name="mediatype", native_enum=False),
            nullable=False,
        ),
        sa.Column("tmdb_id", sa.Integer(), nullable=True),
        sa.Column("tvdb_id", sa.Integer(), nullable=True),
        sa.Column("imdb_id", auto_string(), nullable=True),
        sa.Column("title", auto_string(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("poster_url", auto_string(), nullable=True),
        sa.Column("background_url", auto_string(), nullable=True),
        sa.Column("youtube_id_overturedb", auto_string(), nullable=True),
        sa.Column("youtube_id_themerrdb", auto_string(), nullable=True),
        sa.Column("no_theme", sa.Boolean(), nullable=False),
        sa.Column("catalog_synced_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "media_type IN ('movie', 'show')", name="ck_public_dataset_items_media_type"
        ),
        sa.CheckConstraint(
            "youtube_id_overturedb IS NULL OR youtube_id_themerrdb IS NULL"
            " OR youtube_id_overturedb != youtube_id_themerrdb",
            name="ck_public_dataset_different_youtube_ids",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_public_dataset_item_imdb", "public_dataset_items", ["media_type", "imdb_id"]
    )
    op.create_index(
        "ix_public_dataset_item_tmdb", "public_dataset_items", ["media_type", "tmdb_id"]
    )
    op.create_index(
        "ix_public_dataset_item_tvdb", "public_dataset_items", ["media_type", "tvdb_id"]
    )
    op.create_index(
        "ix_public_dataset_items_imdb_id", "public_dataset_items", ["imdb_id"]
    )
    op.create_index(
        "ix_public_dataset_items_media_type", "public_dataset_items", ["media_type"]
    )
    op.create_index(
        "ix_public_dataset_items_tmdb_id", "public_dataset_items", ["tmdb_id"]
    )
    op.create_index(
        "ix_public_dataset_items_tvdb_id", "public_dataset_items", ["tvdb_id"]
    )
    op.create_table(
        "saved_schedules",
        sa.Column(
            "kind",
            sa.Enum("assets", "sync", name="schedulekind", native_enum=False),
            nullable=False,
        ),
        sa.Column("name", auto_string(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cron_expression", auto_string(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_json", sa.JSON(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('assets', 'sync')", name="ck_saved_schedules_kind"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "name", name="uq_saved_schedules_kind_name"),
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
        "task_schedule",
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("cron_expression", auto_string(), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column("task_name", auto_string(), nullable=False),
        sa.PrimaryKeyConstraint("task_name"),
    )
    op.create_table(
        "collection_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("criteria_json", auto_string(), nullable=False),
        sa.Column("smart", sa.Boolean(), nullable=False),
        sa.Column("item_limit", sa.Integer(), nullable=True),
        sa.Column(
            "sync_mode",
            sa.Enum("sync", "append", name="syncmode", native_enum=False),
            nullable=True,
        ),
        sa.Column("minimum_items", sa.Integer(), nullable=True),
        sa.Column("delete_below_minimum", sa.Boolean(), nullable=True),
        sa.Column(
            "collection_mode",
            sa.Enum(
                "default",
                "hide_items",
                "show_items",
                "hide",
                name="collectionmode",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "order_type",
            sa.Enum(
                "custom",
                "release.asc",
                "release.desc",
                "title.asc",
                "title.desc",
                "added.desc",
                "added.asc",
                "critic_rating.desc",
                "critic_rating.asc",
                "audience_rating.desc",
                "audience_rating.asc",
                "user_rating.desc",
                "user_rating.asc",
                "duration.desc",
                "duration.asc",
                "plays.desc",
                "plays.asc",
                "last_played.desc",
                "last_played.asc",
                "random",
                name="collectionorder",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column(
            "collection_filtering",
            sa.Enum("admin", "user", name="collectionfiltering", native_enum=False),
            nullable=True,
        ),
        sa.Column("visible_home", sa.Boolean(), nullable=True),
        sa.Column("visible_shared", sa.Boolean(), nullable=True),
        sa.Column("visible_library", sa.Boolean(), nullable=True),
        sa.Column("sort_title_format", auto_string(), nullable=True),
        sa.Column("summary_format", auto_string(), nullable=True),
        sa.Column("active_start_mmdd", auto_string(), nullable=True),
        sa.Column("active_end_mmdd", auto_string(), nullable=True),
        sa.Column("delete_when_inactive", sa.Boolean(), nullable=True),
        sa.Column("auto_match_art", sa.Boolean(), nullable=True),
        sa.Column("auto_match_theme", sa.Boolean(), nullable=True),
        sa.Column("request_missing", sa.Boolean(), nullable=True),
        sa.Column("member_label", auto_string(), nullable=True),
        sa.Column("arr_tag", auto_string(), nullable=True),
        sa.Column("home_order", sa.Integer(), nullable=True),
        sa.Column("source_summary", auto_string(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", auto_string(), nullable=True),
        sa.CheckConstraint(
            "collection_filtering IN ('admin', 'user')",
            name="ck_collection_rules_collection_filtering",
        ),
        sa.CheckConstraint(
            "collection_mode IN ('default', 'hide_items', 'show_items', 'hide')",
            name="ck_collection_rules_collection_mode",
        ),
        sa.CheckConstraint(
            "order_type IN ('custom', 'release.asc', 'release.desc', 'title.asc', "
            "'title.desc', 'added.desc', 'added.asc', 'critic_rating.desc', "
            "'critic_rating.asc', 'audience_rating.desc', 'audience_rating.asc', "
            "'user_rating.desc', 'user_rating.asc', 'duration.desc', 'duration.asc', "
            "'plays.desc', 'plays.asc', 'last_played.desc', 'last_played.asc', "
            "'random')",
            name="ck_collection_rules_order_type",
        ),
        sa.CheckConstraint(
            "sync_mode IN ('sync', 'append')", name="ck_collection_rules_sync_mode"
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["media_collections.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_collection_rules_collection_id",
        "collection_rules",
        ["collection_id"],
        unique=True,
    )
    op.create_table(
        "job_log_lines",
        sa.Column("run_id", auto_string(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("outcome", auto_string(), nullable=False),
        sa.Column("entry", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["job_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "ordinal"),
    )
    op.create_index(
        "ix_job_log_lines_run_outcome",
        "job_log_lines",
        ["run_id", "outcome", "ordinal"],
    )
    op.create_table(
        "job_results",
        sa.Column("run_id", auto_string(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["job_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("run_id", "ordinal"),
    )
    op.create_table(
        "media_collection_members",
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("collection_id", sa.Integer(), nullable=False),
        sa.Column("media_item_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["media_collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("collection_id", "media_item_id"),
    )
    op.create_index(
        "ix_media_collection_members_item",
        "media_collection_members",
        ["media_item_id"],
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
    op.create_index(
        "ix_public_dataset_seasons_season_num", "public_dataset_seasons", ["season_num"]
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("media_item_id", "season_num", name="uq_season"),
    )
    op.create_index("ix_seasons_item_files", "seasons", ["media_item_id", "file_count"])
    op.create_index(
        "ix_seasons_item_number_files",
        "seasons",
        ["media_item_id", "season_num", "file_count"],
    )
    op.create_index("ix_seasons_media_item_id", "seasons", ["media_item_id"])
    op.create_table(
        "art_slots",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("media_item_id", sa.Integer(), nullable=True),
        sa.Column("season_id", sa.Integer(), nullable=True),
        sa.Column("collection_id", sa.Integer(), nullable=True),
        sa.Column(
            "art_type",
            sa.Enum(
                "poster",
                "background",
                "season_poster",
                name="arttype",
                native_enum=False,
            ),
            nullable=False,
        ),
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
        sa.CheckConstraint(
            "(media_item_id IS NOT NULL) + (season_id IS NOT NULL)"
            " + (collection_id IS NOT NULL) = 1",
            name="ck_art_slots_owner",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["media_collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "collection_id", "art_type", name="uq_art_slots_collection"
        ),
        sa.UniqueConstraint(
            "media_item_id", "art_type", name="uq_art_slots_media_item"
        ),
        sa.UniqueConstraint("season_id", "art_type", name="uq_art_slots_season"),
    )
    op.create_index("ix_art_slots_collection_id", "art_slots", ["collection_id"])
    op.create_index("ix_art_slots_media_item_id", "art_slots", ["media_item_id"])
    op.create_index("ix_art_slots_season_id", "art_slots", ["season_id"])
    op.create_table(
        "download_jobs",
        sa.Column("media_item_id", sa.Integer(), nullable=True),
        sa.Column(
            "job_type",
            sa.Enum(
                "art", "theme", "collection_theme", name="jobtype", native_enum=False
            ),
            nullable=False,
        ),
        sa.Column(
            "art_type",
            sa.Enum(
                "poster",
                "background",
                "season_poster",
                name="arttype",
                native_enum=False,
            ),
            nullable=True,
        ),
        sa.Column("target_url", auto_string(), nullable=True),
        sa.Column("season_id", sa.Integer(), nullable=True),
        sa.Column("collection_id", sa.Integer(), nullable=True),
        sa.Column("collection_title", auto_string(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "done",
                "failed",
                "cancelled",
                name="jobstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("progress_percent", sa.Float(), nullable=False),
        sa.Column("error_message", auto_string(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("id", auto_string(), nullable=False),
        sa.CheckConstraint(
            "art_type IN ('poster', 'background', 'season_poster')",
            name="ck_download_jobs_art_type",
        ),
        sa.CheckConstraint(
            "job_type IN ('art', 'theme', 'collection_theme')",
            name="ck_download_jobs_job_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed', 'cancelled')",
            name="ck_download_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["collection_id"], ["media_collections.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["media_item_id"], ["media_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_download_jobs_active_equivalent",
        "download_jobs",
        ["media_item_id", "job_type", "art_type", "target_url", "season_id", "status"],
    )
    op.create_index(
        "ix_download_jobs_collection_id", "download_jobs", ["collection_id"]
    )
    op.create_index(
        "ix_download_jobs_media_item_id", "download_jobs", ["media_item_id"]
    )
    op.create_index("ix_download_jobs_status", "download_jobs", ["status"])
    op.create_index(
        "ix_download_jobs_status_created", "download_jobs", ["status", "created_at"]
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("download_jobs")
    op.drop_table("art_slots")
    op.drop_table("seasons")
    op.drop_table("public_dataset_seasons")
    op.drop_table("media_collection_members")
    op.drop_table("job_results")
    op.drop_table("job_log_lines")
    op.drop_table("collection_rules")
    op.drop_table("task_schedule")
    op.drop_table("saved_schedules")
    op.drop_table("public_dataset_items")
    op.drop_table("public_dataset_drafts")
    op.drop_table("public_dataset_collections")
    op.drop_table("media_items")
    op.drop_table("media_collections")
    op.drop_table("job_runs")
    op.drop_table("collection_presets")
    op.drop_table("collection_groups")
    op.drop_table("auth_sessions")
    op.drop_table("app_settings")
    op.drop_table("api_keys")
