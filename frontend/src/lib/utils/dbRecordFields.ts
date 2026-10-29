export type DisplayField = {
  key: string;
  value: string;
};

/**
 * What the API derives rather than stores: a display rendition of a link, and
 * the completeness the art and theme tabs already show by colour.
 */
const DERIVED_FIELDS = new Set([
  "poster_preview_url",
  "art_status",
  "poster_status",
  "background_status",
  "season_posters_status",
  "theme_status",
]);

const TOP_LEVEL_ORDER = [
  "id",
  "media_item_id",
  "media_type",
  "title",
  "season_num",
  "year",
  "file_count",
  "tmdb_id",
  "tvdb_id",
  "imdb_id",
  "folder_path",
  "server_item_id",
  "server_link",
  "server_verified_at",
  "library_id",
  "monitored",
  "poster_url",
  "poster_source",
  "poster_hash",
  "poster_phash",
  "poster_width",
  "poster_height",
  "background_url",
  "background_source",
  "background_hash",
  "background_phash",
  "background_width",
  "background_height",
  "youtube_id",
  "youtube_id_source",
  "youtube_title",
  "youtube_duration",
  "theme_file_hash",
  "theme_duration",
  "youtube_id_overturedb",
  "youtube_id_themerrdb",
  "no_theme",
  "has_incorrect_aspect_ratio",
  "director",
  "studio",
  "public_dataset_complete",
  "last_synced_at",
  "last_matched_at",
  "created_at",
  "server_added_at",
  "server_removed_at",
];
// Precompute ordering for each dotted prefix to avoid scanning `TOP_LEVEL_ORDER`
const ORDER_MAP = new Map<string, string[]>();
(function buildOrderMap() {
  // Top-level entries are the full TOP_LEVEL_ORDER strings
  ORDER_MAP.set("", TOP_LEVEL_ORDER.slice());

  for (const key of TOP_LEVEL_ORDER) {
    const parts = key.split(".");
    // Build child ordering for each prefix in the path
    for (let i = 1; i < parts.length; i++) {
      const prefix = parts.slice(0, i).join(".");
      const child = parts[i];
      if (!child) continue;
      const list: string[] = ORDER_MAP.get(prefix) ?? [];
      if (!list.includes(child)) list.push(child);
      ORDER_MAP.set(prefix, list);
    }
  }
})();

function orderForPrefix(prefix: string): string[] {
  if (!prefix) return TOP_LEVEL_ORDER.slice();
  const list = ORDER_MAP.get(prefix);
  return list ? list.slice() : [];
}

function orderedEntries(record: Record<string, unknown>, prefix: string) {
  const order = orderForPrefix(prefix);
  if (order.length === 0) return Object.entries(record);
  const rank = new Map(order.map((key, index) => [key, index]));
  return Object.entries(record).sort(([left], [right]) => {
    const leftRank = rank.get(left) ?? Number.MAX_SAFE_INTEGER;
    const rightRank = rank.get(right) ?? Number.MAX_SAFE_INTEGER;
    if (leftRank !== rightRank) return leftRank - rightRank;
    return left.localeCompare(right);
  });
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function jsonValue(value: unknown): string {
  try {
    const json = JSON.stringify(value);
    return json === undefined ? String(value) : json;
  } catch {
    return "unserializable";
  }
}

function displayValue(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") {
    return String(value);
  }
  if (Array.isArray(value)) return value.length === 0 ? "[]" : jsonValue(value);
  return jsonValue(value);
}

export function dbRecordFields(record: object | null | undefined, prefix = ""): DisplayField[] {
  if (!record) return [];

  return orderedEntries(record as Record<string, unknown>, prefix).flatMap(([key, value]) => {
    if (DERIVED_FIELDS.has(key)) return [];
    const fieldKey = prefix ? `${prefix}.${key}` : key;
    if (!isPlainRecord(value)) {
      return [{ key: fieldKey, value: displayValue(value) }];
    }

    const fields = dbRecordFields(value, fieldKey);
    return fields.length > 0 ? fields : [{ key: fieldKey, value: "{}" }];
  });
}
