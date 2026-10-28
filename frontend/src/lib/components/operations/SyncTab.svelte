<script lang="ts">
  import RefreshCw from "@lucide/svelte/icons/refresh-cw";
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import { onMount, type Snippet } from "svelte";
  import type {
    IncrementalThemeOrder,
    ServerLibraryRead,
    SyncScheduleConfigInput,
    SyncScheduleMode,
    SyncScheduleResponse,
  } from "../../../generated/rest/types.gen";
  import CardColumn from "../CardColumn.svelte";
  import JobPanel from "../JobPanel.svelte";
  import PendingButton from "../PendingButton.svelte";
  import JobFooter from "./JobFooter.svelte";
  import LibraryChecklist from "../LibraryChecklist.svelte";
  import Schedules from "../Schedules.svelte";
  import {
    createSyncScheduleMutation,
    deleteSyncScheduleMutation,
    getPublicDatasetStatusOptions,
    listCollectionGroupsOptions,
    listServerLibrariesOptions,
    listSyncSchedulesOptions,
    runSyncMutation,
    runSyncScheduleMutation,
    stopSyncMutation,
    syncCollectionGroupMutation,
    updateSyncScheduleMutation,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import { libraryGate } from "../../stores/libraryGate.svelte";
  import { createNotifier } from "../../stores/notificationState.svelte";
  import { settingsState } from "../../stores/settingsState.svelte";
  import { syncState } from "../../stores/jobStates.svelte";
  import { librarySummary } from "../../utils/assetsPopup";
  import { errorMessage } from "../../utils/errors";
  import { createClearResults } from "../../utils/jobSnapshots";
  import { formatDateInTimezone } from "../../utils/popupFormat";
  import {
    filterAvailableValues,
    selectedValuesForAll,
    toggleSelectedValue,
  } from "../../utils/popupSelection";
  import {
    POLLING_CRON_PRESETS,
    ROUTINE_CRON_PRESETS,
    type CronPreset,
  } from "../../utils/cronPresets";
  import { ScheduleController } from "../../utils/schedules.svelte";
  import { readJson, writeJson } from "../../utils/storage";

  let {
    isActive = false,
    onfooterchange,
  }: {
    isActive?: boolean;
    onfooterchange?: (footer: Snippet) => void;
  } = $props();

  const CRON_PRESETS: Record<SyncScheduleMode, readonly CronPreset[]> = {
    full: ROUTINE_CRON_PRESETS,
    incremental: POLLING_CRON_PRESETS,
  };
  const MODE_LABELS: Record<SyncScheduleMode, string> = {
    full: "Full sync",
    incremental: "New-media polling",
  };
  const THEME_ORDER_LABELS: Record<IncrementalThemeOrder, string> = {
    off: "Disabled",
    overturedb_themerrdb: "OvertureDB -> ThemerrDB",
    themerrdb_overturedb: "ThemerrDB -> OvertureDB",
  };

  const scheduleTypeId = $props.id();
  const libraryKeys = (available: ServerLibraryRead[]) => available.map((library) => library.key);

  const librariesQuery = createQuery(() => ({
    ...listServerLibrariesOptions(),
    enabled: isActive,
  }));
  const datasetStatusQuery = createQuery(() => ({
    ...getPublicDatasetStatusOptions(),
    enabled: isActive,
  }));
  let libraries: ServerLibraryRead[] = $derived(librariesQuery.data ?? []);
  /** The chosen libraries; `null` until a choice is made means all of them. */
  let librarySelection = $state<string[] | null>(
    readJson<string[] | null>("syncPopup_selectedLibraries", null),
  );
  let selectedLibraryIds = $derived(
    filterAvailableValues(librarySelection ?? libraryKeys(libraries), libraryKeys(libraries)),
  );
  /** Results show exactly while a run exists, never ahead of the server's answer. */
  let hasResults = $derived(syncState.hasRun);
  const feedback = createNotifier();
  let publicDatasetEnabled = $derived(!!datasetStatusQuery.data?.enabled);
  let publicDatasetStatusError = $derived(
    datasetStatusQuery.error
      ? errorMessage(datasetStatusQuery.error, "Failed to load OvertureDB status")
      : "",
  );
  let loading = $derived(librariesQuery.isPending);
  let configurationError = $derived(
    librariesQuery.error
      ? errorMessage(librariesQuery.error, "Failed to load sync configuration")
      : "",
  );

  let includeCollections = $state(readJson<boolean>("syncPopup_includeCollections", true));

  const groupQueries = (["movie", "show"] as const).map((mediaType) => ({
    mediaType,
    query: createQuery(() => ({
      ...listCollectionGroupsOptions({ query: { media_type: mediaType } }),
      enabled: isActive && settingsState.current.collections_supported,
    })),
  }));
  let collectionGroups = $derived(
    groupQueries.flatMap(({ mediaType, query }) =>
      (query.data ?? []).map((name) => ({ mediaType, name, key: `${mediaType}:${name}` })),
    ),
  );
  /** A group Run Now syncs on its own, instead of a full sync; empty for all. */
  let collectionGroupKey = $state("");
  let collectionGroup = $derived(
    collectionGroups.find((group) => group.key === collectionGroupKey),
  );
  const syncGroupRequest = createMutation(() => syncCollectionGroupMutation());

  let scheduleMode = $state<SyncScheduleMode>("full");
  let scheduleCronExpression = $state("0 * * * *");
  let downloadOvertureDbArt = $state(false);
  let downloadThemes = $state<IncrementalThemeOrder>("off");

  const runSyncRequest = createMutation(() => runSyncMutation());
  const stopSyncRequest = createMutation(() => stopSyncMutation());
  let stopping = $derived(stopSyncRequest.isPending || syncState.stopping);
  const clearResults = createClearResults(() => ["sync"], feedback);
  const createScheduleRequest = createMutation(() => createSyncScheduleMutation());
  const updateScheduleRequest = createMutation(() => updateSyncScheduleMutation());
  const deleteScheduleRequest = createMutation(() => deleteSyncScheduleMutation());
  const runScheduleRequest = createMutation(() => runSyncScheduleMutation());
  const schedulesQuery = createQuery(() => ({
    ...listSyncSchedulesOptions(),
    enabled: isActive,
  }));
  const scheduleController = new ScheduleController<SyncScheduleConfigInput, SyncScheduleResponse>({
    list: schedulesQuery,
    create: createScheduleRequest,
    update: updateScheduleRequest,
    remove: deleteScheduleRequest,
    run: runScheduleRequest,
  });

  let checklistLibraries = $derived(
    libraries.map((library) => ({ id: library.key, title: library.title })),
  );
  let movieChecklistLibraries = $derived(
    libraries
      .filter((library) => library.media_type === "movie")
      .map((library) => ({ id: library.key, title: library.title })),
  );
  let showChecklistLibraries = $derived(
    libraries
      .filter((library) => library.media_type === "show")
      .map((library) => ({ id: library.key, title: library.title })),
  );
  let hasSelectedLibraries = $derived(
    !loading && !configurationError && selectedLibraryIds.length > 0,
  );
  let canRunSync = $derived(
    !loading &&
      !configurationError &&
      (hasSelectedLibraries || (libraries.length === 0 && settingsState.current.tmdb_configured)),
  );
  // What a schedule may download depends on OvertureDB, so it waits for its status.
  let canSaveSchedule = $derived(
    hasSelectedLibraries &&
      datasetStatusQuery.isSuccess &&
      scheduleController.name.trim().length > 0 &&
      scheduleCronExpression.trim().length > 0,
  );

  function saveSelection() {
    writeJson("syncPopup_selectedLibraries", selectedLibraryIds);
    writeJson("syncPopup_includeCollections", includeCollections);
  }

  function toggleAll(checked: boolean) {
    librarySelection = selectedValuesForAll(checked, libraryKeys(libraries));
  }

  function toggleLibrary(key: string) {
    librarySelection = toggleSelectedValue(selectedLibraryIds, key);
  }

  function scheduleConfig(): SyncScheduleConfigInput {
    const incremental = scheduleMode === "incremental" && publicDatasetEnabled;
    return {
      mode: scheduleMode,
      include_collections: includeCollections,
      library_ids: selectedLibraryIds,
      download_overturedb_art: incremental && downloadOvertureDbArt,
      download_themes: incremental ? downloadThemes : "off",
    };
  }

  async function saveSchedule() {
    if (!canSaveSchedule) return;
    saveSelection();
    await scheduleController.save(scheduleCronExpression, scheduleConfig());
  }

  function editSchedule(schedule: SyncScheduleResponse) {
    scheduleController.beginEdit(schedule);
    const saved = schedule.config;
    scheduleMode = saved.mode;
    includeCollections = saved.include_collections;
    scheduleCronExpression = schedule.cron_expression;
    downloadOvertureDbArt = saved.download_overturedb_art;
    downloadThemes = saved.download_themes;
    // A schedule without libraries syncs all of them.
    librarySelection = saved.library_ids.length ? saved.library_ids : null;
  }

  async function syncGroup(group: { mediaType: "movie" | "show"; name: string }) {
    if (syncGroupRequest.isPending) return;
    feedback.clear();
    try {
      const result = await syncGroupRequest.mutateAsync({
        query: { media_type: group.mediaType, name: group.name },
      });
      const failed = Object.keys(result.errors).length;
      feedback.success(
        `Synced ${result.synced} collections in ${group.name}` +
          (failed ? `; ${failed} failed` : "") +
          ".",
      );
    } catch (err) {
      feedback.error(errorMessage(err, "Group sync failed"));
    }
  }

  async function runNow() {
    if (collectionGroup) {
      await syncGroup(collectionGroup);
      return;
    }
    if (!canRunSync || libraryGate.blocked("sync") || runSyncRequest.isPending) return;
    saveSelection();
    feedback.clear();
    try {
      await runSyncRequest.mutateAsync({
        body: { library_ids: selectedLibraryIds, include_collections: includeCollections },
      });
      syncState.markStartAccepted();
    } catch (err) {
      feedback.error(errorMessage(err, "Sync failed"));
    }
  }

  async function stopSync() {
    if (stopSyncRequest.isPending) return;
    feedback.clear();
    try {
      await stopSyncRequest.mutateAsync({});
      syncState.markStopRequested();
    } catch (err) {
      feedback.error(errorMessage(err, "Stop failed"));
    }
  }

  onMount(() => {
    onfooterchange?.(syncFooter);
  });
</script>

{#if !hasResults}
  <CardColumn>
    <div class="option-card">
      <LibraryChecklist
        movieLibraries={movieChecklistLibraries}
        showLibraries={showChecklistLibraries}
        selectedIds={selectedLibraryIds}
        {loading}
        error={configurationError}
        onretry={() => librariesQuery.refetch()}
        ontoggle={toggleLibrary}
        ontoggleall={toggleAll}
        collections={settingsState.current.collections_supported && scheduleMode === "full"
          ? includeCollections
          : undefined}
        oncollectionschange={(checked) => (includeCollections = checked)}
      />
      {#if settingsState.current.collections_supported && collectionGroups.length}
        <label class="form-row">
          <span>Collections</span>
          <select bind:value={collectionGroupKey} aria-label="Collections to sync">
            <option value="">All, with the libraries</option>
            {#each collectionGroups as group (group.key)}
              <option value={group.key}>Group: {group.name} ({group.mediaType})</option>
            {/each}
          </select>
        </label>
        {#if collectionGroup}
          <p class="hint">Run Now syncs only this group's collections, not the libraries.</p>
        {/if}
      {/if}
    </div>

    <Schedules
      controller={scheduleController}
      emptyMessage="No saved sync schedules."
      onedit={editSchedule}
      cronExpression={scheduleCronExpression}
      namePlaceholder="Hourly sync"
      presets={CRON_PRESETS[scheduleMode]}
      oncronchange={(value) => (scheduleCronExpression = value)}
    >
      {#snippet settings()}
        <div class="schedule-config">
          <div class="form-row">
            <label for={scheduleTypeId}>Schedule type</label>
            {#if scheduleMode === "incremental"}
              <span class="hint">adds new items only; Run Now always syncs fully</span>
            {/if}
            <select
              id={scheduleTypeId}
              class="select-compact type-select"
              bind:value={scheduleMode}
            >
              <option value="full">{MODE_LABELS.full}</option>
              <option value="incremental">{MODE_LABELS.incremental}</option>
            </select>
          </div>
          {#if scheduleMode === "incremental"}
            <label
              class={[
                "form-row justify-between",
                { "option-card-disabled": !publicDatasetEnabled },
              ]}
            >
              <span>Download OvertureDB art for new media</span>
              <input
                type="checkbox"
                bind:checked={downloadOvertureDbArt}
                disabled={!publicDatasetEnabled}
              />
            </label>
            <label
              class={[
                "form-row justify-between",
                { "option-card-disabled": !publicDatasetEnabled },
              ]}
            >
              <span>Download themes for new media</span>
              <select
                class="select-compact"
                bind:value={downloadThemes}
                disabled={!publicDatasetEnabled}
              >
                {#each Object.entries(THEME_ORDER_LABELS) as [value, label] (value)}
                  <option {value}>{label}</option>
                {/each}
              </select>
            </label>
            {#if !publicDatasetEnabled && !publicDatasetStatusError}
              <p class="hint">Enable OvertureDB to use these.</p>
            {/if}
          {/if}
          {#if publicDatasetStatusError}
            <div class="heading-row">
              <span class="option-error">{publicDatasetStatusError}</span>
              <button class="btn btn-ghost btn-sm" onclick={() => datasetStatusQuery.refetch()}>
                Retry
              </button>
            </div>
          {/if}
        </div>
      {/snippet}
      {#snippet badges(schedule)}
        <span class="badge badge-muted">{MODE_LABELS[schedule.config.mode]}</span>
      {/snippet}
      {#snippet details(schedule)}
        <div>Libraries: {librarySummary(schedule.config.library_ids, checklistLibraries)}</div>
        {#if schedule.config.mode === "incremental"}
          <div>
            Download OvertureDB art: {schedule.config.download_overturedb_art ? "Yes" : "No"}
          </div>
          <div>Download themes: {THEME_ORDER_LABELS[schedule.config.download_themes]}</div>
          {#if schedule.state.checkpoint}
            <div>
              Checkpoint: {formatDateInTimezone(schedule.state.checkpoint, schedule.timezone)}
            </div>
          {/if}
        {/if}
      {/snippet}
    </Schedules>
  </CardColumn>
{:else}
  <JobPanel
    job={syncState}
    unit="items"
    stats={[
      { label: "added", value: syncState.counters.added, title: "New library items", tone: "info" },
      {
        label: "updated",
        value: syncState.counters.updated,
        title: "Items whose metadata, art, files or seasons changed",
        tone: "accent",
      },
      { label: "unchanged", value: syncState.counters.unchanged },
      {
        label: "removed",
        value: syncState.counters.removed,
        title: "No longer on the server; hidden, files kept",
      },
      { label: "errors", value: syncState.errors, tone: "danger" },
    ]}
  />
{/if}

{#snippet syncFooter()}
  <JobFooter
    {hasResults}
    running={syncState.running}
    blocked={libraryGate.blocked("sync")}
    {stopping}
    onstop={stopSync}
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
        onclick={runNow}
        disabled={collectionGroup ? false : !canRunSync || !!libraryGate.blocked("sync")}
        pending={runSyncRequest.isPending || syncGroupRequest.isPending}
        pendingLabel="Starting..."
      >
        <RefreshCw size={15} />
        Run Now
      </PendingButton>
    {/snippet}
  </JobFooter>
{/snippet}

<style>
  .schedule-config {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }

  .type-select {
    margin-left: auto;
  }
</style>
