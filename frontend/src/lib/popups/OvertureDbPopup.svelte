<script lang="ts">
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import { createMutation, useQueryClient } from "@tanstack/svelte-query";
  import { onMount } from "svelte";
  import { exportPublicDatasetSelections } from "../../generated/rest/sdk.gen";
  import type { PublicDatasetStatus } from "../../generated/rest/types.gen";
  import {
    getPublicDatasetStatusOptions,
    setPublicDatasetEnabledMutation,
    syncPublicDatasetNowMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { publicDatasetState } from "../stores/publicDatasetState.svelte";
  import { publicDatasetSyncState } from "../stores/jobStates.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { errorMessage } from "../utils/errors";
  import { formatBytes, formatDateInTimezone } from "../utils/popupFormat";
  import PopupShell from "../components/PopupShell.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import PendingButton from "../components/PendingButton.svelte";

  const queryClient = useQueryClient();

  let publicDatasetEnabled = $state(false);
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
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (err) {
      feedback.error(errorMessage(err, "Failed to export selections"));
    }
  }
  let draftInitialised = false;
  let publicDatasetStatus = $derived<PublicDatasetStatus | null>(publicDatasetState.status);
  let savedEnabled = $derived(!!publicDatasetStatus?.enabled);
  let dirty = $derived(publicDatasetEnabled !== savedEnabled);
  let stats = $derived(publicDatasetStatus?.last_stats ?? null);
  const saveEnabledRequest = createMutation(() => setPublicDatasetEnabledMutation());
  const syncRequest = createMutation(() => syncPublicDatasetNowMutation());
  // A sync always runs for a while, so show it from the click instead of after a settle delay.
  let publicDatasetBusy = $derived(syncRequest.isPending || publicDatasetSyncState.running);

  $effect(() => {
    if (!draftInitialised && publicDatasetStatus) {
      publicDatasetEnabled = publicDatasetStatus.enabled;
      draftInitialised = true;
    }
  });

  onMount(() => {
    if (!publicDatasetState.loaded) void publicDatasetState.refresh();
  });

  function formatDateTime(value: string | null | undefined) {
    return value ? formatDateInTimezone(value, publicDatasetStatus?.timezone) : "Never";
  }

  async function save() {
    if (saveEnabledRequest.isPending || !publicDatasetStatus || publicDatasetState.error) return;
    feedback.clear();
    try {
      const status = await saveEnabledRequest.mutateAsync({
        body: { enabled: publicDatasetEnabled },
      });
      queryClient.setQueryData(getPublicDatasetStatusOptions().queryKey, status);
      publicDatasetEnabled = status.enabled;
      feedback.success(status.enabled ? "OvertureDB enabled." : "OvertureDB disabled.");
    } catch (err) {
      publicDatasetEnabled = !!publicDatasetStatus?.enabled;
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

<PopupShell title="OvertureDB" width="min(680px, 94vw)" onclose={() => uiState.closePopup()}>
  <DataStatus
    label="OvertureDB status"
    error={publicDatasetState.error}
    loading={publicDatasetState.loading}
    hasData={!!publicDatasetStatus}
    onretry={() => publicDatasetState.refresh()}
  />
  {#if publicDatasetStatus}
    <div class="option-card">
      <span class="form-label">Dataset</span>
      <div class="options-col">
        <label class="form-row justify-between">
          <span>Enable OvertureDB</span>
          <input
            type="checkbox"
            bind:checked={publicDatasetEnabled}
            disabled={saveEnabledRequest.isPending ||
              publicDatasetBusy ||
              !!publicDatasetState.error}
          />
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
          disabled={!savedEnabled || publicDatasetBusy || dirty || !!publicDatasetState.error}
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
          {#each [["Movies", stats.movies], ["Shows", stats.shows], ["Seasons", stats.seasons], ["Errors", stats.errors]] as const as [label, count] (label)}
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
        <span class="dataset-empty">No synced file statistics yet.</span>
      {/if}
    </div>
  {/if}
  <div class="option-card">
    <span class="form-label">Bulk contribution</span>
    <div class="options-col">
      <span class="dataset-empty">
        Export all saved artwork, season posters, and theme selections as a ZIP. Check the export
        report, then attach the ZIP to a Bulk contribution issue on GitHub. Only selections missing
        from OvertureDB are added.
      </span>
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
  {#snippet footer()}
    <button class="btn btn-ghost" onclick={() => uiState.closePopup()}> Cancel </button>
    <PendingButton
      class="btn btn-primary"
      onclick={save}
      pending={saveEnabledRequest.isPending}
      pendingLabel="Saving..."
      disabled={!dirty || !publicDatasetStatus || !!publicDatasetState.error}
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
  .dataset-empty {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }
  .stats-grid {
    display: grid;
    grid-template-columns: repeat(4, minmax(0, 1fr));
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
