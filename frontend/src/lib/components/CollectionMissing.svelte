<script lang="ts">
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionMissingOptions,
    requestCollectionMissingMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { CollectionDetail } from "../../generated/rest/types.gen";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { errorMessage } from "../utils/errors";
  import DataStatus from "./DataStatus.svelte";
  import DetailSection from "./DetailSection.svelte";
  import PendingButton from "./PendingButton.svelte";

  let { collection }: { collection: CollectionDetail } = $props();

  let expanded = $state(false);
  const target = $derived({
    path: { collection_id: collection.id },
    query: { media_type: collection.media_type },
  });
  const missing = createQuery(() => ({
    ...getCollectionMissingOptions(target),
    // Lists are read from TMDB and MDBList, so only once someone looks.
    enabled: expanded,
  }));
  const request = createMutation(() => requestCollectionMissingMutation());
  const feedback = createNotifier();
  let arr = $derived(collection.media_type === "movie" ? "Radarr" : "Sonarr");

  async function requestTitles(tmdbIds: number[] | null) {
    try {
      const result = await request.mutateAsync({ ...target, body: { tmdb_ids: tmdbIds } });
      const summary = `${result.requested} requested, ${result.present} already in ${arr}`;
      if (result.errors.length) feedback.error(`${summary}. ${result.errors.join("; ")}`);
      else feedback.success(`${summary}.`);
      await missing.refetch();
    } catch (error) {
      feedback.error(errorMessage(error, `Could not request from ${arr}`));
    }
  }
</script>

<DetailSection
  collapsible
  title="Missing"
  description="Titles the collection's lists hold that the library lacks."
  ontoggle={(open) => (expanded = open)}
>
  <DataStatus
    label="missing titles"
    error={missing.error}
    loading={missing.isFetching}
    hasData={missing.data !== undefined}
    onretry={() => missing.refetch()}
  />
  {#if missing.data}
    {@const data = missing.data}
    {#if data.titles.length}
      {#if data.requestable}
        <PendingButton
          type="button"
          class="btn btn-secondary"
          pending={request.isPending}
          pendingLabel="Requesting..."
          onclick={() => void requestTitles(null)}>Request all from {arr}</PendingButton
        >
      {/if}
      <ul class="missing">
        {#each data.titles as title (title.tmdb_id)}
          <li>
            <span>{title.title}{title.year ? ` (${title.year})` : ""}</span>
            {#if title.requested}
              <span class="badge">In {arr}</span>
            {:else if data.requestable}
              <button
                type="button"
                class="btn btn-ghost btn-sm"
                disabled={request.isPending}
                aria-label={`Request ${title.title} from ${arr}`}
                onclick={() => void requestTitles([title.tmdb_id])}>Request</button
              >
            {/if}
          </li>
        {/each}
      </ul>
      {#if data.truncated}<p class="hint">Only the first 100 are listed.</p>{/if}
    {:else}
      <p class="text-muted">The library holds every title the lists do.</p>
    {/if}
  {/if}
</DetailSection>

<style>
  .missing {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(min(100%, 260px), 1fr));
    gap: var(--space-1) var(--space-4);
    margin: 0;
    padding: 0;
    list-style: none;
  }

  .missing li {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    font-size: var(--text-sm);
  }
</style>
