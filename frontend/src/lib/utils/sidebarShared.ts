import type {
  AssetStatus,
  CatalogEntryRow,
  CollectionGroupRead,
  CollectionRead,
  MediaItemRead,
} from "../../generated/rest/types.gen";
import { SELECTED_ART_SOURCE_LABELS, UNMANAGED_GROUP } from "../../generated/settings";
import type { NumberRange } from "../stores/filterState.svelte";

export type SidebarTab = "movie" | "show";
export type SidebarMode = "items" | "collections";
/** How the library's collections are listed: inside their groups, or all at once. */
export type CollectionView = "groups" | "collections";
export type SidebarSource = "library" | "overturedb";
export type CatalogPresence = "all" | "present" | "missing";
export type SidebarSortDir = "asc" | "desc";
export type StatusTone = "success" | "warning" | "danger" | "downloading";

/** The hosts a selected artwork is attributed to. */
export type ArtSource = keyof typeof SELECTED_ART_SOURCE_LABELS;

/** Which list a search or filter applies to. */
export type ListScope = "library" | "collections" | "overturedb";
/** Which list a sort applies to; each remembers its own, and groups sort as groups. */
export type SortScope = ListScope | "groups" | "tmdb";

/** A TMDB search result as its sorts see it, with its place in TMDB's order. */
export interface TmdbRow {
  title: string;
  year: number | null;
  rank: number;
}

/** A collection group as the sidebar lists it, with what its collections add up to. */
export interface CollectionGroupRow {
  title: string;
  collections: number;
  items: number;
  /** When a collection in it was last added or synced, or null. */
  added: number | null;
  synced: number | null;
}

export interface MenuEntry<F extends string> {
  id: F;
  label: string;
  shortLabel: string;
}

export type Predicate<T> = (entry: T) => boolean;
export type Row = MediaItemRead | CollectionRead;

export const titleCollator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

export function timestamp(value: string | null): number | null {
  return value ? Date.parse(value) : null;
}

export function hasKey<K extends string>(record: Record<K, unknown>, key: string): key is K {
  return Object.hasOwn(record, key);
}

/** The list a sidebar source and mode show. */
export function sortScope(source: SidebarSource, mode: SidebarMode): ListScope {
  if (source === "overturedb") return "overturedb";
  return mode === "collections" ? "collections" : "library";
}

/** Catalog badges describe the selections the entry currently holds. */
export function catalogStatus(entry: {
  media_type: CatalogEntryRow["media_type"];
  poster_url: string | null;
  background_url: string | null;
  youtube_id_overturedb: string | null;
  youtube_id_themerrdb: string | null;
  seasons?: { season_num: number; poster_url: string | null }[] | null;
  season_posters?: number;
}): Record<"poster" | "background" | "seasons" | "art" | "theme", StatusTone> {
  const poster = !!entry.poster_url;
  const background = !!entry.background_url;
  const seasons = entry.seasons?.some((season) => !!season.poster_url) ?? !!entry.season_posters;
  const artwork = [poster, background, ...(entry.media_type === "show" ? [seasons] : [])];
  return {
    poster: poster ? "success" : "danger",
    background: background ? "success" : "danger",
    seasons: seasons ? "success" : "danger",
    art: artwork.every(Boolean) ? "success" : artwork.some(Boolean) ? "warning" : "danger",
    theme: entry.youtube_id_overturedb || entry.youtube_id_themerrdb ? "success" : "danger",
  };
}

export function isRangeActive(range: NumberRange): boolean {
  return range.min !== null || range.max !== null;
}

/** Whether a known value lies within the inclusive range; unknown values never do. */
export function inRange(value: number | null, range: NumberRange): boolean {
  return (
    value !== null &&
    (range.min === null || value >= range.min) &&
    (range.max === null || value <= range.max)
  );
}

export function matchesTriState(value: boolean, filter: string, whenTrue: string): boolean {
  return filter === "all" || value === (filter === whenTrue);
}

const STATUS_TONES: Record<AssetStatus, StatusTone> = {
  complete: "success",
  partial: "warning",
  missing: "danger",
};

/**
 * The tone of an asset status the backend reported: the sidebar badges and the
 * detail page's section icons draw it with the `data-status` styles in app.css.
 */
export function statusTone(status: AssetStatus, downloading: boolean): StatusTone {
  return downloading ? "downloading" : STATUS_TONES[status];
}

/** Rows mounted beyond each edge of the sidebar's viewport, so they load before they show. */
export const SIDEBAR_OVERSCAN_ROWS = 20;

/** Screens of rows below and above the viewport whose posters are fetched ahead. */
const PRELOAD_SCREENS = 2;

/**
 * The rows whose posters to fetch ahead once scrolling settles, given the
 * rows on screen (`first` up to `end`): up to a screen past the mounted
 * rows, below first (the usual way on), each side nearest first.
 */
export function preloadRowIndexes(first: number, end: number, count: number): number[] {
  const span = Math.max(1, end - first) * PRELOAD_SCREENS;
  const belowStart = Math.min(count, end + SIDEBAR_OVERSCAN_ROWS);
  const belowEnd = Math.min(count, belowStart + span);
  const aboveEnd = Math.max(0, first - SIDEBAR_OVERSCAN_ROWS);
  const aboveStart = Math.max(0, aboveEnd - span);
  return [
    ...Array.from({ length: belowEnd - belowStart }, (_, offset) => belowStart + offset),
    ...Array.from({ length: aboveEnd - aboveStart }, (_, offset) => aboveEnd - 1 - offset),
  ];
}

/**
 * Whether a collection is listed under *group*. Every collection Overture
 * manages is in a group, and the virtual Unmanaged one holds every collection
 * without a rule, so those appear nowhere else.
 */
export function inCollectionGroup(
  collection: Pick<CollectionRead, "collection_group" | "managed">,
  group: string,
): boolean {
  return collection.managed ? collection.collection_group === group : group === UNMANAGED_GROUP;
}

/**
 * Every group, empty or not, and any a collection names that the group list
 * has yet to load, as after saving into a new one; then Unmanaged while it
 * holds one of `collections`.
 */
export function sidebarGroupNames(
  saved: readonly CollectionGroupRead[],
  collections: readonly CollectionRead[],
): string[] {
  const names = new Set(saved.map((group) => group.name));
  for (const row of collections)
    if (row.managed && row.collection_group) names.add(row.collection_group);
  return collections.some((row) => !row.managed) ? [...names, UNMANAGED_GROUP] : [...names];
}
