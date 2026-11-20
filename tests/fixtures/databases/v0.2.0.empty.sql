BEGIN TRANSACTION;
CREATE TABLE alembic_version (
	version_num VARCHAR(32) NOT NULL, 
	CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);
INSERT INTO "alembic_version" VALUES('f2b6d9a4c731');
CREATE TABLE api_keys (
	id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	key_hash VARCHAR NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	UNIQUE (key_hash), 
	UNIQUE (name)
);
INSERT INTO "api_keys" VALUES(1,'value 1','value 1','2026-11-20 09:12:13.415355');
CREATE TABLE "app_settings" (
	collection_sync_mode VARCHAR(6) NOT NULL, 
	collection_mode_default VARCHAR(10) NOT NULL, 
	collection_order_default VARCHAR(20) NOT NULL, 
	collection_filtering_default VARCHAR(5) NOT NULL, 
	collection_visible_home BOOLEAN NOT NULL, 
	collection_visible_shared BOOLEAN NOT NULL, 
	collection_visible_library BOOLEAN NOT NULL, 
	collection_minimum_items INTEGER NOT NULL, 
	collection_delete_below_minimum BOOLEAN NOT NULL, 
	collection_auto_match_theme BOOLEAN NOT NULL, 
	collection_sort_title_format VARCHAR(200) NOT NULL, 
	collection_summary_format VARCHAR(2000) NOT NULL, 
	collection_delete_when_inactive BOOLEAN NOT NULL, 
	collection_request_missing BOOLEAN NOT NULL, 
	collection_import_unmanaged BOOLEAN NOT NULL, 
	overturedb_no_theme BOOLEAN NOT NULL, 
	overturedb_browse BOOLEAN NOT NULL, 
	tmdb_region VARCHAR(2) NOT NULL, 
	radarr_root_folder VARCHAR(500) NOT NULL, 
	radarr_quality_profile_id INTEGER, 
	radarr_search BOOLEAN NOT NULL, 
	sonarr_root_folder VARCHAR(500) NOT NULL, 
	sonarr_quality_profile_id INTEGER, 
	sonarr_search BOOLEAN NOT NULL, 
	auto_match_art BOOLEAN NOT NULL, 
	workflow VARCHAR(14) NOT NULL, 
	theme_search_format VARCHAR(200) NOT NULL, 
	min_duration_seconds INTEGER NOT NULL, 
	max_duration_seconds INTEGER NOT NULL, 
	normalize_theme_loudness BOOLEAN NOT NULL, 
	skip_media_server_tmdb_urls BOOLEAN NOT NULL, 
	disable_media_server_art BOOLEAN NOT NULL, 
	aspect_ratio_tolerance VARCHAR(7) NOT NULL, 
	tmdb_language_filter VARCHAR(7) NOT NULL, 
	auto_advance VARCHAR(15) NOT NULL, 
	auto_advance_skip_completed BOOLEAN NOT NULL, 
	auto_unmonitor VARCHAR(13) NOT NULL, 
	id INTEGER NOT NULL, 
	updated_at DATETIME, 
	collection_auto_art VARCHAR(24) NOT NULL, 
	collection_generated_style VARCHAR(6) NOT NULL, 
	collection_backgrounds BOOLEAN NOT NULL, 
	auto_search_themes BOOLEAN NOT NULL, 
	collection_overturedb_posters VARCHAR(10) NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_app_settings_tmdb_language_filter CHECK (tmdb_language_filter IN ('en_null', 'all')), 
	CONSTRAINT ck_app_settings_collection_filtering_default CHECK (collection_filtering_default IN ('admin', 'user')), 
	CONSTRAINT ck_app_settings_collection_mode_default CHECK (collection_mode_default IN ('default', 'hide_items', 'show_items', 'hide')), 
	CONSTRAINT ck_app_settings_collection_overturedb_posters CHECK (collection_overturedb_posters IN ('individual', 'consistent')), 
	CONSTRAINT ck_app_settings_workflow CHECK (workflow IN ('art', 'art_and_themes', 'themes')), 
	CONSTRAINT ck_app_settings_aspect_ratio_tolerance CHECK (aspect_ratio_tolerance IN ('strict', 'lenient', 'off')), 
	CONSTRAINT ck_app_settings_collection_order_default CHECK (collection_order_default IN ('custom', 'release.asc', 'release.desc', 'title.asc', 'title.desc', 'added.desc', 'added.asc', 'critic_rating.desc', 'critic_rating.asc', 'audience_rating.desc', 'audience_rating.asc', 'user_rating.desc', 'user_rating.asc', 'duration.desc', 'duration.asc', 'plays.desc', 'plays.asc', 'last_played.desc', 'last_played.asc', 'random')), 
	CONSTRAINT ck_app_settings_auto_advance CHECK (auto_advance IN ('off', 'slots', 'slots_and_items')), 
	CONSTRAINT ck_app_settings_singleton CHECK (id = 1), 
	CONSTRAINT ck_app_settings_collection_sync_mode CHECK (collection_sync_mode IN ('sync', 'append')), 
	CONSTRAINT ck_app_settings_auto_unmonitor CHECK (auto_unmonitor IN ('off', 'art', 'theme', 'art_or_theme', 'art_and_theme')), 
	CONSTRAINT ck_app_settings_collection_auto_art CHECK (collection_auto_art IN ('off', 'overturedb', 'tmdb', 'overturedb_tmdb', 'overturedb_generate', 'tmdb_generate', 'overturedb_tmdb_generate', 'generate')), 
	CONSTRAINT ck_app_settings_collection_generated_style CHECK (collection_generated_style IN ('dark', 'light', 'accent'))
);
INSERT INTO "app_settings" VALUES('sync','default','release.asc','user',0,0,0,2,1,0,'','',1,0,1,1,1,'US','',NULL,0,'',NULL,0,0,'art_and_themes','{title} {year} main theme music',20,600,1,0,0,'strict','en_null','slots_and_items',1,'art_and_theme',1,NULL,'off','dark',1,1,'individual');
CREATE TABLE "art_slots" (
	id INTEGER NOT NULL, 
	media_item_id INTEGER, 
	season_id INTEGER, 
	collection_id INTEGER, 
	art_type VARCHAR(13) NOT NULL, 
	url VARCHAR, 
	file_hash VARCHAR, 
	phash VARCHAR, 
	width INTEGER, 
	height INTEGER, 
	file_mtime_ns INTEGER, 
	file_size INTEGER, 
	upload_hash VARCHAR, 
	generated_style VARCHAR(6), 
	generated_title_only BOOLEAN NOT NULL, selection_hash VARCHAR, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_art_slots_season UNIQUE (season_id, art_type), 
	CONSTRAINT ck_art_slots_generated_style CHECK (generated_style IN ('dark', 'light', 'accent')), 
	CONSTRAINT uq_art_slots_collection UNIQUE (collection_id, art_type), 
	CONSTRAINT ck_art_slots_selection CHECK (url IS NULL OR upload_hash IS NULL), 
	CONSTRAINT ck_art_slots_art_type CHECK (art_type IN ('poster', 'background', 'season_poster')), 
	CONSTRAINT ck_art_slots_generated_title_only CHECK (NOT generated_title_only OR generated_style IS NOT NULL), 
	CONSTRAINT uq_art_slots_media_item UNIQUE (media_item_id, art_type), 
	CONSTRAINT ck_art_slots_generated CHECK (generated_style IS NULL OR upload_hash IS NOT NULL), 
	CONSTRAINT ck_art_slots_owner CHECK ((media_item_id IS NOT NULL) + (season_id IS NOT NULL) + (collection_id IS NOT NULL) = 1), 
	FOREIGN KEY(collection_id) REFERENCES media_collections (id) ON DELETE CASCADE, 
	FOREIGN KEY(media_item_id) REFERENCES media_items (id) ON DELETE CASCADE, 
	FOREIGN KEY(season_id) REFERENCES seasons (id) ON DELETE CASCADE
);
INSERT INTO "art_slots" VALUES(1,1,NULL,NULL,'poster',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL);
CREATE TABLE auth_sessions (
	token_hash VARCHAR NOT NULL, 
	expires_at DATETIME NOT NULL, 
	oidc_issuer VARCHAR, 
	credential_fingerprint VARCHAR, 
	id_token VARCHAR, 
	PRIMARY KEY (token_hash)
);
INSERT INTO "auth_sessions" VALUES('value 1','2026-01-01 00:00:00.000000',NULL,NULL,NULL);
CREATE TABLE "catalog_collections" (
	id INTEGER NOT NULL, 
	tmdb_id INTEGER NOT NULL, 
	title VARCHAR NOT NULL, 
	poster_url VARCHAR, 
	background_url VARCHAR, 
	youtube_id_overturedb VARCHAR, 
	youtube_id_themerrdb VARCHAR, 
	no_theme BOOLEAN NOT NULL, 
	catalog_synced_at DATETIME, 
	consistent_poster_url VARCHAR, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_catalog_collection_different_youtube_ids CHECK (youtube_id_overturedb IS NULL OR youtube_id_themerrdb IS NULL OR youtube_id_overturedb != youtube_id_themerrdb), 
	UNIQUE (tmdb_id)
);
INSERT INTO "catalog_collections" VALUES(1,1,'value 1',NULL,NULL,NULL,NULL,0,NULL,NULL);
CREATE TABLE "catalog_drafts" (
	id INTEGER NOT NULL, 
	media_type VARCHAR(10) NOT NULL, 
	tmdb_id INTEGER, 
	tvdb_id INTEGER, 
	imdb_id VARCHAR, 
	entry JSON NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_catalog_drafts_media_type CHECK (media_type IN ('movie', 'show', 'collection')), 
	CONSTRAINT ck_catalog_drafts_entry_json CHECK (json_valid(entry))
);
INSERT INTO "catalog_drafts" VALUES(1,'movie',NULL,NULL,NULL,'{}','2026-01-01 00:00:00.000000');
CREATE TABLE "catalog_item_seasons" (
	catalog_item_id INTEGER NOT NULL, 
	season_num INTEGER NOT NULL, 
	poster_url VARCHAR, 
	id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(catalog_item_id) REFERENCES catalog_items (id) ON DELETE CASCADE
);
INSERT INTO "catalog_item_seasons" VALUES(1,1,NULL,1);
CREATE TABLE "catalog_items" (
	media_type VARCHAR(5) NOT NULL, 
	tmdb_id INTEGER, 
	tvdb_id INTEGER, 
	imdb_id VARCHAR, 
	title VARCHAR, 
	year INTEGER, 
	poster_url VARCHAR, 
	background_url VARCHAR, 
	youtube_id_overturedb VARCHAR, 
	youtube_id_themerrdb VARCHAR, 
	no_theme BOOLEAN NOT NULL, 
	catalog_synced_at DATETIME, 
	id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_catalog_items_media_type CHECK (media_type IN ('movie', 'show')), 
	CONSTRAINT ck_catalog_item_different_youtube_ids CHECK (youtube_id_overturedb IS NULL OR youtube_id_themerrdb IS NULL OR youtube_id_overturedb != youtube_id_themerrdb)
);
INSERT INTO "catalog_items" VALUES('movie',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,0,NULL,1);
CREATE TABLE "collection_groups" (
	id INTEGER NOT NULL, 
	name VARCHAR NOT NULL, 
	sync_mode VARCHAR(6), 
	minimum_items INTEGER, 
	delete_below_minimum BOOLEAN, 
	collection_mode VARCHAR(10), 
	order_type VARCHAR(20), 
	collection_filtering VARCHAR(5), 
	visible_home BOOLEAN, 
	visible_shared BOOLEAN, 
	visible_library BOOLEAN, 
	sort_title_format VARCHAR, 
	summary_format VARCHAR, 
	active_start_mmdd VARCHAR, 
	active_end_mmdd VARCHAR, 
	delete_when_inactive BOOLEAN, 
	auto_match_theme BOOLEAN, 
	request_missing BOOLEAN, 
	member_label VARCHAR, 
	arr_tag VARCHAR, 
	home_order INTEGER, 
	generator JSON, 
	generated_at DATETIME, 
	separator BOOLEAN NOT NULL, 
	auto_art VARCHAR(24), 
	generated_style VARCHAR(6), 
	backgrounds BOOLEAN, 
	overturedb_posters VARCHAR(10), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_collection_groups_collection_mode CHECK (collection_mode IN ('default', 'hide_items', 'show_items', 'hide')), 
	CONSTRAINT ck_collection_groups_overturedb_posters CHECK (overturedb_posters IN ('individual', 'consistent')), 
	CONSTRAINT uq_collection_group UNIQUE (name), 
	CONSTRAINT ck_collection_groups_generator_json CHECK (json_valid(generator)), 
	CONSTRAINT ck_collection_groups_sync_mode CHECK (sync_mode IN ('sync', 'append')), 
	CONSTRAINT ck_collection_groups_collection_filtering CHECK (collection_filtering IN ('admin', 'user')), 
	CONSTRAINT ck_collection_groups_order_type CHECK (order_type IN ('custom', 'release.asc', 'release.desc', 'title.asc', 'title.desc', 'added.desc', 'added.asc', 'critic_rating.desc', 'critic_rating.asc', 'audience_rating.desc', 'audience_rating.asc', 'user_rating.desc', 'user_rating.asc', 'duration.desc', 'duration.asc', 'plays.desc', 'plays.asc', 'last_played.desc', 'last_played.asc', 'random')), 
	CONSTRAINT ck_collection_groups_auto_art CHECK (auto_art IN ('off', 'overturedb', 'tmdb', 'overturedb_tmdb', 'overturedb_generate', 'tmdb_generate', 'overturedb_tmdb_generate', 'generate')), 
	CONSTRAINT ck_collection_groups_generated_style CHECK (generated_style IN ('dark', 'light', 'accent'))
);
INSERT INTO "collection_groups" VALUES(1,'value 1',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,'null',NULL,0,NULL,NULL,NULL,NULL);
CREATE TABLE "collection_libraries" (
	id INTEGER NOT NULL, 
	collection_id INTEGER NOT NULL, 
	library_id VARCHAR NOT NULL, 
	media_type VARCHAR(5) NOT NULL, 
	server_item_id VARCHAR, 
	criteria JSON, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_collection_library UNIQUE (collection_id, library_id), 
	CONSTRAINT ck_collection_libraries_media_type CHECK (media_type IN ('movie', 'show')), 
	CONSTRAINT fk_collection_libraries_library FOREIGN KEY(library_id, media_type) REFERENCES libraries (id, media_type) ON DELETE RESTRICT, 
	CONSTRAINT ck_collection_libraries_criteria_json CHECK (json_valid(criteria)), 
	FOREIGN KEY(collection_id) REFERENCES media_collections (id) ON DELETE CASCADE
);
INSERT INTO "collection_libraries" VALUES(1,1,'value 1','movie',NULL,'null');
CREATE TABLE "collection_rules" (
	id INTEGER NOT NULL, 
	collection_id INTEGER NOT NULL, 
	smart BOOLEAN NOT NULL, 
	item_limit INTEGER, 
	sync_mode VARCHAR(6), 
	minimum_items INTEGER, 
	delete_below_minimum BOOLEAN, 
	collection_mode VARCHAR(10), 
	order_type VARCHAR(20), 
	collection_filtering VARCHAR(5), 
	visible_home BOOLEAN, 
	visible_shared BOOLEAN, 
	visible_library BOOLEAN, 
	sort_title_format VARCHAR, 
	summary_format VARCHAR, 
	active_start_mmdd VARCHAR, 
	active_end_mmdd VARCHAR, 
	delete_when_inactive BOOLEAN, 
	auto_match_theme BOOLEAN, 
	request_missing BOOLEAN, 
	member_label VARCHAR, 
	arr_tag VARCHAR, 
	home_order INTEGER, 
	source_summary VARCHAR, 
	last_synced_at DATETIME, 
	last_error VARCHAR, 
	auto_art VARCHAR(24), 
	generated_style VARCHAR(6), 
	backgrounds BOOLEAN, 
	overturedb_posters VARCHAR(10), 
	PRIMARY KEY (id), 
	CONSTRAINT ck_collection_rules_collection_mode CHECK (collection_mode IN ('default', 'hide_items', 'show_items', 'hide')), 
	CONSTRAINT ck_collection_rules_sync_mode CHECK (sync_mode IN ('sync', 'append')), 
	CONSTRAINT ck_collection_rules_order_type CHECK (order_type IN ('custom', 'release.asc', 'release.desc', 'title.asc', 'title.desc', 'added.desc', 'added.asc', 'critic_rating.desc', 'critic_rating.asc', 'audience_rating.desc', 'audience_rating.asc', 'user_rating.desc', 'user_rating.asc', 'duration.desc', 'duration.asc', 'plays.desc', 'plays.asc', 'last_played.desc', 'last_played.asc', 'random')), 
	CONSTRAINT ck_collection_rules_collection_filtering CHECK (collection_filtering IN ('admin', 'user')), 
	CONSTRAINT ck_collection_rules_overturedb_posters CHECK (overturedb_posters IN ('individual', 'consistent')), 
	CONSTRAINT ck_collection_rules_auto_art CHECK (auto_art IN ('off', 'overturedb', 'tmdb', 'overturedb_tmdb', 'overturedb_generate', 'tmdb_generate', 'overturedb_tmdb_generate', 'generate')), 
	CONSTRAINT ck_collection_rules_generated_style CHECK (generated_style IN ('dark', 'light', 'accent')), 
	FOREIGN KEY(collection_id) REFERENCES media_collections (id) ON DELETE CASCADE
);
INSERT INTO "collection_rules" VALUES(1,1,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
CREATE TABLE download_jobs (
	media_item_id INTEGER, 
	job_type VARCHAR(16) NOT NULL, 
	art_type VARCHAR(13), 
	target_url VARCHAR, 
	season_id INTEGER, 
	collection_id INTEGER, 
	collection_title VARCHAR, 
	status VARCHAR(9) NOT NULL, 
	progress_percent FLOAT NOT NULL, 
	error_message VARCHAR, 
	created_at DATETIME NOT NULL, 
	completed_at DATETIME, 
	id VARCHAR NOT NULL, upload_hash VARCHAR, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_download_jobs_art_type CHECK (art_type IN ('poster', 'background', 'season_poster')), 
	CONSTRAINT ck_download_jobs_job_type CHECK (job_type IN ('art', 'theme', 'collection_theme')), 
	CONSTRAINT ck_download_jobs_status CHECK (status IN ('pending', 'running', 'done', 'failed', 'cancelled')), 
	FOREIGN KEY(collection_id) REFERENCES media_collections (id) ON DELETE CASCADE, 
	FOREIGN KEY(media_item_id) REFERENCES media_items (id) ON DELETE CASCADE, 
	FOREIGN KEY(season_id) REFERENCES seasons (id) ON DELETE CASCADE
);
INSERT INTO "download_jobs" VALUES(NULL,'art',NULL,NULL,NULL,NULL,NULL,'pending',0.0,NULL,'2026-01-01 00:00:00.000000',NULL,'2c560a09-c90f-4fa2-b224-23573e624e90',NULL);
CREATE TABLE "job_log_lines" (
	run_id VARCHAR NOT NULL, 
	ordinal INTEGER NOT NULL, 
	outcome VARCHAR NOT NULL, 
	entry JSON NOT NULL, 
	PRIMARY KEY (run_id, ordinal), 
	CONSTRAINT ck_job_log_lines_entry_json CHECK (json_valid(entry)), 
	FOREIGN KEY(run_id) REFERENCES job_runs (id) ON DELETE CASCADE
);
INSERT INTO "job_log_lines" VALUES('value 1',1,'value 1','{}');
CREATE TABLE "job_results" (
	run_id VARCHAR NOT NULL, 
	ordinal INTEGER NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (run_id, ordinal), 
	CONSTRAINT ck_job_results_payload_json CHECK (json_valid(payload)), 
	FOREIGN KEY(run_id) REFERENCES job_runs (id) ON DELETE CASCADE
);
INSERT INTO "job_results" VALUES('value 1',1,'{}');
CREATE TABLE "job_runs" (
	id VARCHAR NOT NULL, 
	kind VARCHAR NOT NULL, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	event VARCHAR NOT NULL, 
	summary JSON NOT NULL, 
	total INTEGER NOT NULL, 
	log_total INTEGER NOT NULL, 
	cleared BOOLEAN NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_job_runs_summary_json CHECK (json_valid(summary))
);
INSERT INTO "job_runs" VALUES('value 1','value 1','2026-01-01 00:00:00.000000',NULL,'value 1','{}',0,0,0);
CREATE TABLE libraries (
	id VARCHAR NOT NULL, 
	media_type VARCHAR(5) NOT NULL, 
	title VARCHAR NOT NULL, 
	removed_at DATETIME, 
	PRIMARY KEY (id, media_type), 
	CONSTRAINT ck_libraries_media_type CHECK (media_type IN ('movie', 'show'))
);
INSERT INTO "libraries" VALUES('value 1','movie','value 1',NULL);
CREATE TABLE media_collection_members (
	position INTEGER NOT NULL, 
	collection_id INTEGER NOT NULL, 
	media_item_id INTEGER NOT NULL, 
	PRIMARY KEY (collection_id, media_item_id), 
	FOREIGN KEY(collection_id) REFERENCES media_collections (id) ON DELETE CASCADE, 
	FOREIGN KEY(media_item_id) REFERENCES media_items (id) ON DELETE CASCADE
);
INSERT INTO "media_collection_members" VALUES(0,1,1);
CREATE TABLE "media_collections" (
	kind VARCHAR(9) NOT NULL, 
	title VARCHAR NOT NULL, 
	summary VARCHAR, 
	summary_source VARCHAR, 
	sort_title VARCHAR, 
	sort_title_format VARCHAR, 
	summary_format VARCHAR, 
	collection_mode VARCHAR(10), 
	order_type VARCHAR(20) NOT NULL, 
	collection_filtering VARCHAR(5), 
	visible_home BOOLEAN NOT NULL, 
	visible_shared BOOLEAN NOT NULL, 
	visible_library BOOLEAN NOT NULL, 
	active_start_mmdd VARCHAR, 
	active_end_mmdd VARCHAR, 
	delete_when_inactive BOOLEAN, 
	child_count INTEGER NOT NULL, 
	thumb_url VARCHAR, 
	art_url VARCHAR, 
	server_path VARCHAR, 
	server_added_at DATETIME, 
	provider_tmdb_id INTEGER, 
	tmdb_collection_id INTEGER, 
	generated_value VARCHAR, 
	youtube_id VARCHAR, 
	youtube_id_source VARCHAR(14), 
	youtube_title VARCHAR, 
	youtube_duration INTEGER, 
	server_theme_id VARCHAR, 
	theme_file_hash VARCHAR, 
	theme_file_mtime_ns INTEGER, 
	theme_file_size INTEGER, 
	theme_file_duration INTEGER, 
	last_matched_at DATETIME, 
	monitored BOOLEAN NOT NULL, 
	unsynced BOOLEAN NOT NULL, 
	last_synced_at DATETIME, 
	created_at DATETIME, 
	updated_at DATETIME, 
	id INTEGER NOT NULL, 
	deselected BOOLEAN NOT NULL, 
	group_id INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_media_collections_kind CHECK (kind IN ('regular', 'smart', 'separator')), 
	CONSTRAINT ck_media_collections_youtube_id_source CHECK (youtube_id_source IN ('overturedb', 'themerrdb', 'youtube_search')), 
	CONSTRAINT ck_media_collections_collection_filtering CHECK (collection_filtering IN ('admin', 'user')), 
	CONSTRAINT ck_media_collections_order_type CHECK (order_type IN ('custom', 'release.asc', 'release.desc', 'title.asc', 'title.desc', 'added.desc', 'added.asc', 'critic_rating.desc', 'critic_rating.asc', 'audience_rating.desc', 'audience_rating.asc', 'user_rating.desc', 'user_rating.asc', 'duration.desc', 'duration.asc', 'plays.desc', 'plays.asc', 'last_played.desc', 'last_played.asc', 'random')), 
	CONSTRAINT fk_media_collections_group FOREIGN KEY(group_id) REFERENCES collection_groups (id) ON DELETE RESTRICT, 
	CONSTRAINT ck_media_collections_collection_mode CHECK (collection_mode IN ('default', 'hide_items', 'show_items', 'hide'))
);
INSERT INTO "media_collections" VALUES('regular','',NULL,NULL,NULL,NULL,NULL,NULL,'release.asc',NULL,0,0,0,NULL,NULL,NULL,0,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,1,0,NULL,NULL,NULL,1,0,NULL);
CREATE TABLE "media_item_terms" (
	media_item_id INTEGER NOT NULL, 
	kind VARCHAR(14) NOT NULL, 
	position INTEGER NOT NULL, 
	term_id INTEGER NOT NULL, 
	PRIMARY KEY (media_item_id, kind, position), 
	CONSTRAINT ck_media_item_terms_kind CHECK (kind IN ('genre', 'actor', 'director', 'writer', 'producer', 'country', 'label', 'tmdb_keyword', 'company', 'network', 'streaming', 'origin_country')), 
	FOREIGN KEY(media_item_id) REFERENCES media_items (id) ON DELETE CASCADE, 
	CONSTRAINT fk_media_item_terms_term FOREIGN KEY(term_id, kind) REFERENCES terms (id, kind) ON DELETE RESTRICT
)
 WITHOUT ROWID

;
INSERT INTO "media_item_terms" VALUES(1,'genre',1,1);
CREATE TABLE "media_items" (
	media_type VARCHAR(5) NOT NULL, 
	title VARCHAR NOT NULL, 
	year INTEGER, 
	tmdb_id INTEGER, 
	tvdb_id INTEGER, 
	imdb_id VARCHAR, 
	tmdb_collection_id INTEGER, 
	folder_path VARCHAR, 
	server_item_id VARCHAR, 
	server_verified_at DATETIME, 
	library_id VARCHAR, 
	monitored BOOLEAN NOT NULL, 
	youtube_id VARCHAR, 
	youtube_id_source VARCHAR(12), 
	youtube_title VARCHAR, 
	youtube_duration INTEGER, 
	theme_file_hash VARCHAR, 
	studio VARCHAR, 
	content_rating VARCHAR, 
	edition VARCHAR, 
	resolution VARCHAR, 
	critic_rating FLOAT, 
	audience_rating FLOAT, 
	user_rating FLOAT, 
	plays INTEGER, 
	last_played_at DATETIME, 
	unplayed BOOLEAN, 
	in_progress BOOLEAN, 
	release_date VARCHAR, 
	versions INTEGER, 
	original_language VARCHAR, 
	tmdb_rating FLOAT, 
	tmdb_votes INTEGER, 
	show_status VARCHAR, 
	last_aired VARCHAR, 
	last_synced_at DATETIME, 
	last_matched_at DATETIME, 
	created_at DATETIME, 
	server_added_at DATETIME, 
	server_removed_at DATETIME, 
	id INTEGER NOT NULL, 
	director_etag VARCHAR, 
	theme_file_mtime_ns INTEGER, 
	theme_file_size INTEGER, 
	theme_file_duration INTEGER, 
	theme_provenance_cleared BOOLEAN NOT NULL, 
	tmdb_checked_id INTEGER, 
	tmdb_checked_at DATETIME, 
	sort_title VARCHAR, 
	duration_seconds INTEGER, theme_selection_hash VARCHAR, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_media_items_media_type CHECK (media_type IN ('movie', 'show')), 
	CONSTRAINT fk_media_items_library FOREIGN KEY(library_id, media_type) REFERENCES libraries (id, media_type) ON DELETE RESTRICT, 
	CONSTRAINT ck_media_items_show_fields CHECK (media_type = 'show' OR (show_status IS NULL AND last_aired IS NULL)), 
	CONSTRAINT ck_media_items_youtube_id_source CHECK (youtube_id_source IN ('download', 'embedded_id', 'source_url', 'metadata_url', 'selection')), 
	CONSTRAINT ck_media_items_movie_fields CHECK (media_type = 'movie' OR (tmdb_collection_id IS NULL AND edition IS NULL AND versions IS NULL AND director_etag IS NULL))
);
INSERT INTO "media_items" VALUES('movie','value 1',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,1,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,1,NULL,NULL,NULL,NULL,0,NULL,NULL,NULL,NULL,NULL);
CREATE TABLE notification_rules (
	kind VARCHAR NOT NULL, 
	failed BOOLEAN NOT NULL, 
	stopped BOOLEAN NOT NULL, 
	completed VARCHAR(7) NOT NULL, 
	scheduled_only BOOLEAN NOT NULL, 
	PRIMARY KEY (kind), 
	CONSTRAINT ck_notification_rules_completed CHECK (completed IN ('never', 'always', 'changes', 'errors'))
);
INSERT INTO "notification_rules" VALUES('value 1',1,0,'never',0);
CREATE TABLE "saved_schedules" (
	kind VARCHAR(6) NOT NULL, 
	name VARCHAR NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	cron_expression VARCHAR NOT NULL, 
	payload JSON NOT NULL, 
	state JSON NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	last_run_at DATETIME, 
	last_run_summary JSON, 
	id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_saved_schedules_kind CHECK (kind IN ('assets', 'sync')), 
	CONSTRAINT uq_saved_schedules_kind_name UNIQUE (kind, name), 
	CONSTRAINT ck_saved_schedules_payload_json CHECK (json_valid(payload)), 
	CONSTRAINT ck_saved_schedules_state_json CHECK (json_valid(state)), 
	CONSTRAINT ck_saved_schedules_last_run_summary_json CHECK (json_valid(last_run_summary))
);
INSERT INTO "saved_schedules" VALUES('assets','value 1',1,'value 1','{}','{}','2026-01-01 00:00:00.000000','2026-01-01 00:00:00.000000',NULL,'null',1);
CREATE TABLE seasons (
	media_item_id INTEGER NOT NULL, 
	season_num INTEGER NOT NULL, 
	title VARCHAR, 
	server_item_id VARCHAR, 
	file_count INTEGER NOT NULL, 
	folder_path VARCHAR, 
	last_matched_at DATETIME, 
	id INTEGER NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(media_item_id) REFERENCES media_items (id) ON DELETE CASCADE, 
	CONSTRAINT uq_season UNIQUE (media_item_id, season_num)
);
INSERT INTO "seasons" VALUES(1,1,NULL,NULL,0,NULL,NULL,1);
CREATE TABLE "task_schedule" (
	enabled BOOLEAN NOT NULL, 
	cron_expression VARCHAR NOT NULL, 
	payload JSON NOT NULL, 
	updated_at DATETIME, 
	task_name VARCHAR NOT NULL, 
	PRIMARY KEY (task_name), 
	CONSTRAINT ck_task_schedule_payload_json CHECK (json_valid(payload))
);
INSERT INTO "task_schedule" VALUES(0,'','{}',NULL,'value 1');
CREATE TABLE terms (
	id INTEGER NOT NULL, 
	kind VARCHAR(14) NOT NULL, 
	name VARCHAR NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT ck_terms_kind CHECK (kind IN ('genre', 'actor', 'director', 'writer', 'producer', 'country', 'label', 'tmdb_keyword', 'company', 'network', 'streaming', 'origin_country')), 
	CONSTRAINT uq_terms UNIQUE (kind, name)
);
INSERT INTO "terms" VALUES(1,'genre','value 1');
CREATE INDEX ix_auth_sessions_expires_at ON auth_sessions (expires_at);
CREATE INDEX ix_media_collection_members_item ON media_collection_members (media_item_id);
CREATE INDEX ix_seasons_item_files ON seasons (media_item_id, file_count);
CREATE INDEX ix_seasons_item_number_files ON seasons (media_item_id, season_num, file_count);
CREATE INDEX ix_seasons_media_item_id ON seasons (media_item_id);
CREATE INDEX ix_download_jobs_active_equivalent ON download_jobs (media_item_id, job_type, art_type, target_url, season_id, status);
CREATE INDEX ix_download_jobs_collection_id ON download_jobs (collection_id);
CREATE INDEX ix_download_jobs_media_item_id ON download_jobs (media_item_id);
CREATE INDEX ix_download_jobs_status ON download_jobs (status);
CREATE INDEX ix_download_jobs_status_created ON download_jobs (status, created_at);
CREATE UNIQUE INDEX uq_libraries_listed ON libraries (id) WHERE removed_at IS NULL;
CREATE INDEX ix_media_items_library_id ON media_items (library_id);
CREATE INDEX ix_media_items_monitored_library ON media_items (monitored, library_id);
CREATE INDEX ix_media_items_tvdb_identity ON media_items (media_type, tvdb_id);
CREATE INDEX ix_media_items_tmdb_collection_id ON media_items (tmdb_collection_id);
CREATE INDEX ix_media_items_visible_library ON media_items (server_removed_at, library_id);
CREATE INDEX ix_media_items_server_identity ON media_items (media_type, server_item_id);
CREATE INDEX ix_media_items_server_item_id ON media_items (server_item_id);
CREATE INDEX ix_media_items_title ON media_items (title);
CREATE INDEX ix_media_items_tmdb_id ON media_items (tmdb_id);
CREATE INDEX ix_media_items_visible_title ON media_items (server_removed_at, title);
CREATE INDEX ix_media_items_folder_path ON media_items (folder_path);
CREATE INDEX ix_media_items_media_type ON media_items (media_type);
CREATE INDEX ix_media_items_title_year ON media_items (media_type, title, year);
CREATE INDEX ix_media_items_tmdb_identity ON media_items (media_type, tmdb_id);
CREATE INDEX ix_media_items_imdb_identity ON media_items (media_type, imdb_id);
CREATE INDEX ix_collection_libraries_collection_id ON collection_libraries (collection_id);
CREATE INDEX ix_collection_libraries_server_item_id ON collection_libraries (server_item_id);
CREATE INDEX ix_collection_libraries_media_type ON collection_libraries (media_type);
CREATE INDEX ix_saved_schedules_kind ON saved_schedules (kind);
CREATE INDEX ix_saved_schedules_enabled_kind ON saved_schedules (enabled, kind);
CREATE INDEX ix_saved_schedules_kind_created ON saved_schedules (kind, created_at, id);
CREATE INDEX ix_saved_schedules_enabled ON saved_schedules (enabled);
CREATE INDEX ix_job_runs_kind ON job_runs (kind);
CREATE INDEX ix_job_runs_finished_at ON job_runs (finished_at);
CREATE INDEX ix_job_log_lines_run_outcome ON job_log_lines (run_id, outcome, ordinal);
CREATE UNIQUE INDEX uq_terms_id_kind ON terms (id, kind);
CREATE UNIQUE INDEX uq_media_item_terms_term ON media_item_terms (term_id, media_item_id);
CREATE INDEX ix_art_slots_media_item_id ON art_slots (media_item_id);
CREATE INDEX ix_art_slots_season_id ON art_slots (season_id);
CREATE INDEX ix_art_slots_collection_id ON art_slots (collection_id);
CREATE INDEX ix_media_collections_tmdb_collection_id ON media_collections (tmdb_collection_id);
CREATE INDEX ix_media_collections_group_id ON media_collections (group_id);
CREATE INDEX ix_catalog_item_imdb ON catalog_items (media_type, imdb_id);
CREATE INDEX ix_catalog_item_tmdb ON catalog_items (media_type, tmdb_id);
CREATE INDEX ix_catalog_item_tvdb ON catalog_items (media_type, tvdb_id);
CREATE INDEX ix_catalog_items_imdb_id ON catalog_items (imdb_id);
CREATE INDEX ix_catalog_items_media_type ON catalog_items (media_type);
CREATE INDEX ix_catalog_items_tmdb_id ON catalog_items (tmdb_id);
CREATE INDEX ix_catalog_items_tvdb_id ON catalog_items (tvdb_id);
CREATE UNIQUE INDEX ix_catalog_item_season_number ON catalog_item_seasons (catalog_item_id, season_num);
CREATE INDEX ix_catalog_item_seasons_catalog_item_id ON catalog_item_seasons (catalog_item_id);
CREATE INDEX ix_catalog_item_seasons_season_num ON catalog_item_seasons (season_num);
CREATE INDEX ix_catalog_drafts_imdb_id ON catalog_drafts (imdb_id);
CREATE INDEX ix_catalog_drafts_media_type ON catalog_drafts (media_type);
CREATE INDEX ix_catalog_drafts_tmdb_id ON catalog_drafts (tmdb_id);
CREATE INDEX ix_catalog_drafts_tvdb_id ON catalog_drafts (tvdb_id);
CREATE UNIQUE INDEX ix_collection_rules_collection_id ON collection_rules (collection_id);
COMMIT;
