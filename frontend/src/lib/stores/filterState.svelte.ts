import { routeScope } from "../router/routes";
import {
  ART_FILTER_SLOTS,
  ART_SOURCES,
  METADATA_ISSUE_FLAGS,
  THEME_SOURCES,
  defaultCatalogFilters,
  defaultTmdbFilters,
  type ArtFilterSlot,
  type CatalogFilters,
  type MetadataIssue,
  type TmdbFilters,
} from "../utils/sidebarFilters";
import type { ArtSource } from "../utils/sidebarShared";
import { keysOf } from "../utils/records";
import { readJson, stringOption, writeJson } from "../utils/storage";
import type { ThemeIdSource } from "../../generated/rest/types.gen";
import {
  CATALOG_SELECTION_FILTERS,
  SELECTION_AGREEMENTS,
  type CatalogSelectionFilter,
  type SelectionAgreement,
} from "../utils/catalogSelections";

type Completeness = "all" | "complete" | "incomplete";

/** Inclusive bounds; null leaves that side open, and two nulls disable the filter. */
export interface NumberRange {
  min: number | null;
  max: number | null;
}

export interface FilterState extends Record<CatalogSelectionFilter, SelectionAgreement> {
  monitored: "all" | "monitored" | "unmonitored";
  collectionSize: "all" | "empty" | "below_minimum";
  collectionKind: "all" | "regular" | "smart";
  collectionHolds: "all" | "movie" | "show" | "both";
  /** Whether a collection stands alone or is one a set made per value. */
  collectionOrigin: "all" | "single" | "set";
  collectionMembers: "all" | "managed" | "unmanaged";
  collectionSync: "all" | "synced" | "failed";
  art: Completeness;
  theme: Completeness;
  seasonPosters: Completeness;
  overtureDb: Completeness;
  themerrDb: Completeness;
  aspectRatio: "all" | "correct" | "incorrect";
  mediaServer: "all" | "present" | "missing";
  libraryIds: string[];
  collectionId: number | null;
  /** The saved custom filter applied to the titles, if any. */
  customFilter: number | null;
  themeSources: ThemeIdSource[];
  artSource: { sources: ArtSource[]; artType: ArtFilterSlot };
  metadataIssues: { flags: MetadataIssue[]; mode: "all" | "any" };
  resolution: NumberRange & { artType: ArtFilterSlot };
  themeLength: NumberRange;
}

const DEFAULT_FILTERS: FilterState = {
  monitored: "all",
  collectionSize: "all",
  collectionKind: "all",
  collectionHolds: "all",
  collectionOrigin: "all",
  collectionMembers: "all",
  collectionSync: "all",
  art: "all",
  theme: "all",
  seasonPosters: "all",
  overtureDb: "all",
  themerrDb: "all",
  ...(Object.fromEntries(keysOf(CATALOG_SELECTION_FILTERS).map((key) => [key, "all"])) as Record<
    CatalogSelectionFilter,
    SelectionAgreement
  >),
  aspectRatio: "all",
  mediaServer: "all",
  libraryIds: [],
  collectionId: null,
  customFilter: null,
  themeSources: [],
  artSource: { sources: [], artType: "any" },
  metadataIssues: { flags: [], mode: "all" },
  resolution: { artType: "any", min: null, max: null },
  themeLength: { min: null, max: null },
};

export function defaultFilters(): FilterState {
  return structuredClone(DEFAULT_FILTERS);
}

const MONITORED_FILTERS = ["all", "monitored", "unmonitored"] as const;
const COMPLETENESS_FILTERS = ["all", "complete", "incomplete"] as const;
const ASPECT_RATIO_FILTERS = ["all", "correct", "incorrect"] as const;
const MEDIA_SERVER_FILTERS = ["all", "present", "missing"] as const;
const METADATA_ISSUE_MODES = ["all", "any"] as const;
const ART_FILTER_TYPES = keysOf(ART_FILTER_SLOTS);

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is string => typeof entry === "string")
    : [];
}

function allowedValues<T extends string>(value: unknown, allowed: readonly T[]): T[] {
  const values = stringArray(value);
  return allowed.filter((entry) => values.includes(entry));
}

function bound(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function numberRange(value: unknown): NumberRange {
  const source = record(value);
  return { min: bound(source.min), max: bound(source.max) };
}

/** A stored row's ID, or null for anything else. */
function savedId(value: unknown): number | null {
  return typeof value === "number" && Number.isSafeInteger(value) ? value : null;
}

function normalizeFilters(value: unknown): FilterState {
  const source = record(value);
  const metadataIssues = record(source.metadataIssues);
  const resolution = record(source.resolution);
  const artSource = record(source.artSource);
  const defaults = DEFAULT_FILTERS;

  return {
    monitored: stringOption(source.monitored, MONITORED_FILTERS, defaults.monitored),
    collectionSize: stringOption(
      source.collectionSize,
      ["all", "empty", "below_minimum"] as const,
      defaults.collectionSize,
    ),
    collectionHolds: stringOption(
      source.collectionHolds,
      ["all", "movie", "show", "both"] as const,
      defaults.collectionHolds,
    ),
    collectionOrigin: stringOption(
      source.collectionOrigin,
      ["all", "single", "set"] as const,
      defaults.collectionOrigin,
    ),
    collectionKind: stringOption(
      source.collectionKind,
      ["all", "regular", "smart"] as const,
      defaults.collectionKind,
    ),
    collectionMembers: stringOption(
      source.collectionMembers,
      ["all", "managed", "unmanaged"] as const,
      defaults.collectionMembers,
    ),
    collectionSync: stringOption(
      source.collectionSync,
      ["all", "synced", "failed"] as const,
      defaults.collectionSync,
    ),
    art: stringOption(source.art, COMPLETENESS_FILTERS, defaults.art),
    theme: stringOption(source.theme, COMPLETENESS_FILTERS, defaults.theme),
    seasonPosters: stringOption(source.seasonPosters, COMPLETENESS_FILTERS, defaults.seasonPosters),
    overtureDb: stringOption(source.overtureDb, COMPLETENESS_FILTERS, defaults.overtureDb),
    themerrDb: stringOption(source.themerrDb, COMPLETENESS_FILTERS, defaults.themerrDb),
    ...(Object.fromEntries(
      keysOf(CATALOG_SELECTION_FILTERS).map((key) => [
        key,
        stringOption(source[key], SELECTION_AGREEMENTS, defaults[key]),
      ]),
    ) as Record<CatalogSelectionFilter, SelectionAgreement>),
    aspectRatio: stringOption(source.aspectRatio, ASPECT_RATIO_FILTERS, defaults.aspectRatio),
    mediaServer: stringOption(source.mediaServer, MEDIA_SERVER_FILTERS, defaults.mediaServer),
    libraryIds: stringArray(source.libraryIds),
    collectionId: savedId(source.collectionId),
    customFilter: savedId(source.customFilter),
    themeSources: allowedValues(source.themeSources, THEME_SOURCES),
    artSource: {
      sources: allowedValues(artSource.sources, ART_SOURCES),
      artType: stringOption(artSource.artType, ART_FILTER_TYPES, defaults.artSource.artType),
    },
    metadataIssues: {
      flags: allowedValues(metadataIssues.flags, METADATA_ISSUE_FLAGS),
      mode: stringOption(metadataIssues.mode, METADATA_ISSUE_MODES, defaults.metadataIssues.mode),
    },
    resolution: {
      artType: stringOption(resolution.artType, ART_FILTER_TYPES, defaults.resolution.artType),
      ...numberRange(resolution),
    },
    themeLength: numberRange(source.themeLength),
  };
}

function loadFilters(key: string): FilterState {
  return normalizeFilters(readJson<unknown>(key, null));
}

/** The sidebar's filters: each library tab's and the collections', kept between visits, and the catalog's and TMDB search's for the session. */
class Filters {
  movie = $state<FilterState>(loadFilters("movieFilters"));
  show = $state<FilterState>(loadFilters("showFilters"));
  collection = $state<FilterState>(loadFilters("collectionFilters"));
  catalog = $state<CatalogFilters>(defaultCatalogFilters());
  tmdb = $state<TmdbFilters>(defaultTmdbFilters());

  /** The filters of the list the sidebar shows. */
  get current(): FilterState {
    const { mode, tab } = routeScope();
    if (mode === "collections") return this.collection;
    return tab === "movie" ? this.movie : this.show;
  }

  save() {
    writeJson("movieFilters", this.movie);
    writeJson("showFilters", this.show);
    writeJson("collectionFilters", this.collection);
  }

  /** Replace the current list's filters and keep them. */
  set(value: FilterState) {
    // Number inputs can bind zero or negative bounds; those mean "no bound".
    const filters = normalizeFilters(value);
    const { mode, tab } = routeScope();
    if (mode === "collections") this.collection = filters;
    else if (tab === "movie") this.movie = filters;
    else this.show = filters;
    this.save();
  }

  clear() {
    this.set(defaultFilters());
  }
}

export const filterState = new Filters();
