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
  import ScheduleSaveButton from "../ScheduleSaveButton.svelte";
  import JobFooter from "./JobFooter.svelte";
  import CollectionChecklist from "../CollectionChecklist.svelte";
  import LibraryChecklist from "../LibraryChecklist.svelte";
  import FieldRow from "../FieldRow.svelte";
  import Schedules from "../Schedules.svelte";
  import Select from "../Select.svelte";
  import { fromLabels } from "../../utils/selectOptions";
  import {
    createSyncScheduleMutation,
    deleteSyncScheduleMutation,
    getCatalogStatusOptions,
    listServerLibrariesOptions,
    listSyncSchedulesOptions,
    runSyncMutation,
    runSyncScheduleMutation,
    stopSyncMutation,
    updateSyncScheduleMutation,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import { settingsState } from "../../stores/settingsState.svelte";
  import { syncState } from "../../stores/jobStates.svelte";
  import { syncSelection } from "../../stores/syncSelection.svelte";
  import { collectionSummary } from "../../utils/assetsPopup";
  import { librarySummary } from "../../utils/libraries.svelte";
  import {
    choosableCollections,
    collectionGroupNames,
  } from "../../utils/collectionGroups.svelte";
  import { errorMessage } from "../../utils/errors";
  import { OperationRun } from "../../utils/operationRun.svelte";
  import { formatDateInTimezone } from "../../utils/popupFormat";
  import {
    chosenApart,
    chosenTitles,
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
  const MODE_OPTIONS = fromLabels(MODE_LABELS);
  const THEME_ORDER_OPTIONS = fromLabels(THEME_ORDER_LABELS);

  const scheduleTypeId = $props.id();
  const libraryKeys = (available: ServerLibraryRead[]) => available.map((library) => library.key);

  const librariesQuery = createQuery(() => ({
    ...listServerLibrariesOptions(),
    enabled: isActive,
  }));
  const catalogStatusQuery = createQuery(() => ({
    ...getCatalogStatusOptions(),
    enabled: isActive,
  }));
  syncSelection.restore();
  let libraries: ServerLibraryRead[] = $derived(librariesQuery.data ?? []);
  let selectedLibraryIds = $derived(
    filterAvailableValues(
      syncSelection.libraries ?? libraryKeys(libraries),
      libraryKeys(libraries),
    ),
  );
  /** Results show exactly while a run exists, never ahead of the server's answer. */
  const run = new OperationRun("sync", {
    blocker: () =>
      loading
        ? "Loading the libraries..."
        : configurationError
          ? "The libraries could not be loaded"
          : hasSelectedLibraries ||
              collectionsChosen ||
              (libraries.length === 0 && settingsState.current.tmdb_configured)
            ? null
            : "Choose a library or collections",
    results: () => ["sync"],
    stopping: () => syncState.stopping,
  });
  let catalogEnabled = $derived(!!catalogStatusQuery.data?.enabled);
  let catalogStatusError = $derived(
    catalogStatusQuery.error
      ? errorMessage(catalogStatusQuery.error, "Failed to load OvertureDB status")
      : "",
  );
  let loading = $derived(librariesQuery.isPending);
  let configurationError = $derived(
    librariesQuery.error
      ? errorMessage(librariesQuery.error, "Failed to load sync configuration")
      : "",
  );

  let collectionsSupported = $derived(settingsState.current.collections_supported);
  let includeCollections = $derived(syncSelection.allCollections);
  const collectionGroups = collectionGroupNames(() => isActive && collectionsSupported);
  /** The saved group choice, less groups that no longer exist. */
  let selectedCollectionGroups = $derived(
    filterAvailableValues(syncSelection.groups, collectionGroups()),
  );
  const collections = choosableCollections(() => isActive && collectionsSupported);
  /** The saved collection choice, less collections that no longer exist or a group covers. */
  let selectedCollectionIds = $derived(
    chosenApart(syncSelection.collectionIds, collections(), selectedCollectionGroups),
  );

  let scheduleMode = $state<SyncScheduleMode>("full");
  let scheduleCronExpression = $state("0 * * * *");
  let downloadOvertureDbArt = $state(false);
  let downloadThemes = $state<IncrementalThemeOrder>("off");

  const runSyncRequest = createMutation(() => runSyncMutation());
  const stopSyncRequest = createMutation(() => stopSyncMutation());
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

  let checklistLibraries = $derived(libraries.map((library) => ({ ...library, id: library.key })));
  let hasSelectedLibraries = $derived(
    !loading && !configurationError && selectedLibraryIds.length > 0,
  );
  /** Collections chosen for a full sync, which alone can make a run. */
  let collectionsChosen = $derived(
    collectionsSupported &&
      (includeCollections ||
        selectedCollectionGroups.length > 0 ||
        selectedCollectionIds.length > 0),
  );
  // What a schedule may download depends on OvertureDB, so it waits for its status.
  let scheduleBlocker = $derived(
    !hasSelectedLibraries && !(scheduleMode === "full" && collectionsChosen)
      ? scheduleMode === "full"
        ? "Choose a library or collections"
        : "Choose a library"
      : !catalogStatusQuery.isSuccess
        ? "Waiting for the OvertureDB status"
        : !scheduleController.name.trim()
          ? "Name the schedule"
          : !scheduleCronExpression.trim()
            ? "Choose when it runs"
            : null,
  );
  let canSaveSchedule = $derived(scheduleBlocker === null);

  function saveSelection() {
    syncSelection.save(selectedLibraryIds);
  }

  /**
   * Every collection, or only the chosen groups and collections; none skips
   * collections. Collections without a library sync alone, from what earlier
   * syncs stored.
   */
  function collectionScope(): Pick<
    SyncScheduleConfigInput,
    "include_collections" | "collection_groups" | "collection_ids" | "items"
  > {
    const items = hasSelectedLibraries || !collectionsChosen;
    if (!collectionsSupported || includeCollections || !collectionsChosen)
      return { include_collections: includeCollections, items };
    return {
      include_collections: false,
      ...(selectedCollectionGroups.length && { collection_groups: selectedCollectionGroups }),
      ...(selectedCollectionIds.length && { collection_ids: selectedCollectionIds }),
      items,
    };
  }

  function toggleAll(checked: boolean) {
    syncSelection.libraries = selectedValuesForAll(checked, libraryKeys(libraries));
  }

  function toggleLibrary(key: string) {
    syncSelection.libraries = toggleSelectedValue(selectedLibraryIds, key);
  }

  function scheduleConfig(): SyncScheduleConfigInput {
    const incremental = scheduleMode === "incremental" && catalogEnabled;
    return {
      mode: scheduleMode,
      // Polling only adds items, so it leaves collections alone.
      ...(scheduleMode === "full" ? collectionScope() : { include_collections: includeCollections }),
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
    syncSelection.allCollections = saved.include_collections;
    syncSelection.groups = saved.collection_groups ?? [];
    syncSelection.collectionIds = saved.collection_ids ?? [];
    scheduleCronExpression = schedule.cron_expression;
    downloadOvertureDbArt = saved.download_overturedb_art;
    downloadThemes = saved.download_themes;
    // A schedule without libraries syncs all of them, unless it syncs only collections.
    syncSelection.libraries = !saved.items
      ? []
      : saved.library_ids.length
        ? saved.library_ids
        : null;
  }

  function runNow() {
    return run.start(async () => {
      saveSelection();
      await runSyncRequest.mutateAsync({
        body: { library_ids: selectedLibraryIds, ...collectionScope() },
      });
      syncState.markStartAccepted();
    }, "Sync failed");
  }

  function stopSync() {
    return run.stop(async () => {
      await stopSyncRequest.mutateAsync({});
      syncState.markStopRequested();
    }, "Stop failed");
  }

  onMount(() => {
    onfooterchange?.(syncFooter);
  });
</script>

{#if !run.hasResults}
  <CardColumn>
    <div class="option-card">
      <LibraryChecklist
        libraries={checklistLibraries}
        selectedIds={selectedLibraryIds}
        {loading}
        error={configurationError}
        onretry={() => librariesQuery.refetch()}
        ontoggle={toggleLibrary}
        ontoggleall={toggleAll}
      />
      {#if collectionsSupported && scheduleMode === "full"}
        <CollectionChecklist
          groups={collectionGroups()}
          choice={{ all: includeCollections, groups: selectedCollectionGroups }}
          onchange={(choice) => {
            syncSelection.allCollections = choice.all;
            syncSelection.groups = choice.groups;
          }}
          collections={collections()}
          collectionIds={selectedCollectionIds}
          oncollectionschange={(ids) => (syncSelection.collectionIds = ids)}
        />
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
          <FieldRow
            label="Schedule type"
            for={scheduleTypeId}
            hint={scheduleMode === "incremental"
              ? "Adds new items only; Run now always syncs fully."
              : undefined}
          >
            <Select
              id={scheduleTypeId}
              options={MODE_OPTIONS}
              bind:value={scheduleMode}
            />
          </FieldRow>
          {#if scheduleMode === "incremental"}
            <label
              class={[
                "form-row justify-between",
                { "option-card-disabled": !catalogEnabled },
              ]}
            >
              <span>Download OvertureDB art for new media</span>
              <input
                type="checkbox"
                bind:checked={downloadOvertureDbArt}
                disabled={!catalogEnabled}
              />
            </label>
            <div
              class={[
                "form-row justify-between",
                { "option-card-disabled": !catalogEnabled },
              ]}
            >
              <label for={`${scheduleTypeId}-themes`}>Download themes for new media</label>
              <Select
                id={`${scheduleTypeId}-themes`}
                compact
                disabled={!catalogEnabled}
                options={THEME_ORDER_OPTIONS}
                bind:value={downloadThemes}
              />
            </div>
            {#if !catalogEnabled && !catalogStatusError}
              <p class="hint">Enable OvertureDB to use these.</p>
            {/if}
          {/if}
          {#if catalogStatusError}
            <div class="heading-row">
              <span class="option-error">{catalogStatusError}</span>
              <button class="btn btn-ghost btn-sm" onclick={() => catalogStatusQuery.refetch()}>
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
        <div>
          Libraries: {!schedule.config.items
            ? "None"
            : schedule.config.library_ids.length
              ? librarySummary(schedule.config.library_ids, checklistLibraries)
              : "All libraries"}
        </div>
        {#if schedule.config.mode === "full" && collectionsSupported}
          <div>
            Collections: {collectionSummary(
              schedule.config.include_collections,
              schedule.config.collection_groups,
              chosenTitles(schedule.config.collection_ids, collections()),
            )}
          </div>
        {/if}
        {#if schedule.config.mode === "incremental"}
          <div>
            Download OvertureDB art: {schedule.config.download_overturedb_art ? "Yes" : "No"}
          </div>
          <div>Download themes: {THEME_ORDER_LABELS[schedule.config.download_themes]}</div>
          {#each Object.entries(schedule.state.checkpoints) as [serverId, checkpoint] (serverId)}
            <div>
              Checkpoint{settingsState.multipleServers
                ? ` (${settingsState.server(Number(serverId))?.title ?? "removed server"})`
                : ""}: {formatDateInTimezone(checkpoint, schedule.timezone)}
            </div>
          {/each}
        {/if}
      {/snippet}
    </Schedules>
  </CardColumn>
{:else}
  <JobPanel
    job={syncState}
    unit="items"
    stats={[
      { label: "added", value: syncState.count("Added"), title: "New library items", tone: "info" },
      {
        label: "updated",
        value: syncState.count("Updated"),
        title: "Items whose metadata, art, files or seasons changed",
        tone: "accent",
      },
      { label: "unchanged", value: syncState.count("Unchanged") },
      {
        label: "removed",
        value: syncState.count("Removed"),
        title: "No longer on the server; hidden, files kept",
      },
      { label: "errors", value: syncState.count("Error"), tone: "danger" },
    ]}
  />
{/if}

{#snippet syncFooter()}
  <JobFooter {run} onstop={stopSync}>
    {#snippet start()}
      <ScheduleSaveButton
        controller={scheduleController}
        blocker={scheduleBlocker}
        onsave={saveSchedule}
      />
      <PendingButton
        class="btn btn-primary"
        onclick={runNow}
        title={run.blocked ?? undefined}
        disabled={!!run.blocked}
        pending={run.starting}
        pendingLabel="Starting..."
      >
        <RefreshCw size={15} />
        Run now
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
</style>
