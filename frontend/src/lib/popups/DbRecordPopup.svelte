<script lang="ts">
  import Check from "@lucide/svelte/icons/check";
  import Copy from "@lucide/svelte/icons/copy";
  import { createQuery } from "@tanstack/svelte-query";
  import { onMount } from "svelte";
  import {
    getCatalogEntryOptions,
    getCatalogEntryRecordOptions,
    getCollectionRecordOptions,
    getItemRecordOptions,
    getPublicDatasetCollectionRecordOptions,
    getPublicDatasetRecordOptions,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import CardColumn from "../components/CardColumn.svelte";
  import DataStatus from "../components/DataStatus.svelte";
  import PopupShell from "../components/PopupShell.svelte";
  import { routedCatalogEntry, routedCollectionId, routedItemId } from "../router/routes";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { uiState } from "../stores/uiState.svelte";
  import { dbRecordFields, type DisplayField } from "../utils/dbRecordFields";

  let catalogEntry = $derived(routedCatalogEntry());
  let collectionId = $derived(catalogEntry ? null : routedCollectionId());
  let itemId = $derived(catalogEntry || collectionId !== null ? null : routedItemId());
  // Opening the popup reads the record again, so it shows what is stored as it opens.
  const itemRecord = createQuery(() => ({
    ...getItemRecordOptions({ path: { item_id: itemId ?? 0 } }),
    enabled: itemId !== null,
    refetchOnMount: "always" as const,
  }));
  const collectionRecord = createQuery(() => ({
    ...getCollectionRecordOptions({ path: { collection_id: collectionId ?? 0 } }),
    enabled: collectionId !== null,
    refetchOnMount: "always" as const,
  }));
  let recordQuery = $derived(collectionId !== null ? collectionRecord : itemRecord);
  let record = $derived(catalogEntry ? null : (recordQuery.data ?? null));
  let subjectTitle = $derived(catalogEntry?.entry_key ?? record?.stored[0]?.values.title);
  let recordTitle = $derived(
    subjectTitle ? `Database Record - ${String(subjectTitle)}` : "Database Record",
  );
  const feedback = createNotifier();
  let copiedField = $state<string | null>(null);
  // One OvertureDB record query per subject; only the open subject's runs.
  const itemRecordQuery = createQuery(() => ({
    ...getPublicDatasetRecordOptions({ path: { item_id: itemId ?? 0 } }),
    enabled: itemId !== null,
  }));
  const collectionRecordQuery = createQuery(() => ({
    ...getPublicDatasetCollectionRecordOptions({ path: { collection_id: collectionId ?? 0 } }),
    enabled: collectionId !== null,
  }));
  const catalogRecordQuery = createQuery(() => ({
    ...getCatalogEntryRecordOptions({
      path: catalogEntry ?? { media_type: "movie", entry_key: "" },
    }),
    enabled: catalogEntry !== null,
  }));
  // The open entry's detail, shared with its page, holds any local draft.
  const catalogDetailQuery = createQuery(() => ({
    ...getCatalogEntryOptions({
      path: catalogEntry ?? { media_type: "movie", entry_key: "" },
    }),
    enabled: catalogEntry !== null,
  }));
  let draft = $derived(catalogEntry ? (catalogDetailQuery.data?.draft ?? null) : null);
  let publicDatasetRecordQuery = $derived(
    catalogEntry
      ? catalogRecordQuery
      : collectionId !== null
        ? collectionRecordQuery
        : itemRecordQuery,
  );
  let publicDatasetRecord = $derived(
    publicDatasetRecordQuery.data?.found ? publicDatasetRecordQuery.data : null,
  );

  /** Clears the "copied" mark; a later copy restarts it. */
  let copiedTimer: ReturnType<typeof setTimeout> | undefined;

  onMount(() => () => clearTimeout(copiedTimer));

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

  let publicDatasetSeasons = $derived(publicDatasetRecord?.seasons ?? []);
</script>

{#snippet fieldTable(fields: DisplayField[], scope = "")}
  <div class="db-table">
    {#each fields as field (field.key)}
      {@const key = `${scope}${field.key}`}
      <button class="db-row" onclick={() => copyValue({ ...field, key })}>
        <span class="db-key">{field.key}</span>
        <span class="db-value truncate">{field.value}</span>
        {#if copiedField === key}
          <Check size={12} class="text-success" />
        {:else}
          <Copy size={12} class="text-tertiary" />
        {/if}
      </button>
    {/each}
  </div>
{/snippet}

<PopupShell title={recordTitle} onclose={() => uiState.closePopup()}>
  <CardColumn>
    {#if !catalogEntry}
      <DataStatus
        label="database record"
        error={recordQuery.error}
        loading={recordQuery.isFetching}
        hasData={record !== null}
        onretry={() => recordQuery.refetch()}
      />
    {/if}
    {#if record}
      {@const [own, ...related] = record.stored}
      {#if own}
        <section class="option-card">
          <h3 class="form-label">Stored in {own.table}</h3>
          {@render fieldTable(dbRecordFields(own.values), "own:")}
          {#each related as row, index (index)}
            <details class="db-details">
              <summary
                >{row.table}{row.values.id === undefined ? "" : ` ${String(row.values.id)}`}</summary
              >
              {@render fieldTable(dbRecordFields(row.values), `${index}:`)}
            </details>
          {/each}
        </section>
      {/if}
      <section class="option-card">
        <h3 class="form-label">Derived by the API</h3>
        <p class="hint">What Overture shows that no column stores, worked out from the rows above.</p>
        {@render fieldTable(dbRecordFields(record.derived), "derived:")}
      </section>
    {/if}
    {#if catalogEntry || record}
      <DataStatus
        label="OvertureDB record"
        error={publicDatasetRecordQuery.error}
        loading={publicDatasetRecordQuery.isFetching}
        hasData={publicDatasetRecordQuery.data !== undefined}
        onretry={() => publicDatasetRecordQuery.refetch()}
      />
      {#if publicDatasetRecordQuery.data && !publicDatasetRecord}
        <p class="hint">OvertureDB has no entry for this.</p>
      {/if}
      {#if draft}
        <section class="option-card">
          <h3 class="form-label">Local draft</h3>
          {@render fieldTable(dbRecordFields(draft))}
        </section>
      {/if}
      {#if publicDatasetRecord?.collection}
        <section class="option-card">
          <h3 class="form-label">OvertureDB Collection</h3>
          {@render fieldTable(dbRecordFields(publicDatasetRecord.collection))}
        </section>
      {/if}
      {#if publicDatasetRecord?.item}
        <section class="option-card">
          <h3 class="form-label">OvertureDB Item</h3>
          {@render fieldTable(dbRecordFields(publicDatasetRecord.item))}
        </section>

        {#if publicDatasetSeasons.length > 0}
          <section class="option-card">
            <h3 class="form-label">OvertureDB Seasons</h3>
            {#each publicDatasetSeasons as season (season.season_num)}
              <details class="db-details">
                <summary>Season {season.season_num}</summary>
                {@render fieldTable(dbRecordFields(season), `od-${season.season_num}:`)}
              </details>
            {/each}
          </section>
        {/if}
      {/if}
    {/if}
  </CardColumn>

  {#snippet footer()}
    <button type="button" class="btn btn-secondary" onclick={() => uiState.closePopup()}
      >Close</button
    >
  {/snippet}
</PopupShell>

<style>
  .db-table {
    display: flex;
    flex-direction: column;
  }

  .db-row {
    display: flex;
    align-items: center;
    gap: var(--space-3);
    width: 100%;
    padding: var(--space-1) 0;
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
    -webkit-user-select: text;
    user-select: text;
    flex: 1;
    min-width: 0;
    font-family: var(--font-mono);
    color: var(--text-secondary);
  }

  .db-details summary {
    cursor: pointer;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    padding: var(--space-1) 0;
  }

  .db-details summary:hover {
    color: var(--text-primary);
  }
</style>
