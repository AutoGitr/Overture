<script lang="ts">
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import { createMutation, createQuery, useQueryClient } from "@tanstack/svelte-query";
  import { exportPublicDatasetSelections } from "../../generated/rest/sdk.gen";
  import type { PublicDatasetStatus } from "../../generated/rest/types.gen";
  import {
    getPublicDatasetStatusOptions,
    getCatalogCountsOptions,
    getSettingsOptions,
    setPublicDatasetEnabledMutation,
    syncPublicDatasetNowMutation,
    updateSettingsMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { invalidateTags } from "../rest/cache";
  import { settingsState } from "../stores/settingsState.svelte";
  import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
  import { discardDrafts, draftedEntries } from "../utils/catalogDrafts";
  import { publicDatasetSyncState } from "../stores/jobStates.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { errorMessage } from "../utils/errors";
  import { formatBytes, formatDateInTimezone } from "../utils/popupFormat";
  import CardColumn from "../components/CardColumn.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import PendingButton from "../components/PendingButton.svelte";

  const datasetQuery = createQuery(() => getPublicDatasetStatusOptions());

  const countsQuery = createQuery(() => ({
    ...getCatalogCountsOptions(),
    enabled: datasetQuery.data?.enabled === true,
  }));
  let draftCount = $derived(countsQuery.data?.drafts ?? null);

  const queryClient = useQueryClient();

  let publicDatasetEnabled = $state(false);
  /** The OvertureDB settings the app settings hold, edited here. */
  let noTheme = $state(settingsState.current.overturedb_no_theme);
  let browse = $state(settingsState.current.overturedb_browse);
  let settingsDirty = $derived(
    noTheme !== settingsState.current.overturedb_no_theme ||
      browse !== settingsState.current.overturedb_browse,
  );
  const saveSettingsRequest = createMutation(() => updateSettingsMutation());
  const feedback = createNotifier();
  const exportRequest = createMutation(() => ({
    mutationFn: async () => (await exportPublicDatasetSelections({ throwOnError: true })).data,
  }));

  async function exportSelections() {
    feedback.clear();
    try {
      const data = await exportRequest.mutateAsync();
      const url = URL.createObjectURL(data);
      const link = document.createElement("a");
      link.href = url;
      link.download = "overturedb-selections.zip";
      link.click();
      // Following the link resolves the blob URL at once, so the download
      // keeps the archive after the URL is revoked.
      URL.revokeObjectURL(url);
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to export selections"));
      return;
    }
    await offerDraftDiscard();
  }

  /** Drafts the export carried are done with once they reach an issue. */
  async function offerDraftDiscard() {
    if (!draftCount) return;
    const confirmed = await confirmAction({
      title: "Discard exported drafts?",
      message:
        "Keep them until the contribution is merged if you may edit it; discard them once it is attached to an issue.",
      confirmLabel: "Discard drafts",
      destructive: true,
    });
    if (!confirmed) return;
    try {
      feedback.success(`Discarded ${await discardDrafts(await draftedEntries())} drafts.`);
    } catch (err) {
      feedback.error(errorMessage(err, "Could not discard the drafts"));
    }
  }
  let draftInitialised = false;
  let publicDatasetStatus = $derived<PublicDatasetStatus | null>(datasetQuery.data ?? null);
  let savedEnabled = $derived(!!publicDatasetStatus?.enabled);
  let enabledDirty = $derived(publicDatasetEnabled !== savedEnabled);
  let stats = $derived(publicDatasetStatus?.last_stats ?? null);
  const saveEnabledRequest = createMutation(() => setPublicDatasetEnabledMutation());
  let saving = $derived(saveEnabledRequest.isPending || saveSettingsRequest.isPending);
  const syncRequest = createMutation(() => syncPublicDatasetNowMutation());
  // A sync always runs for a while, so show it from the click instead of after a settle delay.
  let publicDatasetBusy = $derived(syncRequest.isPending || publicDatasetSyncState.running);

  $effect(() => {
    if (!draftInitialised && publicDatasetStatus) {
      publicDatasetEnabled = publicDatasetStatus.enabled;
      draftInitialised = true;
    }
  });

  function formatDateTime(value: string | null | undefined) {
    return value ? formatDateInTimezone(value, publicDatasetStatus?.timezone) : "Never";
  }

  async function save() {
    if (saving || !publicDatasetStatus || datasetQuery.error) return;
    feedback.clear();
    try {
      if (settingsDirty) {
        const fresh = await saveSettingsRequest.mutateAsync({
          body: { overturedb_no_theme: noTheme, overturedb_browse: browse },
        });
        queryClient.setQueryData(getSettingsOptions().queryKey, fresh);
        // Theme completeness of titles and collections follows the flag setting.
        void invalidateTags(["library", "collections"]);
      }
      if (enabledDirty) {
        const status = await saveEnabledRequest.mutateAsync({
          body: { enabled: publicDatasetEnabled },
        });
        queryClient.setQueryData(getPublicDatasetStatusOptions().queryKey, status);
        publicDatasetEnabled = status.enabled;
      }
      feedback.success("OvertureDB settings saved.");
    } catch (err) {
      publicDatasetEnabled = savedEnabled;
      feedback.error(errorMessage(err, "Failed to save OvertureDB settings"));
    }
  }

  async function syncPublicDatasetNow() {
    if (publicDatasetBusy) return;
    feedback.clear();
    try {
      const result = await syncRequest.mutateAsync({});
      if (result.status === "disabled") {
        feedback.warning("Enable and save OvertureDB before syncing.");
        return;
      }
      publicDatasetSyncState.markStartAccepted();
    } catch (err) {
      feedback.error(errorMessage(err, "OvertureDB sync failed"));
    }
  }
</script>

<PopupShell title="OvertureDB" onclose={() => uiState.closePopup()}>
  <CardColumn>
    <DataStatus
      label="OvertureDB status"
      error={datasetQuery.error}
      loading={datasetQuery.isFetching}
      hasData={!!publicDatasetStatus}
      onretry={() => datasetQuery.refetch()}
    />
    {#if publicDatasetStatus}
      <div class="option-card">
        <span class="form-label">Settings</span>
        <div class="options-col">
          <label class="form-row justify-between">
            <span>Enable OvertureDB</span>
            <input
              type="checkbox"
              bind:checked={publicDatasetEnabled}
              disabled={saving || publicDatasetBusy || !!datasetQuery.error}
            />
          </label>
          <label class="form-row justify-between">
            <span>Trust OvertureDB's No theme flag</span>
            <input type="checkbox" bind:checked={noTheme} disabled={saving || !publicDatasetEnabled} />
          </label>
          <span class="hint"
            >A title OvertureDB marks as having no theme music counts as complete, and theme runs
            skip it.</span
          >
          <label class="form-row justify-between">
            <span>Browse OvertureDB in the sidebar</span>
            <input type="checkbox" bind:checked={browse} disabled={saving || !publicDatasetEnabled} />
          </label>
        </div>
      </div>

      <div class="option-card">
        <span class="form-label">Status</span>
        <div class="options-col">
          <div class="dataset-meta">
            <span>Repository</span>
            {#if publicDatasetStatus?.repo_url}
              <a
                href={publicDatasetStatus.repo_url}
                target="_blank"
                rel="noopener noreferrer"
                class="dataset-link"
                title={publicDatasetStatus.repo_url}
              >
                <code>{publicDatasetStatus.repo_url}</code>
                <ExternalLink size={12} />
              </a>
            {:else}
              <code>Not configured</code>
            {/if}
          </div>
          <div class="dataset-meta">
            <span>Catalog</span>
            <code>{publicDatasetStatus?.catalog_url || "Not configured"}</code>
          </div>
          <div class="dataset-meta">
            <span>Last sync</span>
            <span>{formatDateTime(publicDatasetStatus?.last_synced_at)}</span>
          </div>
          <div class="dataset-meta">
            <span>Status</span>
            <span>{publicDatasetStatus?.last_status || "never_synced"}</span>
          </div>
          <div class="dataset-meta">
            <span>Next sync</span>
            <span>
              {savedEnabled ? formatDateTime(publicDatasetStatus?.next_run) : "Disabled"}
            </span>
          </div>
          <button
            class="btn btn-secondary btn-sm self-start"
            onclick={syncPublicDatasetNow}
            disabled={!savedEnabled || publicDatasetBusy || enabledDirty || !!datasetQuery.error}
          >
            {publicDatasetBusy ? "Syncing..." : "Sync OvertureDB Now"}
          </button>
          {#if publicDatasetSyncState.error}
            <span class="dataset-error" role="alert">{publicDatasetSyncState.error}</span>
          {/if}
        </div>
      </div>
      <div class="option-card">
        <span class="form-label">Synced File</span>
        {#if stats}
          <div class="stats-grid">
            {#each [["Movies", stats.movies], ["Shows", stats.shows], ["Collections", stats.collections], ["Seasons", stats.seasons], ["Errors", stats.errors]] as const as [label, count] (label)}
              <div class="stat-card">
                <span>{label}</span>
                <strong>{count.toLocaleString()}</strong>
              </div>
            {/each}
          </div>
          <div class="options-col">
            <div class="dataset-meta">
              <span>Compressed</span>
              <span>{formatBytes(stats.catalog_bytes)}</span>
            </div>
            <div class="dataset-meta">
              <span>Unpacked</span>
              <span>{formatBytes(stats.catalog_uncompressed_bytes)}</span>
            </div>
            <div class="dataset-meta">
              <span>Schema</span>
              <span>{stats.schema_version ?? "Unknown"}</span>
            </div>
          </div>
        {:else}
          <span class="hint">No synced file statistics yet.</span>
        {/if}
      </div>
    {/if}
    <div class="option-card">
      <span class="form-label">Bulk contribution</span>
      <div class="options-col">
        <span class="hint">
          Export local catalog drafts and saved artwork, season posters, and theme selections as a
          ZIP. Check the export report, then attach the ZIP to a Bulk contribution issue on GitHub.
          Only selections missing from OvertureDB are added.
        </span>
        {#if countsQuery.data}<span class="hint"
            >{countsQuery.data.collections} catalog {countsQuery.data.collections === 1
              ? "collection"
              : "collections"}</span
          >{/if}
        {#if draftCount !== null}<span class="hint"
            >{draftCount} local {draftCount === 1 ? "draft" : "drafts"}</span
          >{/if}
        {#if countsQuery.isError}<DataStatus
            label="draft count"
            error={countsQuery.error}
            hasData={false}
            loading={false}
            onretry={() => countsQuery.refetch()}
          />{/if}
        <div class="flex gap-2 self-start">
          <PendingButton
            class="btn btn-secondary btn-sm"
            onclick={exportSelections}
            pending={exportRequest.isPending}
            pendingLabel="Exporting..."
          >
            Export selections
          </PendingButton>
          {#if publicDatasetStatus?.repo_url}
            <a
              class="btn btn-secondary btn-sm"
              href={`${publicDatasetStatus.repo_url.replace(/\/$/, "")}/issues/new?template=bulk.yml`}
              target="_blank"
              rel="noopener noreferrer"
            >
              Create issue
            </a>
          {/if}
        </div>
      </div>
    </div>
  </CardColumn>
  {#snippet footer()}
    <button class="btn btn-secondary" onclick={() => uiState.closePopup()}>Cancel</button>
    <PendingButton
      class="btn btn-primary"
      onclick={save}
      pending={saving}
      pendingLabel="Saving..."
      disabled={!(enabledDirty || settingsDirty) || !publicDatasetStatus || !!datasetQuery.error}
    >
      Save
    </PendingButton>
  {/snippet}
</PopupShell>

<style>
  .dataset-meta {
    display: grid;
    grid-template-columns: 110px minmax(0, 1fr);
    gap: var(--space-3);
    align-items: center;
    font-size: var(--text-xs);
    color: var(--text-secondary);
  }
  .dataset-meta code {
    min-width: 0;
    word-break: break-all;
    white-space: normal;
    color: var(--text-tertiary);
  }
  .dataset-link {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-width: 0;
    max-width: 100%;
    color: var(--accent);
    text-decoration: none;
  }
  .dataset-link:hover {
    color: var(--accent-hover);
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  .dataset-link:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: var(--radius-sm);
  }
  .dataset-link code {
    color: inherit;
    cursor: pointer;
  }
  .dataset-link :global(svg) {
    flex-shrink: 0;
  }
  .dataset-error {
    font-size: var(--text-xs);
    color: var(--danger);
  }
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(80px, 1fr));
    gap: var(--space-2);
    margin-top: var(--space-2);
  }
  .stat-card {
    display: flex;
    flex-direction: column;
    gap: 2px;
    padding: var(--space-2);
    background: var(--bg-tertiary);
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
  }
  .stat-card span {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }
  .stat-card strong {
    font-size: var(--text-sm);
    color: var(--text-primary);
  }

  @media (max-width: 480px) {
    .dataset-meta {
      grid-template-columns: 80px minmax(0, 1fr);
    }

    .stats-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
