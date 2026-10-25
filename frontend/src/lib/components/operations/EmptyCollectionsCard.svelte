<script lang="ts">
  import { createQuery, createMutation } from "@tanstack/svelte-query";
  import {
    listCollectionsOptions,
    bulkOperateCollectionsMutation,
  } from "../../../generated/rest/@tanstack/svelte-query.gen";
  import type { CollectionRead } from "../../../generated/rest/types.gen";
  import { settingsState } from "../../stores/settingsState.svelte";
  import { confirmAction, createNotifier } from "../../stores/notificationState.svelte";
  import { runBulkCollections } from "../../utils/bulkCollections";
  import { errorMessage } from "../../utils/errors";
  import DataStatus from "../DataStatus.svelte";

  let { isActive }: { isActive: boolean } = $props();
  const movies = createQuery(() => ({
    ...listCollectionsOptions({ query: { media_type: "movie" } }),
    enabled: isActive && settingsState.current.collections_supported,
  }));
  const shows = createQuery(() => ({
    ...listCollectionsOptions({ query: { media_type: "show" } }),
    enabled: isActive && settingsState.current.collections_supported,
  }));
  const request = createMutation(() => bulkOperateCollectionsMutation());
  const feedback = createNotifier();
  let belowMinimum = $state(false);
  let candidates = $derived(
    [...(movies.data ?? []), ...(shows.data ?? [])].filter(
      (row) => row.child_count === 0 || (belowMinimum && row.below_minimum),
    ),
  );
  let ready = $derived(movies.isSuccess && shows.isSuccess);

  async function remove() {
    if (!ready || request.isPending || !candidates.length) return;
    const rows: CollectionRead[] = candidates;
    if (
      !(await confirmAction({
        title: `Delete ${rows.length} collections?`,
        message:
          "Remove these empty or undersized collections from Overture and the active media server. Movies, shows and media files are kept.",
        confirmLabel: "Delete collections",
        destructive: true,
      }))
    )
      return;
    try {
      let removed = 0;
      for (const media_type of ["movie", "show"] as const) {
        const ids = rows.filter((row) => row.media_type === media_type).map((row) => row.id);
        const result = await runBulkCollections(
          { collection_ids: ids, media_type, operation: "delete" },
          (body) => request.mutateAsync({ body }),
        );
        removed += result.collection_ids.length;
        for (const [id, error] of Object.entries(result.errors)) feedback.error(`${id}: ${error}`);
      }
      feedback.success(`Deleted ${removed} collections.`);
    } catch (error) {
      feedback.error(errorMessage(error, "Collection cleanup failed"));
    }
  }
</script>

{#if settingsState.current.collections_supported}
  <section class="option-card options-col" aria-label="Empty collections">
    <h3>Empty collections</h3>
    <p class="hint">
      Review the latest library sync before deleting collections. Media files are kept.
    </p>
    <DataStatus
      label="movie collections"
      error={movies.error}
      loading={movies.isFetching}
      hasData={movies.data !== undefined}
      onretry={() => movies.refetch()}
    />
    <DataStatus
      label="show collections"
      error={shows.error}
      loading={shows.isFetching}
      hasData={shows.data !== undefined}
      onretry={() => shows.refetch()}
    />
    <label class="form-row"
      ><input type="checkbox" bind:checked={belowMinimum} disabled={request.isPending} />Include
      collections below their effective minimum</label
    >
    {#if ready}
      <ul>
        {#each candidates as row (row.id)}<li>{row.title} ({row.child_count} members)</li>{/each}
      </ul>
      <button
        class="btn btn-danger"
        disabled={!candidates.length || request.isPending}
        onclick={() => void remove()}>Delete {candidates.length} collections</button
      >
    {/if}
  </section>
{/if}
