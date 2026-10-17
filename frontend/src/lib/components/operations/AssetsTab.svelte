<script lang="ts">
  import Image from "@lucide/svelte/icons/image";
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import { onMount, type Snippet } from "svelte";
  import type {
    ArtType,
    BulkAssetsScheduleResponse,
    LibrarySectionRead,
    RecentUnit,
  } from "../../../generated/rest/types.gen";
  import { ASSETS_MATCH_THRESHOLD_DEFAULT } from "../../../generated/settings";
  import AssetsConfigurationPanel from "../AssetsConfigurationPanel.svelte";
  import AssetsResultsView from "../AssetsResultsView.svelte";
  import AssetsSchedulePanel from "../AssetsSchedulePanel.svelte";
  import PendingButton from "../PendingButton.svelte";
  import JobFooter from "./JobFooter.svelte";
  import {
    createBulkAssetsScheduleMutation,
    deleteBulkAssetsScheduleMutation,
    getLibrariesOptions,
    getPublicDatasetStatusOptions,
    listBulkAssetsSchedulesOptions,
    runBulkAssetsScheduleMutation,
    startBulkAssetsMutation,
    stopBulkAssetsMutation,
    updateBulkAssetsScheduleMutation,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import { libraryGate } from "../../stores/libraryGate.svelte";
  import { createNotifier } from "../../stores/notificationState.svelte";
  import { matchState } from "../../stores/matchState.svelte";
  import { sidebarState } from "../../stores/sidebarState.svelte";
  import { themeJobState } from "../../stores/bulkJobState.svelte";
  import type {
    ArtAssetSource,
    AssetsConfig,
    BulkAssetsRequest,
    ThemeAssetSource,
  } from "../../utils/assetsPopup";
  import {
    DEFAULT_ART_SOURCE_ORDER,
    DEFAULT_THEME_SOURCE_ORDER,
    buildBulkAssetsRequest,
    buildBulkAssetsStopRequest,
    clampBulkThreshold,
    disabledSources,
    enabledSources,
    moveOrderedSource,
    normaliseSelectedSources,
    normaliseSourceOrder,
    restoreLibrarySelection,
    selectAllLibraries,
    selectedIncludesShowLibrary,
  } from "../../utils/assetsPopup";
  import { assetsInScope } from "../../utils/artTypes";
  import { DEFAULT_CRON_EXPRESSION } from "../../utils/cronPresets";
  import { errorMessage } from "../../utils/errors";
  import { createClearResults } from "../../utils/jobSnapshots";
  import { persistedState } from "../../utils/persistedState.svelte";
  import { toggleSelectedValue } from "../../utils/popupSelection";
  import { ScheduleController } from "../../utils/schedules.svelte";

  let {
    isActive = false,
    onfooterchange,
  }: {
    isActive?: boolean;
    onfooterchange?: (footer: Snippet) => void;
  } = $props();

  const config: AssetsConfig = persistedState("assetsPopup", {
    selectedLibraries: [] as string[],
    useSidebarItems: false,
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

  /** The tab loads its data once it is first shown, and keeps it fresh after. */
  let hasActivated = $state(false);
  $effect(() => {
    if (isActive) hasActivated = true;
  });

  const movieLibrariesQuery = createQuery(() => ({
    ...getLibrariesOptions({ query: { media_type: "movie" } }),
    enabled: hasActivated,
  }));
  const showLibrariesQuery = createQuery(() => ({
    ...getLibrariesOptions({ query: { media_type: "show" } }),
    enabled: hasActivated,
  }));
  const datasetStatusQuery = createQuery(() => ({
    ...getPublicDatasetStatusOptions(),
    enabled: hasActivated,
  }));
  let movieLibraries: LibrarySectionRead[] = $derived(movieLibrariesQuery.data ?? []);
  let showLibraries: LibrarySectionRead[] = $derived(showLibrariesQuery.data ?? []);
  let librariesLoaded = $derived(movieLibrariesQuery.isSuccess && showLibrariesQuery.isSuccess);
  let librariesError = $derived.by(() => {
    const error = movieLibrariesQuery.error ?? showLibrariesQuery.error;
    return error ? errorMessage(error, "Failed to load libraries") : "";
  });
  // Sources OvertureDB serves are left out while it is off, never unselected.
  let publicDatasetEnabled = $derived(!!datasetStatusQuery.data?.enabled);
  let publicDatasetStatusError = $derived(
    datasetStatusQuery.error
      ? errorMessage(datasetStatusQuery.error, "Failed to load OvertureDB status")
      : "",
  );
  /** The saved library choice, less libraries the server no longer has. */
  let selectedLibraries = $derived(
    restoreLibrarySelection(movieLibraries, showLibraries, config.selectedLibraries),
  );

  const feedback = createNotifier();

  let artHasResults = $derived(matchState.hasRun);
  let themeHasResults = $derived(themeJobState.hasRun);
  /** Results show exactly while a run exists, never ahead of the server's answer. */
  let hasResults = $derived(artHasResults || themeHasResults);
  let anyRunning = $derived(matchState.running || themeJobState.running);

  let hasShowLibraries = $derived(
    config.useSidebarItems
      ? sidebarState.current?.type === "show"
      : selectedIncludesShowLibrary(selectedLibraries, showLibraries),
  );
  let hasSelectedLibraries = $derived(
    config.useSidebarItems
      ? !!sidebarState.current?.itemIds.length
      : librariesLoaded && selectedLibraries.length > 0,
  );
  let activeArtSources = $derived(
    enabledSources(config.artSourceOrder, config.selectedArtSources, publicDatasetEnabled),
  );
  let activeThemeSources = $derived(
    enabledSources(config.themeSourceOrder, config.selectedThemeSources, publicDatasetEnabled),
  );
  let localArtMatchingEnabled = $derived(activeArtSources.includes("local_art_matching"));
  /** The chosen art types the selection has items for: season posters need shows. */
  let artTypesToRun = $derived(
    assetsInScope(config.artTypes, {
      hasSelection: hasSelectedLibraries,
      hasShows: hasShowLibraries,
    }),
  );
  let canRunArt = $derived(
    !config.enableArt || (artTypesToRun.length > 0 && activeArtSources.length > 0),
  );
  let canRunThemes = $derived(!config.enableThemes || activeThemeSources.length > 0);
  let canRunCurrent = $derived(
    hasSelectedLibraries && (config.enableArt || config.enableThemes) && canRunArt && canRunThemes,
  );
  const startJobRequest = createMutation(() => startBulkAssetsMutation());
  const stopJobRequest = createMutation(() => stopBulkAssetsMutation());
  let stopping = $derived(
    stopJobRequest.isPending || matchState.stopping || themeJobState.stopping,
  );
  const clearResults = createClearResults(
    () => [
      ...(artHasResults ? (["bulk_art"] as const) : []),
      ...(themeHasResults ? (["bulk_theme"] as const) : []),
    ],
    feedback,
  );
  const createScheduleRequest = createMutation(() => createBulkAssetsScheduleMutation());
  const updateScheduleRequest = createMutation(() => updateBulkAssetsScheduleMutation());
  const deleteScheduleRequest = createMutation(() => deleteBulkAssetsScheduleMutation());
  const runScheduleRequest = createMutation(() => runBulkAssetsScheduleMutation());
  const schedulesQuery = createQuery(() => ({
    ...listBulkAssetsSchedulesOptions(),
    enabled: hasActivated,
  }));
  const scheduleController = new ScheduleController<BulkAssetsRequest, BulkAssetsScheduleResponse>({
    list: schedulesQuery,
    create: createScheduleRequest,
    update: updateScheduleRequest,
    remove: deleteScheduleRequest,
    run: runScheduleRequest,
  });

  let canSaveSchedule = $derived(
    !config.useSidebarItems &&
      canRunCurrent &&
      scheduleController.name.trim().length > 0 &&
      config.scheduleCronExpression.trim().length > 0,
  );

  function currentBulkAssetsRequest() {
    return buildBulkAssetsRequest({
      selectedLibraries,
      itemIds: config.useSidebarItems ? (sidebarState.current?.itemIds ?? []) : undefined,
      includeUnmonitored: config.includeUnmonitored,
      overwriteExisting: config.overwriteExisting,
      retrySavedDownloads: config.retrySavedDownloads,
      skipRecentVal: config.skipRecentVal,
      skipRecentUnit: config.skipRecentUnit,
      enableArt: config.enableArt,
      artTypes: artTypesToRun,
      activeArtSources,
      threshold: config.threshold,
      enableThemes: config.enableThemes,
      activeThemeSources,
    });
  }

  $effect(() => {
    if (!librariesLoaded) return;
    config.save();
  });

  onMount(() => {
    onfooterchange?.(assetsFooter);
  });

  function toggleAll(checked: boolean) {
    config.useSidebarItems = false;
    config.selectedLibraries = selectAllLibraries(checked, movieLibraries, showLibraries);
  }

  function toggleLibrary(id: string) {
    config.selectedLibraries = config.useSidebarItems
      ? [id]
      : toggleSelectedValue(selectedLibraries, id);
    config.useSidebarItems = false;
  }

  function toggleArtType(type: ArtType) {
    config.artTypes = toggleSelectedValue(config.artTypes, type);
  }

  function toggleArtSource(source: string) {
    if (disabledSources(publicDatasetEnabled).includes(source)) return;
    config.selectedArtSources = toggleSelectedValue(
      config.selectedArtSources,
      source,
    ) as ArtAssetSource[];
  }

  function toggleThemeSource(source: string) {
    if (disabledSources(publicDatasetEnabled).includes(source)) return;
    config.selectedThemeSources = toggleSelectedValue(
      config.selectedThemeSources,
      source,
    ) as ThemeAssetSource[];
  }

  function moveArtSource(source: string, target: string) {
    config.artSourceOrder = moveOrderedSource(
      config.artSourceOrder,
      source as ArtAssetSource,
      target as ArtAssetSource,
    );
  }

  function moveThemeSource(source: string, target: string) {
    config.themeSourceOrder = moveOrderedSource(
      config.themeSourceOrder,
      source as ThemeAssetSource,
      target as ThemeAssetSource,
    );
  }

  function setThreshold(value: number) {
    config.threshold = value;
  }

  async function saveSchedule() {
    if (!canSaveSchedule) return;
    config.save();
    feedback.clear();
    await scheduleController.save(config.scheduleCronExpression, currentBulkAssetsRequest());
  }

  function editSchedule(schedule: BulkAssetsScheduleResponse) {
    scheduleController.beginEdit(schedule);
    applyScheduleConfig(schedule);
  }

  function applyScheduleConfig(schedule: BulkAssetsScheduleResponse) {
    config.useSidebarItems = false;
    const saved = schedule.config;
    config.includeUnmonitored = saved.include_unmonitored ?? false;
    config.overwriteExisting = saved.overwrite_existing ?? false;
    config.retrySavedDownloads = saved.retry_saved_downloads ?? false;
    config.scheduleCronExpression = schedule.cron_expression;
    config.selectedLibraries = restoreLibrarySelection(
      movieLibraries,
      showLibraries,
      saved.library_ids ?? [],
    );
    config.skipRecentVal = saved.skip_recent_val ?? 0;
    config.skipRecentUnit = saved.skip_recent_unit ?? "hours";
    config.enableArt = !!saved.art;
    config.enableThemes = !!saved.themes;
    if (saved.art) {
      config.artTypes = saved.art.art_types ?? [];
      config.artSourceOrder = normaliseSourceOrder(
        saved.art.source_order ?? DEFAULT_ART_SOURCE_ORDER,
        DEFAULT_ART_SOURCE_ORDER,
      );
      config.selectedArtSources = normaliseSelectedSources(
        saved.art.source_order ?? [],
        DEFAULT_ART_SOURCE_ORDER,
      );
      config.threshold = clampBulkThreshold(saved.art.threshold ?? ASSETS_MATCH_THRESHOLD_DEFAULT);
    }
    if (saved.themes) {
      config.themeSourceOrder = normaliseSourceOrder(
        saved.themes.source_order ?? DEFAULT_THEME_SOURCE_ORDER,
        DEFAULT_THEME_SOURCE_ORDER,
      );
      config.selectedThemeSources = normaliseSelectedSources(
        saved.themes.source_order ?? [],
        DEFAULT_THEME_SOURCE_ORDER,
      );
    }
  }

  async function startJob() {
    if (!canRunCurrent || libraryGate.itemsBlocked || startJobRequest.isPending) return;
    config.save();
    feedback.clear();
    try {
      const result = await startJobRequest.mutateAsync({ body: currentBulkAssetsRequest() });
      const messages: string[] = [];
      // An accepted run switches to results through its job state; a refused
      // one leaves the form exactly as it was.
      if (result.art !== "not_requested") matchState.markStartAccepted();
      if (result.themes !== "not_requested") themeJobState.markStartAccepted();
      if (result.art === "already_running") messages.push("Art is already running.");
      if (result.themes === "already_running") messages.push("Themes are already running.");
      if (messages.length) feedback.info(messages.join(" "));
    } catch (err) {
      feedback.error(errorMessage(err, "Bulk assets failed"));
    }
  }

  async function stopJob() {
    if (stopJobRequest.isPending) return;
    const body = buildBulkAssetsStopRequest(matchState.running, themeJobState.running);
    if (!body.art && !body.themes) return;
    feedback.clear();
    try {
      await stopJobRequest.mutateAsync({ body });
      if (body.art) matchState.markStopRequested();
      if (body.themes) themeJobState.markStopRequested();
    } catch (error) {
      feedback.error(errorMessage(error, "Could not stop the assets job. Please retry."));
    }
  }
</script>

{#if !hasResults}
  <AssetsConfigurationPanel
    librariesLoading={!librariesLoaded && !librariesError}
    {librariesError}
    onretrylibraries={() => {
      void movieLibrariesQuery.refetch();
      void showLibrariesQuery.refetch();
    }}
    {config}
    {movieLibraries}
    {showLibraries}
    useSidebarItems={config.useSidebarItems}
    sidebarItems={sidebarState.current}
    onusesidebaritemschange={(selected) => (config.useSidebarItems = selected)}
    onincludeunmonitoredchange={(value) => (config.includeUnmonitored = value)}
    onoverwriteexistingchange={(value) => (config.overwriteExisting = value)}
    onretrysaveddownloadschange={(value) => (config.retrySavedDownloads = value)}
    {publicDatasetEnabled}
    {publicDatasetStatusError}
    {hasSelectedLibraries}
    {hasShowLibraries}
    {localArtMatchingEnabled}
    ontogglelibrary={toggleLibrary}
    ontoggleall={toggleAll}
    ontoggletype={toggleArtType}
    ontoggleartsource={toggleArtSource}
    ontogglethemesource={toggleThemeSource}
    onmoveartsource={moveArtSource}
    onmovethemesource={moveThemeSource}
    onthresholdchange={setThreshold}
    onenableartchange={(enabled) => (config.enableArt = enabled)}
    onenablethemeschange={(enabled) => (config.enableThemes = enabled)}
    onskiprecentvalchange={(value) => (config.skipRecentVal = value)}
    onskiprecentunitchange={(unit) => (config.skipRecentUnit = unit)}
  />

  <AssetsSchedulePanel
    canSchedule={!config.useSidebarItems}
    scheduleCronExpression={config.scheduleCronExpression}
    controller={scheduleController}
    libraries={[...movieLibraries, ...showLibraries]}
    oncronchange={(value) => (config.scheduleCronExpression = value)}
    onedit={editSchedule}
  />
{:else}
  <AssetsResultsView />
{/if}

{#snippet assetsFooter()}
  <JobFooter
    {hasResults}
    running={anyRunning}
    blocked={libraryGate.itemsBlocked}
    {stopping}
    onstop={stopJob}
    clear={clearResults}
  >
    {#snippet start()}
      <button
        class="btn btn-secondary"
        onclick={saveSchedule}
        disabled={!canSaveSchedule ||
          createScheduleRequest.isPending ||
          updateScheduleRequest.isPending}
      >
        {scheduleController.isEditing ? "Update Schedule" : "Save Schedule"}
      </button>
      <PendingButton
        class="btn btn-primary"
        onclick={startJob}
        disabled={!canRunCurrent || !!libraryGate.itemsBlocked}
        pending={startJobRequest.isPending}
        pendingLabel="Starting..."
      >
        <Image size={15} />
        Run Now
      </PendingButton>
    {/snippet}
  </JobFooter>
{/snippet}
