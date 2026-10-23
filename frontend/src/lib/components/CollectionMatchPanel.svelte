<script lang="ts">
  import { createMutation, createQuery } from "@tanstack/svelte-query";
  import {
    resetCollectionMatchMutation,
    searchTmdbOptions,
    setCollectionMatchMutation,
  } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { CollectionDetail } from "../../generated/rest/types.gen";
  import { storeCollectionDetail } from "../rest/cache";
  import { createNotifier } from "../stores/notificationState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { errorMessage } from "../utils/errors";
  import DataStatus from "./DataStatus.svelte";

  let { collection }: { collection: CollectionDetail } = $props();
  let text = $state("");
  let submitted = $state("");
  const search = createQuery(() => ({
    ...searchTmdbOptions({ query: { media_type: "movie", query: submitted } }),
    enabled: !!submitted && settingsState.current.tmdb_configured,
  }));
  const setMatch = createMutation(() => setCollectionMatchMutation());
  const resetMatch = createMutation(() => resetCollectionMatchMutation());
  const feedback = createNotifier();
  let busy = $derived(setMatch.isPending || resetMatch.isPending);
  let matches = $derived(
    search.data?.results.filter((result) => result.kind === "collection") ?? [],
  );

  async function match(tmdbId: number | null) {
    if (busy) return;
    try {
      const result = await setMatch.mutateAsync({
        path: { collection_id: collection.id },
        body: { media_type: collection.media_type, tmdb_collection_id: tmdbId },
      });
      storeCollectionDetail(result);
      submitted = "";
      text = "";
    } catch (error) {
      feedback.error(errorMessage(error, "Match could not be saved"));
    }
  }
  async function reset() {
    if (busy) return;
    try {
      const result = await resetMatch.mutateAsync({
        path: { collection_id: collection.id },
        query: { media_type: collection.media_type },
      });
      storeCollectionDetail(result);
    } catch (error) {
      feedback.error(errorMessage(error, "Match could not be reset"));
    }
  }
</script>

<section class="matching" aria-label="TMDB collection match">
  <p class="text-muted">
    Match: {collection.tmdb_match === "manual"
      ? "Manual"
      : collection.tmdb_match === "unmatched"
        ? "Manually unmatched"
        : collection.tmdb_collection_id
          ? "Automatic"
          : "No automatic match"}
  </p>
  <div class="actions">
    <button
      class="btn btn-ghost btn-sm"
      onclick={() => match(null)}
      disabled={busy || collection.tmdb_match === "unmatched"}>Unmatch</button
    >
    <button
      class="btn btn-ghost btn-sm"
      onclick={reset}
      disabled={busy || collection.tmdb_match === "auto"}>Reset to auto</button
    >
  </div>
  {#if settingsState.current.tmdb_configured}
    <form
      class="actions"
      onsubmit={(event) => {
        event.preventDefault();
        const query = text.trim();
        if (query === submitted) void search.refetch();
        else submitted = query;
      }}
    >
      <input
        aria-label="Search TMDB collections"
        placeholder="TMDB collection title or ID"
        bind:value={text}
      />
      <button class="btn btn-secondary btn-sm" disabled={!text.trim() || busy || search.isFetching}
        >Search TMDB</button
      >
    </form>
    <DataStatus
      label="TMDB collection search"
      error={search.error}
      loading={search.isFetching}
      hasData={search.data !== undefined}
      onretry={() => search.refetch()}
    />
    {#each matches as candidate (candidate.tmdb_id)}
      <button
        class="btn btn-secondary self-start"
        onclick={() => match(candidate.tmdb_id)}
        disabled={busy}>Match {candidate.title} (TMDB {candidate.tmdb_id})</button
      >
    {/each}
    {#if submitted && search.isSuccess && matches.length === 0}<p class="text-muted">
        No TMDB collections found.
      </p>{/if}
  {:else}
    <p class="text-muted">Configure TMDB to search collections, or enter a collection ID.</p>
    <form
      class="actions"
      onsubmit={(event) => {
        event.preventDefault();
        void match(Number(text));
      }}
    >
      <input
        aria-label="TMDB collection ID"
        type="number"
        min="1"
        step="1"
        required
        bind:value={
          () => text,
          (value) => {
            text = String(value ?? "");
          }
        }
      />
      <button class="btn btn-secondary btn-sm" disabled={busy || !text}>Match collection</button>
    </form>
  {/if}
</section>

<style>
  .matching {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
    margin-bottom: var(--space-4);
  }
  .actions {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-2);
  }
  .actions input {
    flex: 1;
    min-width: 0;
  }
</style>
