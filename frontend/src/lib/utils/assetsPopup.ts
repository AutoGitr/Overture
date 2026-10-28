import type {
  ArtBulkSource,
  ArtType,
  BulkAssetsRequestInput,
  BulkAssetsStopRequest,
  LibrarySectionRead,
  RecentUnit,
  ThemeBulkSource,
} from "../../generated/rest/types.gen";
import {
  CATALOG_SOURCES,
  DEFAULT_ART_SOURCE_ORDER as GENERATED_ART_SOURCE_ORDER,
  DEFAULT_THEME_SOURCE_ORDER as GENERATED_THEME_SOURCE_ORDER,
  MATCH_THRESHOLD_MAX,
  PERFECT_MATCH_ONLY,
} from "../../generated/settings";
import { ASSET_LABELS } from "./artTypes";
import { filterAvailableValues, selectedValuesForAll } from "./popupSelection";

export type BulkAssetsRequest = BulkAssetsRequestInput;
export type ArtAssetSource = ArtBulkSource;
export type ThemeAssetSource = ThemeBulkSource;

/** The persisted assets-workflow configuration shared by the popup's panels. */
/** What an Assets run targets when it does not use the sidebar's items. */
export type AssetsScope = "libraries" | "collections";

export interface AssetsConfig {
  selectedLibraries: string[];
  useSidebarItems: boolean;
  scope: AssetsScope;
  /** Collection groups a Collections run covers; none means every collection. */
  collectionGroups: string[];
  includeCollections: boolean;
  includeUnmonitored: boolean;
  overwriteExisting: boolean;
  enableArt: boolean;
  enableThemes: boolean;
  artTypes: ArtType[];
  artSourceOrder: ArtAssetSource[];
  selectedArtSources: ArtAssetSource[];
  themeSourceOrder: ThemeAssetSource[];
  selectedThemeSources: ThemeAssetSource[];
  threshold: number;
  skipRecentVal: number;
  skipRecentUnit: RecentUnit;
  scheduleCronExpression: string;
  save(): void;
}

export const DEFAULT_ART_SOURCE_ORDER: ArtAssetSource[] = [...GENERATED_ART_SOURCE_ORDER];
export const DEFAULT_THEME_SOURCE_ORDER: ThemeAssetSource[] = [...GENERATED_THEME_SOURCE_ORDER];

/** Clamp a stored Assets-run threshold to the range the backend accepts. */
export function clampBulkThreshold(value: number): number {
  return Math.max(PERFECT_MATCH_ONLY, Math.min(MATCH_THRESHOLD_MAX, Math.round(value)));
}

/** Return the combined ids of every movie and show library. */
export function libraryIds(
  movieLibraries: LibrarySectionRead[],
  showLibraries: LibrarySectionRead[],
): string[] {
  return [...movieLibraries, ...showLibraries].map((library) => library.id);
}

/** Restore a stored library selection, dropping libraries that no longer exist. */
export function restoreLibrarySelection(
  movieLibraries: LibrarySectionRead[],
  showLibraries: LibrarySectionRead[],
  storedSelection: string[],
): string[] {
  return filterAvailableValues(storedSelection, libraryIds(movieLibraries, showLibraries));
}

/** Select or deselect every available library. */
export function selectAllLibraries(
  checked: boolean,
  movieLibraries: LibrarySectionRead[],
  showLibraries: LibrarySectionRead[],
): string[] {
  return selectedValuesForAll(checked, libraryIds(movieLibraries, showLibraries));
}

/** Return whether any selected library is a show library. */
export function selectedIncludesShowLibrary(
  selectedLibraries: string[],
  showLibraries: LibrarySectionRead[],
): boolean {
  const showIds = new Set(showLibraries.map((library) => library.id));
  return selectedLibraries.some((id) => showIds.has(id));
}

/** Reorder a stored source order, dropping unknown entries and appending missing defaults. */
export function normaliseSourceOrder<T extends string>(
  value: string[],
  defaults: readonly T[],
): T[] {
  const valid: ReadonlySet<string> = new Set(defaults);
  const ordered = value.filter((source): source is T => valid.has(source));
  for (const source of defaults) {
    if (!ordered.includes(source)) ordered.push(source);
  }
  return ordered;
}

/** Filter a stored source selection down to known sources. */
export function normaliseSelectedSources<T extends string>(
  value: string[],
  defaults: readonly T[],
): T[] {
  const valid: ReadonlySet<string> = new Set(defaults);
  return value.filter((source): source is T => valid.has(source));
}

/** Whether a source is a curated catalog, which only an enabled OvertureDB provides. */
function isDatasetSource(source: string): boolean {
  return CATALOG_SOURCES.some((catalog) => catalog === source);
}

/** Return the ordered sources that are both selected and currently usable. */
export function enabledSources<T extends string>(
  sourceOrder: T[],
  selectedSources: T[],
  publicDatasetEnabled: boolean,
): T[] {
  return sourceOrder.filter(
    (source) =>
      selectedSources.includes(source) && (!isDatasetSource(source) || publicDatasetEnabled),
  );
}

/** Move `source` to sit just before `target` in a source order. */
export function moveOrderedSource<T extends string>(sourceOrder: T[], source: T, target: T): T[] {
  if (source === target) return sourceOrder;
  const targetIndex = sourceOrder.indexOf(target);
  const reordered = sourceOrder.filter((entry) => entry !== source);
  reordered.splice(targetIndex < 0 ? reordered.length : targetIndex, 0, source);
  return reordered;
}

/** Return whether a source is unavailable (currently dataset sources, when disabled). */
export function sourceDisabled(source: string, publicDatasetEnabled: boolean): boolean {
  return isDatasetSource(source) && !publicDatasetEnabled;
}

/** Return the list of sources that should render as disabled. */
export function disabledSources(publicDatasetEnabled: boolean): readonly string[] {
  return publicDatasetEnabled ? [] : CATALOG_SOURCES;
}

export interface BulkAssetsRequestParams {
  selectedLibraries: string[];
  itemIds?: number[];
  collectionIds?: number[];
  /** Groups for a Collections run; an empty list means every collection. */
  collectionGroups?: string[];
  includeCollections?: boolean;
  includeUnmonitored: boolean;
  overwriteExisting: boolean;
  skipRecentVal: number;
  skipRecentUnit: RecentUnit;
  enableArt: boolean;
  artTypes: ArtType[];
  activeArtSources: ArtAssetSource[];
  threshold: number;
  enableThemes: boolean;
  activeThemeSources: ThemeAssetSource[];
}

/** Build the bulk-assets start request from the current popup configuration. */
export function buildBulkAssetsRequest(params: BulkAssetsRequestParams): BulkAssetsRequest {
  const { collectionGroups } = params;
  const libraries =
    params.itemIds === undefined &&
    params.collectionIds === undefined &&
    collectionGroups === undefined;
  return {
    library_ids: libraries ? params.selectedLibraries : [],
    ...(params.itemIds === undefined ? {} : { item_ids: [...params.itemIds] }),
    ...(params.collectionIds === undefined ? {} : { collection_ids: [...params.collectionIds] }),
    ...(collectionGroups === undefined
      ? {}
      : collectionGroups.length
        ? { collection_groups: [...collectionGroups] }
        : { all_collections: true }),
    include_unmonitored: params.includeUnmonitored,
    overwrite_existing: params.overwriteExisting,
    skip_recent_val: params.skipRecentVal,
    skip_recent_unit: params.skipRecentUnit,
    art: params.enableArt
      ? {
          art_types: params.artTypes,
          source_order: params.activeArtSources,
          threshold: params.threshold,
        }
      : null,
    themes: params.enableThemes
      ? {
          source_order: params.activeThemeSources,
          include_collections: params.includeCollections ?? false,
        }
      : null,
  };
}

/** Build the bulk-assets stop request for whichever workflows are running. */
export function buildBulkAssetsStopRequest(
  artRunning: boolean,
  themesRunning: boolean,
): BulkAssetsStopRequest {
  return { art: artRunning, themes: themesRunning };
}

/** The parts of an art or theme job that decide its status label. */
export interface WorkflowStatus {
  status?: string;
  downloading: boolean;
  running: boolean;
  finished_at: string | null;
}

/** Return the human-readable status label for an art/theme workflow with a run. */
export function workflowStatusLabel(job: WorkflowStatus): string {
  if (job.downloading) return "Downloading";
  if (job.running) return "Running";
  if (job.status === "stopped") return "Stopped";
  if (job.status === "failed") return "Failed";
  return job.finished_at ? "Finished" : "Results";
}

/** Render a comma-separated summary of selected library titles. */
export function librarySummary(
  ids: string[],
  libraries: readonly { id: string; title: string }[],
): string {
  if (ids.length === 0) return "All libraries";
  const titles = new Map(libraries.map((library) => [library.id, library.title]));
  return ids.map((id) => titles.get(id) || id).join(", ");
}

/** Render a comma-separated summary of sources using the given labels. */
export function sourceSummary(sources: string[], labels: Record<string, string>): string {
  return sources.map((source) => labels[source] || source).join(", ");
}

/** Render a comma-separated summary of art types. */
export function artTypeSummary(types: ArtType[]): string {
  return types.map((type) => ASSET_LABELS[type]).join(", ");
}

/** Render a short "Art + Themes" summary for a schedule's configured workflows. */
export function workflowSummary(config: BulkAssetsRequest): string {
  return [config.art ? "Art" : "", config.themes ? "Themes" : ""].filter(Boolean).join(" + ");
}
