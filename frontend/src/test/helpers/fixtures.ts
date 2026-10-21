import { DEFAULT_APP_SETTINGS } from "../../generated/settings";
import type { JobLogFeed } from "../../lib/stores/jobLogFeed.svelte";
import type {
  AppSettingsRead,
  ArtCandidate,
  ArtMatchResponse,
  BulkAssetsScheduleResponse,
  CollectionRead,
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
    art_url: null,
    child_count: 0,
    has_theme: false,
    id: "collection-1",
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
    run_status: "idle",
    waiting_for: null,
    config: {
      library_ids: ["1"],
      item_ids: null,
      skip_recent_val: 4,
      skip_recent_unit: "days",
      include_unmonitored: true,
      overwrite_existing: true,
      retry_saved_downloads: true,
      art: { art_types: ["background"], source_order: ["overturedb"], threshold: 5 },
      themes: null,
    },
    ...overrides,
  };
}
