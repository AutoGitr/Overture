<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import Copy from "@lucide/svelte/icons/copy";
  import { createQuery } from "@tanstack/svelte-query";
  import { onMount } from "svelte";
  import { getPublicDatasetRecordOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import DataStatus from "../components/DataStatus.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import { invalidateSeasons, refreshItem } from "../rest/cache";
  import { createSeasonsQuery } from "../rest/queries";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { collectionState } from "../stores/collectionState.svelte";
  import { selectedState } from "../stores/selectedState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { dbRecordFields, type DisplayField } from "../utils/dbRecordFields";
  import { errorMessage } from "../utils/errors";

  let item = $derived(selectedState.item);
  let coll = $derived(collectionState.selectedCollection);
  const seasonsQuery = createSeasonsQuery(() => item);
  let seasons = $derived(seasonsQuery.data ?? []);
  let recordTitle = $derived(
    `Database Record - ${(uiState.sidebarMode === "collections" ? coll?.title : item?.title) || ""}`,
  );
  const feedback = createNotifier();
  let copiedField = $state<string | null>(null);
  let refreshError = $state("");
  let refreshing = $state(false);
  const publicDatasetRecordQuery = createQuery(() => ({
    ...getPublicDatasetRecordOptions({ path: { item_id: item?.id ?? 0 } }),
    enabled: uiState.sidebarMode !== "collections" && !!item?.id,
  }));
  let publicDatasetRecord = $derived(
    publicDatasetRecordQuery.data?.found ? publicDatasetRecordQuery.data : null,
  );

  // Re-read the record on open so it includes server-side changes.
  async function refreshRecord() {
    if (uiState.sidebarMode === "collections" || !item) return;
    const itemId = item.id;
    refreshing = true;
    refreshError = "";
    try {
      await Promise.all([refreshItem(itemId), invalidateSeasons(itemId)]);
    } catch (error) {
      refreshError = errorMessage(error, "Could not refresh the database record.");
    } finally {
      refreshing = false;
    }
  }

  /** Clears the "copied" mark; a later copy restarts it. */
  let copiedTimer: ReturnType<typeof setTimeout> | undefined;

  onMount(() => {
    void refreshRecord();
    return () => clearTimeout(copiedTimer);
  });

  function getFields(obj: object | null | undefined): DisplayField[] {
    return dbRecordFields(obj);
  }

  async function copyValue(field: DisplayField) {
    feedback.clear();
    try {
      await navigator.clipboard.writeText(field.value);
      copiedField = field.key;
      clearTimeout(copiedTimer);
      copiedTimer = setTimeout(() => (copiedField = null), 1500);
    } catch {
      feedback.warning("Clipboard access is unavailable. Select and copy the value manually.");
    }
  }

  let mediaFields = $derived(item ? getFields(item) : []);
  let collFields = $derived(coll ? getFields(coll) : []);
  let publicDatasetSeasons = $derived(publicDatasetRecord?.seasons ?? []);
</script>

<PopupShell title={recordTitle} width="min(700px,92vw)" onclose={() => uiState.closePopup()}>
  {#if uiState.sidebarMode === "collections" && coll}
    <h3 class="section-title">Collection</h3>
    <div class="db-table">
      {#each collFields as field (field.key)}
        <button class="db-row" onclick={() => copyValue(field)}>
          <span class="db-key">{field.key}</span>
          <span class="db-value truncate">{field.value}</span>
          {#if copiedField === field.key}
            <Check size={12} class="text-success" />
          {:else}
            <Copy size={12} class="text-tertiary" />
          {/if}
        </button>
      {/each}
    </div>
  {:else if item}
    <DataStatus
      label="database record"
      error={refreshError}
      loading={refreshing}
      hasData={true}
      onretry={refreshRecord}
    />
    <h3 class="section-title">Media Item</h3>
    <div class="db-table">
      {#each mediaFields as field (field.key)}
        <button class="db-row" onclick={() => copyValue(field)}>
          <span class="db-key">{field.key}</span>
          <span class="db-value truncate">{field.value}</span>
          {#if copiedField === field.key}
            <Check size={12} class="text-success" />
          {:else}
            <Copy size={12} class="text-tertiary" />
          {/if}
        </button>
      {/each}
    </div>

    {#if item.media_type === "show"}
      <DataStatus
        label="seasons"
        error={seasonsQuery.error}
        loading={seasonsQuery.isFetching}
        hasData={seasonsQuery.data !== undefined}
        onretry={() => seasonsQuery.refetch()}
      />
    {/if}
    {#if seasons.length > 0}
      <h3 class="section-title">Seasons</h3>
      {#each seasons as season (season.id)}
        <details class="db-details">
          <summary>{season.title || `Season ${season.season_num}`}</summary>
          <div class="db-table">
            {#each getFields(season) as field (field.key)}
              <button class="db-row" onclick={() => copyValue(field)}>
                <span class="db-key">{field.key}</span>
                <span class="db-value truncate">{field.value}</span>
                {#if copiedField === field.key}
                  <Check size={12} class="text-success" />
                {:else}
                  <Copy size={12} class="text-tertiary" />
                {/if}
              </button>
            {/each}
          </div>
        </details>
      {/each}
    {/if}

    <DataStatus
      label="OvertureDB record"
      error={publicDatasetRecordQuery.error}
      loading={publicDatasetRecordQuery.isFetching}
      hasData={publicDatasetRecordQuery.data !== undefined}
      onretry={() => publicDatasetRecordQuery.refetch()}
    />
    {#if publicDatasetRecord?.item}
      <h3 class="section-title">OvertureDB Item</h3>
      <div class="db-table">
        {#each getFields(publicDatasetRecord.item) as field (field.key)}
          <button class="db-row" onclick={() => copyValue(field)}>
            <span class="db-key">{field.key}</span>
            <span class="db-value truncate">{field.value}</span>
            {#if copiedField === field.key}
              <Check size={12} class="text-success" />
            {:else}
              <Copy size={12} class="text-tertiary" />
            {/if}
          </button>
        {/each}
      </div>

      {#if publicDatasetSeasons.length > 0}
        <h3 class="section-title">OvertureDB Seasons</h3>
        {#each publicDatasetSeasons as season (season.season_num)}
          <details class="db-details">
            <summary>Season {season.season_num}</summary>
            <div class="db-table">
              {#each getFields(season) as field (field.key)}
                <button class="db-row" onclick={() => copyValue(field)}>
                  <span class="db-key">{field.key}</span>
                  <span class="db-value truncate">{field.value}</span>
                  {#if copiedField === field.key}
                    <Check size={12} class="text-success" />
                  {:else}
                    <Copy size={12} class="text-tertiary" />
                  {/if}
                </button>
              {/each}
            </div>
          </details>
        {/each}
      {/if}
    {/if}
  {/if}
</PopupShell>

<style>
  .section-title {
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-secondary);
    margin: var(--space-4) 0 var(--space-2);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .section-title:first-child {
    margin-top: 0;
  }

  .db-table {
    border: var(--border-subtle);
    border-radius: var(--radius-md);
    overflow: hidden;
  }

  .db-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    padding: var(--space-2) var(--space-3);
    text-align: left;
    font-size: var(--text-xs);
    border-bottom: var(--border-subtle);
  }

  .db-row:last-child {
    border-bottom: none;
  }

  .db-row:hover {
    background: var(--bg-hover);
  }

  .db-key {
    width: min(240px, 42%);
    flex-shrink: 0;
    font-family: var(--font-mono);
    color: var(--accent);
    overflow-wrap: anywhere;
  }

  .db-value {
    user-select: text;
    flex: 1;
    min-width: 0;
    font-family: var(--font-mono);
    color: var(--text-secondary);
  }

  .db-details {
    margin-bottom: var(--space-2);
  }

  .db-details summary {
    cursor: pointer;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    padding: var(--space-2) 0;
  }

  .db-details summary:hover {
    color: var(--text-primary);
  }

  :global(.text-tertiary) {
    color: var(--text-tertiary);
  }
</style>
