import { DEFAULT_APP_SETTINGS } from "../../generated/settings";
import type { JobLogFeed } from "../../lib/stores/jobLogFeed.svelte";
import type {
  AppSettingsRead,
  ArtCandidate,
  ArtMatchResponse,
  BulkAssetsScheduleResponse,
  CollectionRead,
  CollectionCapabilities,
  CollectionRuleRead,
  CollectionDetail,
  CatalogEntry,
  CatalogEntryDetail,
  CatalogEntryRow,
  MediaItemRead,
  PublicDatasetRecord,
  PublicDatasetRecordItem,
  PublicDatasetRecordSeason,
  SeasonRead,
  ThemeSearchResult,
  PublicDatasetStatus,
} from "../../generated/rest/types.gen";
import type {
  DownloadJobEvent,
  DownloadStatus,
  JobLogEntry,
  JobOutcome,
  RealtimeSnapshot,
  ServerWebSocketDataMessage,
  WebSocketDataEventName,
  WebSocketPayloadMap,
} from "../../generated/ws";

/** The lines a job log holds, in order. */
export function loggedLines(feed: JobLogFeed): JobLogEntry[] {
  return [...feed.lines.entries()].sort(([a], [b]) => a - b).map(([, entry]) => entry);
}

export function logEntry(
  outcome: JobOutcome,
  target: string,
  reason: string,
  at = "2026-01-01T12:00:00Z",
): JobLogEntry {
  return { outcome, target, reason, at };
}

export function mediaItem(overrides: Partial<MediaItemRead> = {}): MediaItemRead {
  return {
    art_status: "missing",
    background_status: "missing",
    background_hash: null,
    background_height: null,
    background_phash: null,
    background_source: null,
    background_url: null,
    background_width: null,
    created_at: null,
    director: null,
    has_incorrect_aspect_ratio: false,
    theme_duration: null,
    theme_file_hash: null,
    theme_status: "missing",
    id: 1,
    imdb_id: null,
    last_matched_at: null,
    last_synced_at: null,
    library_id: null,
    folder_path: null,
    media_type: "movie",
    monitored: true,
    poster_status: "missing",
    poster_hash: null,
    poster_height: null,
    poster_phash: null,
    poster_preview_url: null,
    poster_source: null,
    poster_url: null,
    poster_width: null,
    public_dataset_complete: false,
    public_dataset_themerrdb: false,
    public_dataset_ids: null,
    season_posters_status: "missing",
    server_added_at: null,
    server_item_id: null,
    server_link: null,
    server_removed_at: null,
    server_verified_at: null,
    studio: null,
    title: "Test Item",
    tmdb_id: null,
    tmdb_collection_id: null,
    library_collection_id: null,
    tvdb_id: null,
    year: null,
    youtube_duration: null,
    youtube_id: null,
    youtube_id_source: null,
    youtube_title: null,
    ...overrides,
  };
}

export function season(overrides: Partial<SeasonRead> = {}): SeasonRead {
  return {
    file_count: 1,
    id: 1,
    last_matched_at: null,
    folder_path: null,
    media_item_id: 1,
    poster_status: "missing",
    poster_hash: null,
    poster_height: null,
    poster_phash: null,
    poster_preview_url: null,
    poster_url: null,
    poster_width: null,
    season_num: 1,
    server_item_id: null,
    title: null,
    ...overrides,
  };
}

export function collection(overrides: Partial<CollectionRead> = {}): CollectionRead {
  return {
    active_end_mmdd: null,
    active_start_mmdd: null,
    generated_value: null,
    managed: false,
    sync_failed: false,
    last_rule_sync: null,
    theme_duration: null,
    collection_filtering: null,
    delete_when_inactive: null,
    kind: "regular",
    sort_title_format: null,
    summary_format: null,
    visible_library: false,
    visible_shared: false,
    withheld: false,
    unsynced: false,
    below_minimum: false,
    art_url: null,
    sort_title: null,
    collection_group: null,
    poster_url: null,
    background_url: null,
    poster_status: "missing",
    background_status: "missing",
    art_status: "missing",
    collection_mode: null,
    order_type: "release.asc",
    visible_home: false,
    child_count: 0,
    has_theme: false,
    id: 1,
    tmdb_collection_id: null,
    public_dataset_complete: false,
    public_dataset_themerrdb: false,
    library_id: null,
    media_type: "movie",
    monitored: false,
    server_added_at: null,
    server_link: null,
    server_type: "plex",
    summary: null,
    thumb_url: null,
    theme_status: "missing",
    title: "Test Collection",
    youtube_duration: null,
    youtube_id: null,
    youtube_title: null,
    ...overrides,
  };
}

export function collectionRule(overrides: Partial<CollectionRuleRead> = {}): CollectionRuleRead {
  return {
    active_end_mmdd: null,
    active_start_mmdd: null,
    auto_match_art: null,
    auto_match_theme: null,
    criteria: {
      mode: "all",
      conditions: [
        {
          kind: "source",
          operator: "is",
          source: { type: "mdblist", identifiers: ["user/list"] },
        },
      ],
      groups: [],
    },
    collection_filtering: null,
    collection_mode: null,
    delete_below_minimum: null,
    delete_when_inactive: null,
    last_error: null,
    last_synced_at: null,
    limit: null,
    minimum_items: null,
    order_type: null,
    smart: false,
    sort_title_format: null,
    summary_format: null,
    sync_schedule: null,
    sync_enabled: null,
    request_missing: null,
    member_label: null,
    arr_tag: null,
    home_order: null,
    source_summary: null,
    sync_mode: null,
    visible_home: null,
    visible_library: null,
    visible_shared: null,
    ...overrides,
  };
}

/** What Plex offers movie collections, as the backend describes it. */
export function collectionCapabilities(
  overrides: Partial<CollectionCapabilities> = {},
): CollectionCapabilities {
  const text = [
    "is",
    "is_not",
    "contains",
    "does_not_contain",
    "starts_with",
    "ends_with",
  ] as const;
  const numbers = ["is", "is_not", "gt", "gte", "lt", "lte"] as const;
  return {
    server_type: "plex",
    smart: true,
    visibility: true,
    orders: ["custom", "release.asc", "release.desc", "title.asc", "critic_rating.desc"],
    smart_orders: ["release.asc", "release.desc", "title.asc", "critic_rating.desc"],
    fields: [
      {
        field: "title",
        label: "Title",
        kind: "text",
        operators: [...text],
        local: true,
        smart: true,
      },
      {
        field: "genre",
        label: "Genre",
        kind: "tag",
        operators: ["is", "is_not"],
        local: true,
        smart: true,
      },
      {
        field: "year",
        label: "Year",
        kind: "number",
        operators: [...numbers],
        local: true,
        smart: true,
      },
      {
        field: "added",
        label: "Date added",
        kind: "date",
        operators: ["in_last", "not_in_last", "before", "after"],
        local: true,
        smart: true,
      },
      {
        field: "unplayed",
        label: "Unplayed",
        kind: "boolean",
        operators: ["is", "is_not"],
        local: true,
        smart: true,
      },
      {
        field: "hdr",
        label: "HDR",
        kind: "boolean",
        operators: ["is", "is_not"],
        local: false,
        smart: true,
      },
    ],
    sources: [
      { type: "tmdb_collection", label: "TMDB franchise", unavailable: null },
      { type: "tmdb_list", label: "TMDB list", unavailable: null },
      { type: "tmdb_item", label: "TMDB titles", unavailable: null },
      { type: "tmdb_person", label: "TMDB person", unavailable: null },
      { type: "mdblist", label: "MDBList", unavailable: null },
      { type: "radarr_tag", label: "Radarr tags", unavailable: null },
      {
        type: "sonarr_tag",
        label: "Sonarr tags",
        unavailable: "Sonarr tags select shows only",
      },
    ],
    dimensions: [
      { dimension: "decade", label: "Decades", title_format: "{value}s", smart_only: false },
      { dimension: "genre", label: "Genres", title_format: "{value}", smart_only: false },
      {
        dimension: "franchise",
        label: "TMDB franchises",
        title_format: "{value}",
        smart_only: false,
      },
      { dimension: "custom", label: "Custom", title_format: "{value}", smart_only: false },
    ],
    member_labels: true,
    arr: true,
    charts: ["popular", "top_rated", "trending_week"],
    ...overrides,
  };
}

export function collectionDetail(overrides: Partial<CollectionDetail> = {}): CollectionDetail {
  return {
    ...collection(),
    effective_sync_mode: "sync",
    rule: null,
    theme_duration: null,
    catalog_entry_key: null,
    theme_writable: true,
    members: [],
    catalog_title: null,
    theme_unavailable: null,
    youtube_id_overturedb: null,
    youtube_id_themerrdb: null,
    ...overrides,
  };
}

export function catalogEntry(overrides: Partial<CatalogEntry> = {}): CatalogEntry {
  return {
    media_type: "movie",
    title: "Alien",
    year: 1979,
    tmdb_id: 348,
    tvdb_id: null,
    imdb_id: "tt0078748",
    poster_url: null,
    background_url: null,
    youtube_id_overturedb: null,
    youtube_id_themerrdb: null,
    seasons: null,
    ...overrides,
  };
}
export function catalogDetail(overrides: Partial<CatalogEntryDetail> = {}): CatalogEntryDetail {
  return {
    entry_key: "tmdb-348",
    entry: catalogEntry(),
    draft: null,
    library_item_id: null,
    library_collection_id: null,
    ...overrides,
  };
}
export function catalogRow(overrides: Partial<CatalogEntryRow> = {}): CatalogEntryRow {
  const { seasons: _seasons, ...entry } = catalogEntry();
  return {
    ...entry,
    entry_key: "tmdb-348",
    poster_preview_url: null,
    season_posters: 0,
    has_draft: false,
    library_item_id: null,
    library_collection_id: null,
    ...overrides,
  };
}

export function themeSearchResult(overrides: Partial<ThemeSearchResult> = {}): ThemeSearchResult {
  return {
    channel: null,
    duration: null,
    id: "abc123_DEF0",
    thumbnail: null,
    title: "Theme",
    url: null,
    ...overrides,
  };
}

export function publicDatasetRecordItem(
  overrides: Partial<PublicDatasetRecordItem> = {},
): PublicDatasetRecordItem {
  return {
    background_url: null,
    catalog_synced_at: null,
    id: null,
    imdb_id: null,
    media_type: "movie",
    poster_url: null,
    title: null,
    tmdb_id: null,
    tvdb_id: null,
    year: null,
    youtube_id_overturedb: null,
    youtube_id_themerrdb: null,
    ...overrides,
  };
}

export function publicDatasetRecordSeason(
  overrides: Partial<PublicDatasetRecordSeason> = {},
): PublicDatasetRecordSeason {
  return {
    id: null,
    poster_url: null,
    public_dataset_item_id: 1,
    season_num: 1,
    ...overrides,
  };
}

export function publicDatasetRecord(
  overrides: Partial<PublicDatasetRecord> = {},
): PublicDatasetRecord {
  const { item, seasons, ...recordOverrides } = overrides;
  return {
    found: true,
    item: item === undefined ? publicDatasetRecordItem() : item,
    seasons: seasons ?? [],
    ...recordOverrides,
  };
}

export function publicDatasetStatus(
  overrides: Partial<PublicDatasetStatus> = {},
): PublicDatasetStatus {
  return {
    enabled: true,
    repo_url: "https://github.com/AutoGitr/OvertureDB",
    catalog_url: "https://AutoGitr.github.io/OvertureDB/catalog.jsonl.gz",
    last_synced_at: null,
    last_status: "never_synced",
    last_stats: null,
    next_run: null,
    timezone: "UTC",
    ...overrides,
  };
}

/** A realtime message, its payload typed by its event. */
export function wsMessage<E extends WebSocketDataEventName>(
  event: E,
  data: WebSocketPayloadMap[E],
  sequence = 1,
  epoch = "epoch-1",
): ServerWebSocketDataMessage {
  // TypeScript cannot narrow the message union by a generic event name.
  return { epoch, sequence, event, data } as ServerWebSocketDataMessage;
}

export function realtimeSnapshot(overrides: Partial<RealtimeSnapshot> = {}): RealtimeSnapshot {
  return {
    epoch: "epoch-1",
    sequence: 0,
    server_time: "2026-01-01T12:00:00Z",
    jobs: [],
    downloads: [],
    public_dataset_status: publicDatasetStatus(),
    media_server: { state: "reachable", message: "" },
    ...overrides,
  };
}

/** A download of one item's poster. */
export function itemDownload(
  id: string,
  mediaItemId: number,
  status: DownloadStatus = "started",
  overrides: Partial<DownloadJobEvent> = {},
): DownloadJobEvent {
  return {
    percent: null,
    stage: null,
    step: null,
    steps: null,
    unchanged: null,
    job: {
      id,
      kind: "download",
      status,
      target: {
        target_type: "item",
        media_item_id: mediaItemId,
        title: "Alien",
        job_type: "art",
        art_type: "poster",
        season_id: null,
      },
      error: null,
    },
    ...overrides,
  };
}

export function appSettings(overrides: Partial<AppSettingsRead> = {}): AppSettingsRead {
  return {
    ...DEFAULT_APP_SETTINGS,
    media_server: null,
    tmdb_configured: false,
    mdblist_configured: false,
    radarr_configured: false,
    sonarr_configured: false,
    collections_supported: false,
    collection_themes_unavailable: null,
    art_download_workers: 1,
    theme_download_workers: 1,
    updated_at: null,
    ...overrides,
  };
}

export function artCandidate(overrides: Partial<ArtCandidate> = {}): ArtCandidate {
  return {
    art_type: "poster",
    hamming: null,
    height: 1500,
    iso_639_1: null,
    perfect_match: null,
    preview_url: null,
    source: "tmdb",
    title: null,
    url: "https://images.test/poster.jpg",
    width: 1000,
    ...overrides,
  };
}

export function artMatchResponse(overrides: Partial<ArtMatchResponse> = {}): ArtMatchResponse {
  return {
    errors: [],
    failed: 0,
    matches: [],
    prefiltered: 0,
    reason: null,
    reference: null,
    total_compared: 1,
    ...overrides,
  };
}

export function bulkAssetsSchedule(
  overrides: Partial<BulkAssetsScheduleResponse> = {},
): BulkAssetsScheduleResponse {
  return {
    id: 5,
    kind: "assets",
    name: "Nightly",
    enabled: true,
    cron_expression: "0 4 * * *",
    timezone: "UTC",
    next_run: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    last_run_at: null,
    last_run: null,
    run_status: "idle",
    waiting_for: null,
    config: {
      library_ids: ["1"],
      item_ids: null,
      collection_ids: null,
      skip_recent_val: 4,
      skip_recent_unit: "days",
      include_unmonitored: true,
      overwrite_existing: true,
      art: { art_types: ["background"], source_order: ["overturedb"], threshold: 5 },
      themes: null,
    },
    ...overrides,
  };
}
