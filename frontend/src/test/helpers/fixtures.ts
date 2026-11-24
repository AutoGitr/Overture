import packageJson from "../../../package.json" with { type: "json" };
import { DEFAULT_APP_SETTINGS } from "../../generated/settings";
import type { JobLogFeed } from "../../lib/stores/jobLogFeed.svelte";
import type {
  AppSettingsRead,
  AssetFileRead,
  AssetRead,
  CollectionDimensionRead,
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
  MediaServerRead,
  ServerType,
  CatalogRecord,
  CatalogRecordItem,
  CatalogRecordSeason,
  SeasonRead,
  ServerAsset,
  TitleAssets,
  ThemeSearchResult,
  CatalogStatus,
} from "../../generated/rest/types.gen";
import type {
  AssetIssue,
  AssetScanProgressEvent,
  BulkArtJobEvent,
  BulkThemeJobEvent,
  CatalogSyncEvent,
  DownloadJobEvent,
  DownloadStatus,
  JobKind,
  JobLogEntry,
  JobMetadata,
  JobOutcome,
  LifecycleStatus,
  ServerAuditFixEvent,
  ServerAuditProgressEvent,
  ServerAuditResult,
  SyncJobEvent,
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
  server: MediaServerRead | null = null,
): JobLogEntry {
  return {
    outcome,
    target,
    reason,
    at,
    server_id: server?.id ?? null,
    server: server?.title ?? null,
    count: 1,
  };
}

/** The configured media servers, numbered from 1 and named after their kind, lead first. */
export function mediaServers(...types: (ServerType | null)[]): MediaServerRead[] {
  const titles = { plex: "Plex", jellyfin: "Jellyfin", emby: "Emby" } as const;
  return types
    .filter((type): type is ServerType => type !== null)
    .map((type, index) => ({ id: index + 1, title: titles[type], type, collections: true }));
}

/**
 * One asset, blank unless *overrides* say what is recorded. It is selected,
 * as the backend says, when it names a link, a kept image or a video, and a
 * local file is read from the folder it is delivered to.
 */
export function asset(kind: ServerAsset, overrides: Partial<AssetRead> = {}): AssetRead {
  const recorded: Omit<AssetRead, "selected"> = {
    kind,
    status: "missing",
    needed: true,
    url: null,
    preview_url: null,
    upload_hash: null,
    source: null,
    poster_style: null,
    generated_style: null,
    generated_title_only: false,
    youtube_id: null,
    youtube_id_source: null,
    youtube_title: null,
    youtube_duration: null,
    content_hash: null,
    width: null,
    height: null,
    duration: null,
    file: null,
    deliveries: [],
    ...overrides,
  };
  const { file, content_hash } = recorded;
  return {
    ...recorded,
    selected: !!(recorded.url || recorded.upload_hash || recorded.youtube_id),
    deliveries:
      file && !recorded.deliveries.length
        ? [
            {
              server_id: null,
              channel: "file",
              required: true,
              delivered: content_hash === file.hash,
              present: true,
              checked_at: null,
            },
          ]
        : recorded.deliveries,
  };
}

/** *owner* with one of its assets changed as *overrides* say. */
export function withAsset<T extends { assets: TitleAssets }>(
  owner: T,
  kind: keyof TitleAssets,
  overrides: Partial<AssetRead>,
): T {
  const current = owner.assets[kind];
  return {
    ...owner,
    assets: { ...owner.assets, [kind]: asset(current.kind, { ...current, ...overrides }) },
  };
}

/** The file an asset's owner keeps in its folder, named by its hash. */
export function assetFile(hash: string, overrides: Partial<AssetFileRead> = {}): AssetFileRead {
  return { hash, fingerprint: null, width: null, height: null, duration: null, ...overrides };
}

/** What a test records of a title's or collection's assets, by kind. */
export type AssetOverrides = { [K in keyof TitleAssets]?: Partial<AssetRead> };

/** A title's or collection's poster, background and theme. */
function titleAssets(overrides: AssetOverrides = {}): TitleAssets {
  return {
    poster: asset("poster", overrides.poster),
    background: asset("background", overrides.background),
    theme: asset("theme", overrides.theme),
  };
}

/**
 * A library title. A test names its copy on server 1 with ``library_id`` and
 * ``server_item_id``, which replace any ``copies`` given, or passes ``copies`` itself.
 */
export function mediaItem(
  overrides: Omit<Partial<MediaItemRead>, "assets"> & {
    assets?: AssetOverrides;
    library_id?: string | null;
    server_item_id?: string | null;
  } = {},
): MediaItemRead {
  const { library_id: libraryId, server_item_id: serverItemId, assets, ...rest } = overrides;
  const copies =
    serverItemId || libraryId
      ? [{ server_id: 1, server_item_id: serverItemId ?? "", library_id: libraryId ?? "" }]
      : (rest.copies ?? []);
  return {
    art_status: "missing",
    catalog_entry_key: null,
    created_at: null,
    directors: [],
    has_incorrect_aspect_ratio: false,
    id: 1,
    imdb_id: null,
    last_matched_at: null,
    last_synced_at: null,
    folder_path: null,
    media_type: "movie",
    monitored: true,
    catalog_complete: false,
    catalog_themerrdb: false,
    catalog_ids: null,
    catalog_selections: null,
    metadata_issues: [],
    season_posters_status: "missing",
    server_poster_version: null,
    server_background_version: null,
    season_posters_sources: [],
    season_posters_width: null,
    server_added_at: null,
    server_removed_at: null,
    studio: null,
    sort_title: null,
    title: "Test Item",
    tmdb_id: null,
    tmdb_collection_id: null,
    library_collection_id: null,
    tvdb_id: null,
    year: null,
    ...rest,
    assets: titleAssets(assets),
    copies,
  };
}

export function season(
  overrides: Omit<Partial<SeasonRead>, "poster"> & { poster?: Partial<AssetRead> } = {},
): SeasonRead {
  const { poster, ...rest } = overrides;
  return {
    file_count: 1,
    id: 1,
    last_matched_at: null,
    folder_path: null,
    media_item_id: 1,
    season_num: 1,
    title: null,
    server_poster_version: null,
    ...rest,
    poster: asset("season_poster", poster),
  };
}

export function collection(
  overrides: Omit<Partial<CollectionRead>, "assets"> & { assets?: AssetOverrides } = {},
): CollectionRead {
  const { assets, ...rest } = overrides;
  return {
    active_end_mmdd: null,
    active_start_mmdd: null,
    contributed_style: "individual",
    generated_value: null,
    // Overture manages what it creates; only server imports start unmanaged.
    managed: true,
    sync_failed: false,
    last_rule_sync: null,
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
    server_background_version: null,
    sort_title: null,
    collection_group: null,
    has_incorrect_aspect_ratio: false,
    home_order: null,
    art_status: "missing",
    collection_mode: null,
    order_type: "release.asc",
    visible_home: false,
    child_count: 0,
    id: 1,
    tmdb_collection_id: null,
    catalog_complete: false,
    catalog_themerrdb: false,
    catalog_selections: null,
    metadata_issues: [],
    library_ids: ["1"],
    media_types: ["movie"],
    monitored: false,
    server_added_at: null,
    copies: [],
    summary: null,
    server_poster_version: null,
    title: "Test Collection",
    ...rest,
    assets: titleAssets(assets),
  };
}

export function collectionRule(overrides: Partial<CollectionRuleRead> = {}): CollectionRuleRead {
  return {
    active_end_mmdd: null,
    active_start_mmdd: null,
    auto_art: null,
    auto_match_theme: null,
    backgrounds: null,
    themes: null,
    generated_style: null,
    generated_title_only: null,
    overturedb_posters: null,
    libraries: [
      {
        library_id: "1",
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
      },
    ],
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
export function dimension(
  overrides: Partial<CollectionDimensionRead> &
    Pick<CollectionDimensionRead, "dimension" | "label">,
): CollectionDimensionRead {
  return {
    title_format: "{value}",
    smart_only: false,
    strip_prefix: "",
    strip_suffix: "",
    order_type: null,
    ...overrides,
  };
}

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
    server_types: ["plex"],
    spans_libraries: false,
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
        smart_operators: [...text],
        local: true,
        smart: true,
        labelled: false,
        library_status: false,
        choices: [],
        free_values: false,
        by_id: false,
        ignores_case: true,
      },
      {
        field: "genre",
        label: "Genre",
        kind: "tag",
        operators: ["is", "is_not"],
        smart_operators: ["is", "is_not"],
        local: true,
        smart: true,
        labelled: false,
        library_status: false,
        choices: [],
        free_values: false,
        by_id: false,
        ignores_case: true,
      },
      {
        field: "year",
        label: "Year",
        kind: "number",
        operators: [...numbers],
        smart_operators: [...numbers],
        local: true,
        smart: true,
        labelled: false,
        library_status: false,
        choices: [],
        free_values: false,
        by_id: false,
        ignores_case: false,
      },
      {
        field: "added",
        label: "Date added",
        kind: "date",
        operators: ["in_last", "not_in_last", "before", "after"],
        smart_operators: ["in_last", "not_in_last", "before", "after"],
        local: true,
        smart: true,
        labelled: false,
        library_status: false,
        choices: [],
        free_values: false,
        by_id: false,
        ignores_case: false,
      },
      {
        field: "unplayed",
        label: "Unplayed",
        kind: "boolean",
        operators: ["is", "is_not"],
        smart_operators: ["is", "is_not"],
        local: true,
        smart: true,
        labelled: false,
        library_status: false,
        choices: [],
        free_values: false,
        by_id: false,
        ignores_case: false,
      },
      {
        field: "hdr",
        label: "HDR",
        kind: "boolean",
        operators: ["is", "is_not"],
        smart_operators: ["is", "is_not"],
        local: false,
        smart: true,
        labelled: false,
        library_status: false,
        choices: [],
        free_values: false,
        by_id: false,
        ignores_case: false,
      },
    ],
    sources: [
      { type: "tmdb_collection", label: "TMDB franchise", unavailable: null },
      { type: "tmdb_list", label: "TMDB list", unavailable: null },
      { type: "tmdb_item", label: "TMDB title list", unavailable: null },
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
      dimension({ dimension: "decade", label: "Decades", title_format: "{value}s" }),
      dimension({ dimension: "genre", label: "Genres" }),
      dimension({
        dimension: "franchise",
        label: "TMDB franchises",
        strip_prefix: "The ",
        strip_suffix: " Collection",
        order_type: "release.asc",
      }),
      dimension({ dimension: "custom", label: "Custom" }),
    ],
    member_labels: true,
    arr: true,
    charts: ["popular", "top_rated", "trending_week"],
    ...overrides,
  };
}

export function collectionDetail(
  overrides: Omit<Partial<CollectionDetail>, "assets"> & { assets?: AssetOverrides } = {},
): CollectionDetail {
  const { assets, ...rest } = overrides;
  return {
    ...collection({ assets }),
    effective_sync_mode: "sync",
    rule: collectionRule(),
    catalog_entry_key: null,
    theme_writable: true,
    lists_missing: false,
    member_ids: [],
    catalog_title: null,
    theme_unavailable: null,
    youtube_id_overturedb: null,
    youtube_id_themerrdb: null,
    ...rest,
  };
}

export function catalogEntry(overrides: Partial<CatalogEntry> = {}): CatalogEntry {
  return {
    media_type: "movie",
    no_theme: false,
    title: "Alien",
    year: 1979,
    tmdb_id: 348,
    tvdb_id: null,
    imdb_id: "tt0078748",
    poster_url: null,
    poster_url_individual: null,
    poster_url_matte: null,
    poster_url_overlay: null,
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
    draft_issue: null,
    library_item_id: null,
    library_collection_id: null,
    local_art: {},
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
    local_art: {},
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

export function catalogRecordItem(overrides: Partial<CatalogRecordItem> = {}): CatalogRecordItem {
  return {
    background_url: null,
    catalog_synced_at: null,
    id: null,
    imdb_id: null,
    media_type: "movie",
    no_theme: false,
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

export function catalogRecordSeason(
  overrides: Partial<CatalogRecordSeason> = {},
): CatalogRecordSeason {
  return {
    id: null,
    poster_url: null,
    catalog_item_id: 1,
    season_num: 1,
    ...overrides,
  };
}

export function catalogRecord(overrides: Partial<CatalogRecord> = {}): CatalogRecord {
  const { item, seasons, collection, ...recordOverrides } = overrides;
  return {
    found: true,
    item: item === undefined ? catalogRecordItem() : item,
    collection: collection ?? null,
    seasons: seasons ?? [],
    ...recordOverrides,
  };
}

export function catalogStatus(overrides: Partial<CatalogStatus> = {}): CatalogStatus {
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
    catalog_status: catalogStatus(),
    media_servers: [{ server_id: 1, title: "Plex", state: "reachable", message: "" }],
    // The version this build is, as Vite's define and Playwright both read it.
    app_version: packageJson.version,
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
        source: null,
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
    // Groups are optional unless a test is about requiring them.
    media_servers: mediaServers("plex"),
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
    generated: null,
    hamming: null,
    height: 1500,
    iso_639_1: null,
    perfect_match: null,
    poster_style: null,
    preview_url: null,
    source: "tmdb",
    title_only: false,
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
      collection_groups: null,
      all_collections: false,
      skip_recent_val: 4,
      skip_recent_unit: "days",
      include_unmonitored: true,
      art: {
        art_types: ["background"],
        source_order: ["overturedb", "current_selection"],
        threshold: 5,
      },
      themes: null,
    },
    ...overrides,
  };
}

/** What every job event carries, with nothing reported yet. */
const JOB_ENVELOPE = {
  job: null,
  done: null,
  total: null,
  read: null,
  started_at: null,
  finished_at: null,
  log: null,
  run_id: null,
  schedule: null,
  log_total: null,
  log_outcomes: null,
  log_targets: null,
  log_servers: null,
} satisfies SyncJobEvent;

export function jobMetadata(
  kind: JobKind,
  status: LifecycleStatus,
  overrides: Partial<JobMetadata> = {},
): JobMetadata {
  return { kind, status, id: null, target: null, error: null, ...overrides };
}

export function syncEvent(overrides: Partial<SyncJobEvent> = {}): SyncJobEvent {
  return { ...JOB_ENVELOPE, ...overrides };
}

export function bulkArtEvent(overrides: Partial<BulkArtJobEvent> = {}): BulkArtJobEvent {
  return { ...JOB_ENVELOPE, settled: null, ...overrides };
}

export function bulkThemeEvent(overrides: Partial<BulkThemeJobEvent> = {}): BulkThemeJobEvent {
  return { ...JOB_ENVELOPE, settled: null, ...overrides };
}

export function assetScanEvent(
  overrides: Partial<AssetScanProgressEvent> = {},
): AssetScanProgressEvent {
  return {
    ...JOB_ENVELOPE,
    results_total: null,
    total_folders: null,
    issues_found: null,
    results_found: null,
    issues: null,
    ...overrides,
  };
}

export function serverAuditEvent(
  overrides: Partial<ServerAuditProgressEvent> = {},
): ServerAuditProgressEvent {
  return { ...JOB_ENVELOPE, results_total: null, results_found: null, results: null, ...overrides };
}

export function serverAuditFixEvent(
  overrides: Partial<ServerAuditFixEvent> = {},
): ServerAuditFixEvent {
  return { ...JOB_ENVELOPE, ...overrides };
}

export function catalogSyncEvent(overrides: Partial<CatalogSyncEvent> = {}): CatalogSyncEvent {
  return {
    ...JOB_ENVELOPE,
    stats: {
      catalog_bytes: 0,
      catalog_uncompressed_bytes: 0,
      catalog_url: null,
      collections: 0,
      entries: 0,
      errors: 0,
      items: 0,
      movies: 0,
      schema_version: null,
      seasons: 0,
      shows: 0,
    },
    ...overrides,
  };
}

export function serverAuditResult(overrides: Partial<ServerAuditResult> = {}): ServerAuditResult {
  return {
    kind: "art",
    item_id: 1,
    collection_id: null,
    season_id: null,
    art_type: "poster",
    status: "phash_mismatch",
    title: "Alien",
    local_path: null,
    server_image_present: null,
    hamming: null,
    reason: null,
    local_duration: null,
    server_duration: null,
    server_id: null,
    server: null,
    server_item_id: null,
    theme_id: null,
    theme_title: null,
    refreshed: null,
    refresh_error: null,
    ...overrides,
  };
}

export function assetIssue(overrides: Partial<AssetIssue> = {}): AssetIssue {
  return {
    folder: "/media/Movie",
    current_path: "/media/Movie/cover.jpg",
    current_filename: "cover.jpg",
    suggested_path: "/media/Movie/poster.jpg",
    suggested_filename: "poster.jpg",
    type: "poster",
    conflict: false,
    width: 1000,
    height: 1500,
    conflict_with: null,
    season_num: null,
    potential_false_positive: false,
    renamed: null,
    rename_error: null,
    ...overrides,
  };
}
