import type {
  ArtType,
  BulkAssetsScheduleResponse,
  LibrarySectionRead,
  RecentUnit,
} from "../../generated/rest/types.gen";
import { ASSETS_MATCH_THRESHOLD_DEFAULT } from "../../generated/settings";
import { sidebarState } from "../stores/sidebarState.svelte";
import { assetsInScope } from "./artTypes";
import {
  DEFAULT_ART_SOURCE_ORDER,
  DEFAULT_THEME_SOURCE_ORDER,
  buildBulkAssetsRequest,
  clampBulkThreshold,
  disabledSources,
  enabledSources,
  moveOrderedSource,
  normaliseSelectedSources,
  normaliseSourceOrder,
  restoreLibrarySelection,
  selectAllLibraries,
  selectedIncludesShowLibrary,
  type ArtAssetSource,
  type AssetsConfig,
  type BulkAssetsRequest,
  type ThemeAssetSource,
} from "./assetsPopup";
import { DEFAULT_CRON_EXPRESSION } from "./cronPresets";
import { persistedState } from "./persistedState.svelte";
import { toggleSelectedValue } from "./popupSelection";

/** What the form reads from the server: the libraries and whether OvertureDB is on. */
export interface AssetsFormSource {
  movieLibraries(): LibrarySectionRead[];
  showLibraries(): LibrarySectionRead[];
  librariesLoaded(): boolean;
  publicDatasetEnabled(): boolean;
}

/**
 * The Assets run the user is setting up: its remembered options, what they
 * select, and the request they make. Create it during component initialisation.
 */
export class AssetsForm {
  readonly config: AssetsConfig = persistedState("assetsPopup", {
    selectedLibraries: [] as string[],
    useSidebarItems: false,
    includeCollections: false,
    includeUnmonitored: false,
    overwriteExisting: false,
    retrySavedDownloads: false,
    enableArt: true,
    enableThemes: true,
    artTypes: [] as ArtType[],
    artSourceOrder: {
      default: DEFAULT_ART_SOURCE_ORDER,
      revive: (value: ArtAssetSource[]) => normaliseSourceOrder(value, DEFAULT_ART_SOURCE_ORDER),
    },
    selectedArtSources: {
      default: DEFAULT_ART_SOURCE_ORDER,
      revive: (value: ArtAssetSource[]) =>
        normaliseSelectedSources(value, DEFAULT_ART_SOURCE_ORDER),
    },
    themeSourceOrder: {
      default: DEFAULT_THEME_SOURCE_ORDER,
      revive: (value: ThemeAssetSource[]) =>
        normaliseSourceOrder(value, DEFAULT_THEME_SOURCE_ORDER),
    },
    selectedThemeSources: {
      default: DEFAULT_THEME_SOURCE_ORDER,
      revive: (value: ThemeAssetSource[]) =>
        normaliseSelectedSources(value, DEFAULT_THEME_SOURCE_ORDER),
    },
    threshold: {
      default: ASSETS_MATCH_THRESHOLD_DEFAULT,
      revive: clampBulkThreshold,
    },
    skipRecentVal: 0,
    skipRecentUnit: "hours" as RecentUnit,
    scheduleCronExpression: DEFAULT_CRON_EXPRESSION,
  });

  private readonly source: AssetsFormSource;

  constructor(source: AssetsFormSource) {
    this.source = source;
  }

  get movieLibraries(): LibrarySectionRead[] {
    return this.source.movieLibraries();
  }

  get showLibraries(): LibrarySectionRead[] {
    return this.source.showLibraries();
  }

  /** Catalog sources stay chosen while OvertureDB is off; they are only left out. */
  readonly disabledSources = $derived.by(() => disabledSources(this.source.publicDatasetEnabled()));

  /** The saved library choice, less libraries the server no longer has. */
  readonly selectedLibraries = $derived.by(() =>
    restoreLibrarySelection(this.movieLibraries, this.showLibraries, this.config.selectedLibraries),
  );

  readonly collectionScope = $derived(
    this.config.useSidebarItems && sidebarState.collections !== null,
  );

  readonly hasShowLibraries = $derived.by(() =>
    this.config.useSidebarItems
      ? sidebarState.current?.type === "show"
      : selectedIncludesShowLibrary(this.selectedLibraries, this.showLibraries),
  );

  readonly hasSelectedLibraries = $derived.by(() =>
    this.config.useSidebarItems
      ? !!(sidebarState.current?.itemIds.length || sidebarState.collections?.collectionIds.length)
      : this.source.librariesLoaded() && this.selectedLibraries.length > 0,
  );

  readonly activeArtSources = $derived.by(() =>
    enabledSources(
      this.config.artSourceOrder,
      this.config.selectedArtSources,
      this.source.publicDatasetEnabled(),
    ),
  );

  readonly activeThemeSources = $derived.by(() =>
    enabledSources(
      this.config.themeSourceOrder,
      this.config.selectedThemeSources,
      this.source.publicDatasetEnabled(),
    ),
  );

  readonly localArtMatchingEnabled = $derived(this.activeArtSources.includes("local_art_matching"));

  /** The chosen art types the selection has items for: season posters need shows. */
  readonly artTypesToRun = $derived(
    assetsInScope(this.config.artTypes, {
      hasSelection: this.hasSelectedLibraries,
      hasShows: this.hasShowLibraries,
    }),
  );

  readonly canRun = $derived.by(() => {
    const { enableArt, enableThemes } = this.config;
    const artReady =
      !enableArt ||
      this.collectionScope ||
      (this.artTypesToRun.length > 0 && this.activeArtSources.length > 0);
    const themesReady = !enableThemes || this.activeThemeSources.length > 0;
    return (
      this.hasSelectedLibraries &&
      ((enableArt && !this.collectionScope) || enableThemes) &&
      artReady &&
      themesReady
    );
  });

  request(): BulkAssetsRequest {
    const { config } = this;
    return buildBulkAssetsRequest({
      selectedLibraries: this.selectedLibraries,
      itemIds:
        config.useSidebarItems && !this.collectionScope
          ? (sidebarState.current?.itemIds ?? [])
          : undefined,
      collectionIds: this.collectionScope ? sidebarState.collections?.collectionIds : undefined,
      includeCollections: config.includeCollections,
      includeUnmonitored: config.includeUnmonitored,
      overwriteExisting: config.overwriteExisting,
      retrySavedDownloads: config.retrySavedDownloads,
      skipRecentVal: config.skipRecentVal,
      skipRecentUnit: config.skipRecentUnit,
      enableArt: config.enableArt,
      artTypes: this.artTypesToRun,
      activeArtSources: this.activeArtSources,
      threshold: config.threshold,
      enableThemes: config.enableThemes,
      activeThemeSources: this.activeThemeSources,
    });
  }

  toggleAll(checked: boolean): void {
    this.config.useSidebarItems = false;
    this.config.selectedLibraries = selectAllLibraries(
      checked,
      this.movieLibraries,
      this.showLibraries,
    );
  }

  toggleLibrary(id: string): void {
    this.config.selectedLibraries = this.config.useSidebarItems
      ? [id]
      : toggleSelectedValue(this.selectedLibraries, id);
    this.config.useSidebarItems = false;
  }

  toggleArtType(type: ArtType): void {
    this.config.artTypes = toggleSelectedValue(this.config.artTypes, type);
  }

  toggleArtSource(source: ArtAssetSource): void {
    if (this.disabledSources.includes(source)) return;
    this.config.selectedArtSources = toggleSelectedValue(this.config.selectedArtSources, source);
  }

  toggleThemeSource(source: ThemeAssetSource): void {
    if (this.disabledSources.includes(source)) return;
    this.config.selectedThemeSources = toggleSelectedValue(
      this.config.selectedThemeSources,
      source,
    );
  }

  moveArtSource(source: ArtAssetSource, target: ArtAssetSource): void {
    this.config.artSourceOrder = moveOrderedSource(this.config.artSourceOrder, source, target);
  }

  moveThemeSource(source: ThemeAssetSource, target: ThemeAssetSource): void {
    this.config.themeSourceOrder = moveOrderedSource(this.config.themeSourceOrder, source, target);
  }

  /** Load a saved schedule's options into the form, to edit it. */
  applySchedule(schedule: BulkAssetsScheduleResponse): void {
    const { config } = this;
    const saved = schedule.config;
    config.useSidebarItems = false;
    config.includeUnmonitored = saved.include_unmonitored;
    config.overwriteExisting = saved.overwrite_existing;
    config.retrySavedDownloads = saved.retry_saved_downloads;
    config.scheduleCronExpression = schedule.cron_expression;
    config.selectedLibraries = restoreLibrarySelection(
      this.movieLibraries,
      this.showLibraries,
      saved.library_ids,
    );
    config.skipRecentVal = saved.skip_recent_val;
    config.skipRecentUnit = saved.skip_recent_unit;
    config.enableArt = !!saved.art;
    config.enableThemes = !!saved.themes;
    config.includeCollections = saved.themes?.include_collections ?? false;
    if (saved.art) {
      config.artTypes = saved.art.art_types;
      config.artSourceOrder = normaliseSourceOrder(
        saved.art.source_order,
        DEFAULT_ART_SOURCE_ORDER,
      );
      config.selectedArtSources = normaliseSelectedSources(
        saved.art.source_order,
        DEFAULT_ART_SOURCE_ORDER,
      );
      config.threshold = clampBulkThreshold(saved.art.threshold);
    }
    if (saved.themes) {
      config.themeSourceOrder = normaliseSourceOrder(
        saved.themes.source_order,
        DEFAULT_THEME_SOURCE_ORDER,
      );
      config.selectedThemeSources = normaliseSelectedSources(
        saved.themes.source_order,
        DEFAULT_THEME_SOURCE_ORDER,
      );
    }
  }
}
