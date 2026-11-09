<script lang="ts">
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import {
    getCollectionMissingOptions,
    requestCollectionMissingMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type {
    CollectionDetail,
    CollectionRequestTitle,
    MediaType,
  } from "../../generated/rest/types.gen";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { getSectionView, sectionState } from "../stores/sectionState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { errorMessage } from "../utils/errors";
  import DataStatus from "./DataStatus.svelte";
  import DetailSection from "./DetailSection.svelte";
  import PendingButton from "./PendingButton.svelte";

  let { collection }: { collection: CollectionDetail } = $props();

  const TITLE = "Missing";
  const view = getSectionView();
  let expanded = $derived(sectionState.isOpen(view, TITLE, false));
  const target = $derived({ path: { collection_id: collection.id } });
  const missing = createQuery(() => ({
    ...getCollectionMissingOptions(target),
    // Lists are read from TMDB and MDBList, so only once someone looks.
    enabled: expanded,
  }));
  const request = createMutation(() => requestCollectionMissingMutation());
  const feedback = createNotifier();
  function arrOf(mediaType: MediaType) {
    return mediaType === "movie" ? "Radarr" : "Sonarr";
  }
  let arrs = $derived(collection.media_types.map(arrOf).join(" and "));

  async function requestTitles(titles: CollectionRequestTitle[] | null) {
    try {
      const result = await request.mutateAsync({ ...target, body: { titles } });
      const summary = `${result.requested} requested, ${result.present} already held`;
      if (result.errors.length) feedback.error(`${summary}. ${result.errors.join("; ")}`);
      else feedback.success(`${summary}.`);
      await missing.refetch();
    } catch (error) {
      feedback.error(errorMessage(error, `Could not request from ${arrs}`));
    }
  }
</script>

<DetailSection
  collapsible
  title={TITLE}
  description="Titles the collection's lists hold that the library lacks."
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
      <ul class="missing">
        {#each data.titles as title (`${title.media_type}:${title.tmdb_id}`)}
          <li>
            <span>{title.title}{title.year ? ` (${title.year})` : ""}</span>
            {#if title.requested}
              <span class="badge badge-muted">In {arrOf(title.media_type)}</span>
            {:else if title.requestable}
              <button
                type="button"
                class="btn btn-ghost btn-sm"
                disabled={request.isPending}
                aria-label={`Request ${title.title} from ${arrOf(title.media_type)}`}
                onclick={() =>
                  void requestTitles([{ tmdb_id: title.tmdb_id, media_type: title.media_type }])}
                >Request</button
              >
            {/if}
          </li>
        {/each}
      </ul>
      {#if data.truncated}<p class="hint">Only the first 100 are listed.</p>{/if}
      {#if data.requestable}
        <div class="actions-row">
          <PendingButton
            type="button"
            class="btn btn-secondary"
            pending={request.isPending}
            pendingLabel="Requesting..."
            onclick={() => void requestTitles(null)}>Request all from {arrs}</PendingButton
          >
        </div>
      {/if}
    {:else if settingsState.current.tmdb_configured}
      <p class="text-muted">The library holds every title the lists do.</p>
    {:else}
      <p class="text-muted">Set TMDB_API_KEY to list the titles the library lacks.</p>
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
