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
  import ScheduleSaveButton from "../ScheduleSaveButton.svelte";
  import JobFooter from "./JobFooter.svelte";
  import {
    createBulkAssetsScheduleMutation,
    deleteBulkAssetsScheduleMutation,
    getLibrariesOptions,
    getCatalogStatusOptions,
    listBulkAssetsSchedulesOptions,
    runBulkAssetsScheduleMutation,
    startBulkAssetsMutation,
    stopBulkAssetsMutation,
    updateBulkAssetsScheduleMutation,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import { settingsState } from "../../stores/settingsState.svelte";
  import { matchState, themeJobState } from "../../stores/bulkJobState.svelte";
  import { buildBulkAssetsStopRequest, type BulkAssetsRequest } from "../../utils/assetsPopup";
  import { errorMessage } from "../../utils/errors";
  import { OperationRun } from "../../utils/operationRun.svelte";
  import { AssetsForm } from "../../utils/assetsForm.svelte";
  import {
    choosableCollections,
    collectionGroupNames,
  } from "../../utils/collectionGroups.svelte";
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
  const catalogStatusQuery = createQuery(() => ({
    ...getCatalogStatusOptions(),
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
  let catalogEnabled = $derived(!!catalogStatusQuery.data?.enabled);
  let catalogStatusError = $derived(
    catalogStatusQuery.error
      ? errorMessage(catalogStatusQuery.error, "Failed to load OvertureDB status")
      : "",
  );
  let collectionsSupported = $derived(settingsState.current.collections_supported);
  const collectionGroups = collectionGroupNames(() => isActive && collectionsSupported);
  const form = new AssetsForm({
    movieLibraries: () => movieLibraries,
    showLibraries: () => showLibraries,
    librariesLoaded: () => librariesLoaded,
    catalogEnabled: () => catalogEnabled,
    collectionGroups,
    collections: choosableCollections(() => isActive && collectionsSupported),
  });
  const config = form.config;

  const run = new OperationRun("assets", {
    blocker: () => form.blocker,
    results: () => [
      ...(matchState.hasRun ? (["bulk_art"] as const) : []),
      ...(themeJobState.hasRun ? (["bulk_theme"] as const) : []),
    ],
    stopping: () => matchState.stopping || themeJobState.stopping,
  });
  const { feedback } = run;
  const startJobRequest = createMutation(() => startBulkAssetsMutation());
  const stopJobRequest = createMutation(() => stopBulkAssetsMutation());
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

  /** Why the schedule cannot be saved, or null when it can. */
  let scheduleBlocker = $derived(
    config.useSidebarItems
      ? "A schedule runs over libraries or collections, not the sidebar's items"
      : (form.blocker ??
          (!scheduleController.name.trim()
            ? "Name the schedule"
            : !config.scheduleCronExpression.trim()
              ? "Choose when it runs"
              : null)),
  );
  let canSaveSchedule = $derived(scheduleBlocker === null);

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

  function startJob() {
    return run.start(async () => {
      config.save();
      const result = await startJobRequest.mutateAsync({ body: form.request() });
      const messages: string[] = [];
      // An accepted run switches to results through its job state; a refused
      // one leaves the form exactly as it was.
      if (result.art !== "not_requested") matchState.markStartAccepted();
      if (result.themes !== "not_requested") themeJobState.markStartAccepted();
      if (result.art === "already_running") messages.push("Art is already running.");
      if (result.themes === "already_running") messages.push("Themes are already running.");
      if (messages.length) feedback.info(messages.join(" "));
    }, "Bulk assets failed");
  }

  function stopJob() {
    const body = buildBulkAssetsStopRequest(matchState.running, themeJobState.running);
    if (!body.art && !body.themes) return;
    return run.stop(async () => {
      await stopJobRequest.mutateAsync({ body });
      if (body.art) matchState.markStopRequested();
      if (body.themes) themeJobState.markStopRequested();
    }, "Could not stop the assets job. Please retry.");
  }
</script>

{#if !run.hasResults}
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
      {catalogStatusError}
    />

    <AssetsSchedulePanel
      canSchedule={!config.useSidebarItems}
      scheduleCronExpression={config.scheduleCronExpression}
      controller={scheduleController}
      libraries={[...movieLibraries, ...showLibraries]}
      collections={form.collectionOptions}
      oncronchange={(value) => (config.scheduleCronExpression = value)}
      onedit={editSchedule}
    />
  </CardColumn>
{:else}
  <AssetsResultsView />
{/if}

{#snippet assetsFooter()}
  <JobFooter {run} onstop={stopJob}>
    {#snippet start()}
      <ScheduleSaveButton
        controller={scheduleController}
        blocker={scheduleBlocker}
        onsave={saveSchedule}
      />
      <PendingButton
        class="btn btn-primary"
        onclick={startJob}
        title={run.blocked ?? undefined}
        disabled={!!run.blocked}
        pending={run.starting}
        pendingLabel="Starting..."
      >
        <Image size={15} />
        Run now
      </PendingButton>
    {/snippet}
  </JobFooter>
{/snippet}
