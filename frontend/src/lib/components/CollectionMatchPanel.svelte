<script lang="ts">
  import type { CollectionDetail } from "../../generated/rest/types.gen";
  import { settingsState } from "../stores/settingsState.svelte";
  import { CollectionMatcher } from "../utils/collectionMatch.svelte";
  import DetailSection from "./DetailSection.svelte";
  import DataStatus from "./DataStatus.svelte";

  let { collection }: { collection: CollectionDetail } = $props();
  const matcher = new CollectionMatcher(() => collection);
</script>

<DetailSection
  title="TMDB collection match"
  description="Choose the franchise used for artwork and catalog suggestions."
>
  <div class="matching">
    <p class="text-muted">
      Match: {collection.tmdb_match === "manual"
        ? "Manual"
        : collection.tmdb_match === "unmatched"
          ? "Manually unmatched"
          : collection.tmdb_collection_id
            ? "Automatic"
            : "No automatic match"}
    </p>
    <p class="text-muted">
      Current match: <span class="badge"
        >{collection.tmdb_collection_id
          ? `TMDB ${collection.tmdb_collection_id}`
          : "Unmatched"}</span
      >
      {#if collection.tmdb_match_confidence != null}
        &middot; {Math.round(collection.tmdb_match_confidence * 100)}% of members vote for this
        franchise{/if}
    </p>
    <div class="actions">
      <button
        class="btn btn-ghost btn-sm"
        onclick={() => matcher.match(null)}
        disabled={matcher.busy || collection.tmdb_match === "unmatched"}>Unmatch</button
      >
      <button
        class="btn btn-ghost btn-sm"
        onclick={() => void matcher.reset()}
        disabled={matcher.busy || collection.tmdb_match === "auto"}>Reset to auto</button
      >
    </div>
    {#if settingsState.current.tmdb_configured}
      <form
        class="actions"
        onsubmit={(event) => {
          event.preventDefault();
          matcher.submitSearch();
        }}
      >
        <input
          aria-label="Search TMDB collections"
          placeholder="TMDB collection title or ID"
          bind:value={matcher.text}
        />
        <button
          class="btn btn-secondary btn-sm"
          disabled={!matcher.text.trim() || matcher.busy || matcher.search.isFetching}
          >Search TMDB</button
        >
      </form>
      <DataStatus
        label="TMDB collection search"
        error={matcher.search.error}
        loading={matcher.search.isFetching}
        hasData={matcher.search.data !== undefined}
        onretry={() => matcher.search.refetch()}
      />
      {#each matcher.matches as candidate (candidate.tmdb_id)}
        <button
          class="btn btn-secondary self-start"
          onclick={() => matcher.match(candidate.tmdb_id)}
          disabled={matcher.busy}>Match {candidate.title} (TMDB {candidate.tmdb_id})</button
        >
      {/each}
      {#if matcher.submitted && matcher.search.isSuccess && matcher.matches.length === 0}<p
          class="text-muted"
        >
          No TMDB collections found.
        </p>{/if}
    {:else}
      <p class="text-muted">Configure TMDB to search collections, or enter a collection ID.</p>
      <form
        class="actions"
        onsubmit={(event) => {
          event.preventDefault();
          void matcher.match(Number(matcher.text));
        }}
      >
        <input
          aria-label="TMDB collection ID"
          type="number"
          min="1"
          step="1"
          required
          bind:value={
            () => matcher.text,
            (value) => {
              matcher.text = String(value ?? "");
            }
          }
        />
        <button class="btn btn-secondary btn-sm" disabled={matcher.busy || !matcher.text}
          >Match collection</button
        >
      </form>
    {/if}
  </div>
</DetailSection>

<style>
  .matching {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
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
