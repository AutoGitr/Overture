<script lang="ts">
  import { countOf } from "../utils/plural";
  import ExternalLink from "@lucide/svelte/icons/external-link";
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import { exportCatalogSelections } from "../../generated/rest/sdk.gen";
  import type { CatalogStatus, CatalogSyncOutcome } from "../../generated/rest/types.gen";
  import {
    getCatalogStatusOptions,
    getCatalogCountsOptions,
    syncCatalogNowMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import { confirmAction, createNotifier } from "../stores/notificationState.svelte";
  import { discardDrafts, draftedEntries } from "../utils/catalogDrafts";
  import { catalogSyncState } from "../stores/jobStates.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { errorMessage } from "../utils/errors";
  import { formatBytes, formatDateInTimezone } from "../utils/popupFormat";
  import CardColumn from "../components/CardColumn.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import PendingButton from "../components/PendingButton.svelte";

  const SYNC_OUTCOMES: Record<CatalogSyncOutcome, string> = {
    never_synced: "Never synced",
    success: "Succeeded",
    failed: "Failed",
  };

  const catalogQuery = createQuery(() => getCatalogStatusOptions());

  const countsQuery = createQuery(() => ({
    ...getCatalogCountsOptions(),
    enabled: catalogQuery.data?.enabled === true,
  }));
  let draftCount = $derived(countsQuery.data?.drafts ?? null);

  const feedback = createNotifier();
  const exportRequest = createMutation(() => ({
    mutationFn: async () => (await exportCatalogSelections({ throwOnError: true })).data,
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
  let catalogStatus = $derived<CatalogStatus | null>(catalogQuery.data ?? null);
  let savedEnabled = $derived(!!catalogStatus?.enabled);
  let stats = $derived(catalogStatus?.last_stats ?? null);
  const syncRequest = createMutation(() => syncCatalogNowMutation());
  // A sync always runs for a while, so show it from the click instead of after a settle delay.
  let catalogBusy = $derived(syncRequest.isPending || catalogSyncState.running);

  function formatDateTime(value: string | null | undefined) {
    return value ? formatDateInTimezone(value, catalogStatus?.timezone) : "Never";
  }

  async function syncCatalogNow() {
    if (catalogBusy) return;
    feedback.clear();
    try {
      const result = await syncRequest.mutateAsync({});
      if (result.status === "disabled") {
        feedback.warning("Enable OvertureDB in Settings before syncing.");
        return;
      }
      catalogSyncState.markStartAccepted();
    } catch (err) {
      feedback.error(errorMessage(err, "OvertureDB sync failed"));
    }
  }
</script>

<PopupShell title="OvertureDB" onclose={() => uiState.closePopup()}>
  <CardColumn>
    <DataStatus
      label="OvertureDB status"
      error={catalogQuery.error}
      loading={catalogQuery.isFetching}
      hasData={!!catalogStatus}
      onretry={() => catalogQuery.refetch()}
    />
    {#if catalogStatus}

      <div class="option-card">
        <span class="form-label">Status</span>
        <div class="options-col">
          <div class="catalog-meta">
            <span>Repository</span>
            {#if catalogStatus?.repo_url}
              <a
                href={catalogStatus.repo_url}
                target="_blank"
                rel="noopener noreferrer"
                class="catalog-link"
                title={catalogStatus.repo_url}
              >
                <code>{catalogStatus.repo_url}</code>
                <ExternalLink size={12} />
              </a>
            {:else}
              <code>Not configured</code>
            {/if}
          </div>
          <div class="catalog-meta">
            <span>Catalog</span>
            <code>{catalogStatus?.catalog_url || "Not configured"}</code>
          </div>
          <div class="catalog-meta">
            <span>Last sync</span>
            <span>{formatDateTime(catalogStatus?.last_synced_at)}</span>
          </div>
          <div class="catalog-meta">
            <span>Status</span>
            <span>{SYNC_OUTCOMES[catalogStatus?.last_status ?? "never_synced"]}</span>
          </div>
          <div class="catalog-meta">
            <span>Next sync</span>
            <span>
              {savedEnabled ? formatDateTime(catalogStatus?.next_run) : "Disabled"}
            </span>
          </div>
          <button
            class="btn btn-secondary btn-sm self-start"
            onclick={syncCatalogNow}
            disabled={!savedEnabled || catalogBusy || !!catalogQuery.error}
          >
            {catalogBusy ? "Syncing..." : "Sync OvertureDB Now"}
          </button>
          {#if catalogSyncState.error}
            <span class="catalog-error" role="alert">{catalogSyncState.error}</span>
          {/if}
        </div>
      </div>
      <div class="option-card">
        <span class="form-label">Synced file</span>
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
            <div class="catalog-meta">
              <span>Compressed</span>
              <span>{formatBytes(stats.catalog_bytes)}</span>
            </div>
            <div class="catalog-meta">
              <span>Unpacked</span>
              <span>{formatBytes(stats.catalog_uncompressed_bytes)}</span>
            </div>
            <div class="catalog-meta">
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
            >{countOf(draftCount, "local draft")}</span
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
          {#if catalogStatus?.repo_url}
            <a
              class="btn btn-secondary btn-sm"
              href={`${catalogStatus.repo_url.replace(/\/$/, "")}/issues/new?template=bulk.yml`}
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
    <button class="btn btn-secondary" onclick={() => uiState.closePopup()}>Close</button>
  {/snippet}
</PopupShell>

<style>
  .catalog-meta {
    display: grid;
    grid-template-columns: 110px minmax(0, 1fr);
    gap: var(--space-3);
    align-items: center;
    font-size: var(--text-xs);
    color: var(--text-secondary);
  }
  .catalog-meta code {
    min-width: 0;
    word-break: break-all;
    white-space: normal;
    color: var(--text-tertiary);
  }
  .catalog-link {
    display: inline-flex;
    align-items: center;
    gap: var(--space-1);
    min-width: 0;
    max-width: 100%;
    color: var(--accent);
    text-decoration: none;
  }
  .catalog-link:hover {
    color: var(--accent-hover);
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  .catalog-link:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 2px;
    border-radius: var(--radius-sm);
  }
  .catalog-link code {
    color: inherit;
    cursor: pointer;
  }
  .catalog-link :global(svg) {
    flex-shrink: 0;
  }
  .catalog-error {
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
    .catalog-meta {
      grid-template-columns: 80px minmax(0, 1fr);
    }

    .stats-grid {
      grid-template-columns: repeat(2, minmax(0, 1fr));
    }
  }
</style>
