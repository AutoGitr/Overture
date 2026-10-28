<script lang="ts">
  import Image from "@lucide/svelte/icons/image";
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import { onMount, type Snippet } from "svelte";
  import type {
    BulkAssetsScheduleResponse,
    LibrarySectionRead,
  } from "../../../generated/rest/types.gen";
  import CardColumn from "../CardColumn.svelte";
  import AssetsConfigurationPanel from "../AssetsConfigurationPanel.svelte";
  import AssetsResultsView from "../AssetsResultsView.svelte";
  import AssetDownloads from "../AssetDownloads.svelte";
  import AssetsSchedulePanel from "../AssetsSchedulePanel.svelte";
  import PendingButton from "../PendingButton.svelte";
  import JobFooter from "./JobFooter.svelte";
  import {
    createBulkAssetsScheduleMutation,
    deleteBulkAssetsScheduleMutation,
    getLibrariesOptions,
    getPublicDatasetStatusOptions,
    listCollectionGroupsOptions,
    listBulkAssetsSchedulesOptions,
    runBulkAssetsScheduleMutation,
    startBulkAssetsMutation,
    stopBulkAssetsMutation,
    updateBulkAssetsScheduleMutation,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import { libraryGate } from "../../stores/libraryGate.svelte";
  import { settingsState } from "../../stores/settingsState.svelte";
  import { createNotifier } from "../../stores/notificationState.svelte";
  import { OPERATIONS } from "../../stores/operations";
  import { matchState, themeJobState } from "../../stores/bulkJobState.svelte";
  import { buildBulkAssetsStopRequest, type BulkAssetsRequest } from "../../utils/assetsPopup";
  import { errorMessage } from "../../utils/errors";
  import { createClearResults } from "../../utils/jobSnapshots";
  import { AssetsForm } from "../../utils/assetsForm.svelte";
  import { ScheduleController } from "../../utils/schedules.svelte";

  let {
    isActive = false,
    onfooterchange,
  }: {
    isActive?: boolean;
    onfooterchange?: (footer: Snippet) => void;
  } = $props();

  const movieLibrariesQuery = createQuery(() => ({
    ...getLibrariesOptions({ query: { media_type: "movie" } }),
    enabled: isActive,
  }));
  const showLibrariesQuery = createQuery(() => ({
    ...getLibrariesOptions({ query: { media_type: "show" } }),
    enabled: isActive,
  }));
  const datasetStatusQuery = createQuery(() => ({
    ...getPublicDatasetStatusOptions(),
    enabled: isActive,
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
  let collectionsSupported = $derived(settingsState.current.collections_supported);
  const movieGroupsQuery = createQuery(() => ({
    ...listCollectionGroupsOptions({ query: { media_type: "movie" } }),
    enabled: isActive && collectionsSupported,
  }));
  const showGroupsQuery = createQuery(() => ({
    ...listCollectionGroupsOptions({ query: { media_type: "show" } }),
    enabled: isActive && collectionsSupported,
  }));
  let collectionGroups = $derived([
    ...new Set([...(movieGroupsQuery.data ?? []), ...(showGroupsQuery.data ?? [])]),
  ]);
  const form = new AssetsForm({
    movieLibraries: () => movieLibraries,
    showLibraries: () => showLibraries,
    librariesLoaded: () => librariesLoaded,
    publicDatasetEnabled: () => publicDatasetEnabled,
    collectionGroups: () => collectionGroups,
  });
  const config = form.config;

  const feedback = createNotifier();

  let hasResults = $derived(OPERATIONS.assets.hasRun);
  let anyRunning = $derived(OPERATIONS.assets.running);

  const startJobRequest = createMutation(() => startBulkAssetsMutation());
  const stopJobRequest = createMutation(() => stopBulkAssetsMutation());
  let stopping = $derived(
    stopJobRequest.isPending || matchState.stopping || themeJobState.stopping,
  );
  const clearResults = createClearResults(
    () => [
      ...(matchState.hasRun ? (["bulk_art"] as const) : []),
      ...(themeJobState.hasRun ? (["bulk_theme"] as const) : []),
    ],
    feedback,
  );
  const createScheduleRequest = createMutation(() => createBulkAssetsScheduleMutation());
  const updateScheduleRequest = createMutation(() => updateBulkAssetsScheduleMutation());
  const deleteScheduleRequest = createMutation(() => deleteBulkAssetsScheduleMutation());
  const runScheduleRequest = createMutation(() => runBulkAssetsScheduleMutation());
  const schedulesQuery = createQuery(() => ({
    ...listBulkAssetsSchedulesOptions(),
    enabled: isActive,
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
      form.canRun &&
      scheduleController.name.trim().length > 0 &&
      config.scheduleCronExpression.trim().length > 0,
  );

  $effect(() => {
    if (!librariesLoaded) return;
    config.save();
  });

  onMount(() => {
    onfooterchange?.(assetsFooter);
  });

  async function saveSchedule() {
    if (!canSaveSchedule) return;
    config.save();
    feedback.clear();
    await scheduleController.save(config.scheduleCronExpression, form.request());
  }

  function editSchedule(schedule: BulkAssetsScheduleResponse) {
    scheduleController.beginEdit(schedule);
    form.applySchedule(schedule);
  }

  async function startJob() {
    if (!form.canRun || libraryGate.blocked("assets") || startJobRequest.isPending) return;
    config.save();
    feedback.clear();
    try {
      const result = await startJobRequest.mutateAsync({ body: form.request() });
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
    const stopArt = matchState.running;
    const stopThemes = themeJobState.running;
    const body = buildBulkAssetsStopRequest(stopArt, stopThemes);
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
  <CardColumn>
    <AssetDownloads />
    <AssetsConfigurationPanel
      {form}
      librariesLoading={!librariesLoaded && !librariesError}
      {librariesError}
      onretrylibraries={() => {
        void movieLibrariesQuery.refetch();
        void showLibrariesQuery.refetch();
      }}
      {publicDatasetStatusError}
    />

    <AssetsSchedulePanel
      canSchedule={!config.useSidebarItems}
      scheduleCronExpression={config.scheduleCronExpression}
      controller={scheduleController}
      libraries={[...movieLibraries, ...showLibraries]}
      oncronchange={(value) => (config.scheduleCronExpression = value)}
      onedit={editSchedule}
    />
  </CardColumn>
{:else}
  <AssetsResultsView />
{/if}

{#snippet assetsFooter()}
  <JobFooter
    {hasResults}
    running={anyRunning}
    blocked={libraryGate.blocked("assets")}
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
        disabled={!form.canRun || !!libraryGate.blocked("assets")}
        pending={startJobRequest.isPending}
        pendingLabel="Starting..."
      >
        <Image size={15} />
        Run Now
      </PendingButton>
    {/snippet}
  </JobFooter>
{/snippet}
