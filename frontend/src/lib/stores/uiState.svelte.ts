import { routeScope } from "../router/routes";
import {
  ART_SOURCE_SLOTS,
  ART_SOURCES,
  METADATA_ISSUES,
  THEME_SOURCES,
  defaultCatalogFilters,
  type CatalogFilters,
  type ArtSource,
  type ArtSourceSlot,
  type MetadataIssue,
  type SidebarMode,
  type SidebarSearchField,
  type SidebarTab,
  type ThemeSource,
} from "../utils/sidebarDomain";
import { readJson, writeJson } from "../utils/storage";

export type OperationsTab = "assets" | "sync" | "renamer" | "audit";

export type PopupType =
  | null
  | "collection-groups"
  | "filters"
  | "operations"
  | "settings"
  | "database"
  | "overturedb"
  | "backup"
  | "stats";

export type Completeness = "all" | "complete" | "incomplete";

/** Inclusive bounds; null leaves that side open, and two nulls disable the filter. */
export interface NumberRange {
  min: number | null;
  max: number | null;
}

export interface FilterState {
  monitored: "all" | "monitored" | "unmonitored";
  collectionSize: "all" | "empty" | "below_minimum";
  collectionKind: "all" | "regular" | "smart";
  collectionMembers: "all" | "criteria" | "manual";
  collectionSync: "all" | "synced" | "failed";
  art: Completeness;
  theme: Completeness;
  overtureDb: Completeness;
  themerrDb: Completeness;
  aspectRatio: "all" | "correct" | "incorrect";
  mediaServer: "all" | "present" | "missing";
  libraryIds: string[];
  themeSources: ThemeSource[];
  artSource: { sources: ArtSource[]; artType: ArtSourceSlot };
  metadataIssues: { flags: MetadataIssue[]; mode: "all" | "any" };
  resolution: NumberRange & { artType: "poster" | "background" };
  themeLength: NumberRange;
}

const DEFAULT_FILTERS: FilterState = {
  monitored: "all",
  collectionSize: "all",
  collectionKind: "all",
  collectionMembers: "all",
  collectionSync: "all",
  art: "all",
  theme: "all",
  overtureDb: "all",
  themerrDb: "all",
  aspectRatio: "all",
  mediaServer: "all",
  libraryIds: [],
  themeSources: [],
  artSource: { sources: [], artType: "any" },
  metadataIssues: { flags: [], mode: "all" },
  resolution: { artType: "poster", min: null, max: null },
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
const RESOLUTION_ART_TYPES = ["poster", "background"] as const;
const ART_SOURCE_ART_TYPES = Object.keys(ART_SOURCE_SLOTS) as ArtSourceSlot[];

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

function stringOption<T extends readonly string[]>(
  value: unknown,
  allowed: T,
  fallback: T[number],
): T[number] {
  return typeof value === "string" && (allowed as readonly string[]).includes(value)
    ? (value as T[number])
    : fallback;
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
    collectionKind: stringOption(
      source.collectionKind,
      ["all", "regular", "smart"] as const,
      defaults.collectionKind,
    ),
    collectionMembers: stringOption(
      source.collectionMembers,
      ["all", "criteria", "manual"] as const,
      defaults.collectionMembers,
    ),
    collectionSync: stringOption(
      source.collectionSync,
      ["all", "synced", "failed"] as const,
      defaults.collectionSync,
    ),
    art: stringOption(source.art, COMPLETENESS_FILTERS, defaults.art),
    theme: stringOption(source.theme, COMPLETENESS_FILTERS, defaults.theme),
    overtureDb: stringOption(source.overtureDb, COMPLETENESS_FILTERS, defaults.overtureDb),
    themerrDb: stringOption(source.themerrDb, COMPLETENESS_FILTERS, defaults.themerrDb),
    aspectRatio: stringOption(source.aspectRatio, ASPECT_RATIO_FILTERS, defaults.aspectRatio),
    mediaServer: stringOption(source.mediaServer, MEDIA_SERVER_FILTERS, defaults.mediaServer),
    libraryIds: stringArray(source.libraryIds),
    themeSources: allowedValues(source.themeSources, THEME_SOURCES),
    artSource: {
      sources: allowedValues(artSource.sources, ART_SOURCES),
      artType: stringOption(artSource.artType, ART_SOURCE_ART_TYPES, defaults.artSource.artType),
    },
    metadataIssues: {
      flags: allowedValues(metadataIssues.flags, METADATA_ISSUES),
      mode: stringOption(metadataIssues.mode, METADATA_ISSUE_MODES, defaults.metadataIssues.mode),
    },
    resolution: {
      artType: stringOption(resolution.artType, RESOLUTION_ART_TYPES, defaults.resolution.artType),
      ...numberRange(resolution),
    },
    themeLength: numberRange(source.themeLength),
  };
}

function loadFilters(key: string): FilterState {
  return normalizeFilters(readJson<unknown>(key, null));
}

class UiState {
  searchQuery = $state("");
  searchField = $state<SidebarSearchField>("title");
  mobileShowDetail = $state(false);

  // Filters specific to section
  movieFilters = $state<FilterState>(loadFilters("movieFilters"));
  showFilters = $state<FilterState>(loadFilters("showFilters"));
  catalogFilters = $state<CatalogFilters>(defaultCatalogFilters());

  operationsTab = $state<OperationsTab>("assets");
  collectionGroupToEdit = $state("");
  private collectionGroupChange: ((name: string, replacement: string) => void) | null = null;

  openCollectionGroups(group = "", onchange?: (name: string, replacement: string) => void) {
    this.collectionGroupToEdit = group;
    this.collectionGroupChange = onchange ?? null;
    this.#openPopup = "collection-groups";
  }

  collectionGroupChanged(name: string, replacement: string) {
    this.collectionGroupChange?.(name, replacement);
  }

  /**
   * Which popup overlay is open.
   *
   * Purely in-memory UI state - popups are never reflected in the URL, so
   * they're never linkable/bookmarkable, never recreated by browser
   * back/forward navigation or a page refresh, and never interact with the
   * router in any way.
   */
  #openPopup = $state<PopupType>(null);

  get openPopup(): PopupType {
    return this.#openPopup;
  }

  openPopupByName(name: PopupType) {
    this.#openPopup = name;
  }

  openOperations(tab: OperationsTab = "assets") {
    this.operationsTab = tab;
    this.#openPopup = "operations";
  }

  closePopup() {
    this.#openPopup = null;
    this.collectionGroupChange = null;
  }

  /** Which top-level tab (movies/shows) is active, derived from the URL. */
  get sidebarTab(): SidebarTab {
    return routeScope().tab;
  }

  /** Whether the sidebar is showing individual items or server collections, derived from the URL. */
  get sidebarMode(): SidebarMode {
    return routeScope().mode;
  }

  get sidebarSource() {
    return routeScope().source;
  }

  get currentFilters(): FilterState {
    return this.sidebarTab === "movie" ? this.movieFilters : this.showFilters;
  }

  saveFilters() {
    writeJson("movieFilters", this.movieFilters);
    writeJson("showFilters", this.showFilters);
  }

  setFilters(value: FilterState) {
    // Number inputs can bind zero or negative bounds; those mean "no bound".
    const filters = normalizeFilters(value);
    if (this.sidebarTab === "movie") {
      this.movieFilters = filters;
    } else {
      this.showFilters = filters;
    }
    this.saveFilters();
  }

  clearFilters() {
    this.setFilters(defaultFilters());
  }
}

export const uiState = new UiState();
