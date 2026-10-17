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
  import JobCount from "../JobCount.svelte";
  import JobElapsedTime from "../JobElapsedTime.svelte";
  import JobResults from "../JobResults.svelte";
  import PendingButton from "../PendingButton.svelte";
  import JobFooter from "./JobFooter.svelte";
  import LibraryChecklist from "../LibraryChecklist.svelte";
  import ScheduleForm from "../ScheduleForm.svelte";
  import ScheduleList from "../ScheduleList.svelte";
  import {
    createSyncScheduleMutation,
    deleteSyncScheduleMutation,
    getPublicDatasetStatusOptions,
    listServerLibrariesOptions,
    listSyncSchedulesOptions,
    runSyncMutation,
    runSyncScheduleMutation,
    stopSyncMutation,
    updateSyncScheduleMutation,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import { libraryGate } from "../../stores/libraryGate.svelte";
  import { createNotifier } from "../../stores/notificationState.svelte";
  import { settingsState } from "../../stores/settingsState.svelte";
  import { syncState } from "../../stores/jobStates.svelte";
  import { librarySummary } from "../../utils/assetsPopup";
  import { errorMessage } from "../../utils/errors";
  import { createClearResults } from "../../utils/jobSnapshots";
  import { formatDateInTimezone, formatDuration } from "../../utils/popupFormat";
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

  const libraryKeys = (available: ServerLibraryRead[]) => available.map((library) => library.key);

  /** The tab loads its data once it is first shown, and keeps it fresh after. */
  let hasActivated = $state(false);
  $effect(() => {
    if (isActive) hasActivated = true;
  });

  const librariesQuery = createQuery(() => ({
    ...listServerLibrariesOptions(),
    enabled: hasActivated,
  }));
  const datasetStatusQuery = createQuery(() => ({
    ...getPublicDatasetStatusOptions(),
    enabled: hasActivated,
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
    enabled: hasActivated,
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
    scheduleCronExpression = schedule.cron_expression;
    downloadOvertureDbArt = saved.download_overturedb_art;
    downloadThemes = saved.download_themes;
    // A schedule without libraries syncs all of them.
    librarySelection = saved.library_ids.length ? saved.library_ids : null;
  }

  async function runNow() {
    if (!canRunSync || libraryGate.syncBlocked || runSyncRequest.isPending) return;
    saveSelection();
    feedback.clear();
    try {
      await runSyncRequest.mutateAsync({ body: { library_ids: selectedLibraryIds } });
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
  <div class="option-card">
    <span class="form-label">Libraries</span>
    <LibraryChecklist
      movieLibraries={movieChecklistLibraries}
      showLibraries={showChecklistLibraries}
      selectedIds={selectedLibraryIds}
      {loading}
      error={configurationError}
      onretry={() => librariesQuery.refetch()}
      ontoggle={toggleLibrary}
      ontoggleall={toggleAll}
    />
  </div>

  <ScheduleForm
    controller={scheduleController}
    cronExpression={scheduleCronExpression}
    namePlaceholder="Hourly sync"
    presets={CRON_PRESETS[scheduleMode]}
    oncronchange={(value) => (scheduleCronExpression = value)}
  >
    <div class="schedule-config">
      <label class="form-row justify-between">
        <span>Schedule type</span>
        <select class="select-compact" bind:value={scheduleMode}>
          <option value="full">{MODE_LABELS.full}</option>
          <option value="incremental">{MODE_LABELS.incremental}</option>
        </select>
      </label>
      {#if scheduleMode === "incremental"}
        <div class="schedule-meta">
          Only adds new items. The first run sets a starting point; Run Now is always a full sync.
        </div>
        <label class="form-row justify-between" class:option-card-disabled={!publicDatasetEnabled}>
          <span>Download OvertureDB art for new media</span>
          <input
            type="checkbox"
            bind:checked={downloadOvertureDbArt}
            disabled={!publicDatasetEnabled}
          />
        </label>
        <label class="form-row justify-between" class:option-card-disabled={!publicDatasetEnabled}>
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
        {#if !publicDatasetStatusError}
          <div class="schedule-meta">
            {publicDatasetEnabled
              ? "Only fills in missing files; existing files are kept."
              : "Enable OvertureDB to use these."}
          </div>
        {/if}
      {/if}
      {#if publicDatasetStatusError}
        <div class="schedule-meta">
          <span class="sync-error">{publicDatasetStatusError}</span>
          <button class="btn btn-ghost btn-sm" onclick={() => datasetStatusQuery.refetch()}>
            Retry
          </button>
        </div>
      {/if}
    </div>
  </ScheduleForm>

  <ScheduleList
    controller={scheduleController}
    emptyMessage="No saved sync schedules."
    onedit={editSchedule}
  >
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
        {#if schedule.state.last_duration_seconds !== null}
          <div>
            Last poll: {formatDuration(schedule.state.last_duration_seconds)},
            {schedule.state.last_items_added ?? 0}
            {schedule.state.last_items_added === 1 ? "item" : "items"} added,
            {schedule.state.last_downloads ?? 0}
            {schedule.state.last_downloads === 1 ? "download" : "downloads"}
          </div>
        {/if}
      {/if}
    {/snippet}
  </ScheduleList>
{:else}
  {#snippet syncStats()}
    <div class="stats-row">
      <JobCount job={syncState} unit="items" />
      <div class="stat-item" title="New library items">
        added: <span class="stat-value text-info">{syncState.counters.added}</span>
      </div>
      <div class="stat-item" title="Items whose metadata, art, files or seasons changed">
        updated: <span class="stat-value text-accent">{syncState.counters.updated}</span>
      </div>
      <div class="stat-item">
        unchanged: <span class="stat-value">{syncState.counters.unchanged}</span>
      </div>
      <div class="stat-item" title="No longer on the server; hidden, files kept">
        removed: <span class="stat-value">{syncState.counters.removed}</span>
      </div>
      <div class="stat-item">
        errors: <span class="stat-value text-danger">{syncState.errors}</span>
      </div>
      <JobElapsedTime startedAt={syncState.started_at} finishedAt={syncState.finished_at} />
    </div>
  {/snippet}
  <JobResults progress={syncState.progress} log={syncState.log} stats={syncStats} />
{/if}

{#snippet syncFooter()}
  <JobFooter
    {hasResults}
    running={syncState.running}
    blocked={libraryGate.syncBlocked}
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
        disabled={!canRunSync || !!libraryGate.syncBlocked}
        pending={runSyncRequest.isPending}
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
    gap: var(--space-3);
    margin-top: var(--space-3);
  }
  .schedule-meta {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }
</style>
