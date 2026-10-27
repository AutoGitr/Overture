<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { untrack } from "svelte";
  import { searchYoutubeOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { ThemeSearchResult } from "../../generated/rest/types.gen";
  import { extractYouTubeId, isYouTubeUrl, type ThemeSearchResultItem } from "../utils/themeSearch";
  import DataStatus from "./DataStatus.svelte";
  import PendingButton from "./PendingButton.svelte";
  import ThemeResultGrid from "./ThemeResultGrid.svelte";

  const RESULT_LIMIT = 10;

  /**
   * A YouTube theme search for one subject. It searches for *initialQuery*
   * straight away, so key it on the subject to start afresh for another one.
   * A pasted YouTube link selects that video instead of searching.
   */
  let {
    label,
    initialQuery,
    videoIds = [],
    present = (results) => results,
    currentYoutubeId = null,
    busyVideoId = null,
    busy = false,
    selectLabel,
    onselect,
  }: {
    label: string;
    initialQuery: string;
    /** Videos shown with their metadata whatever is searched for. */
    videoIds?: string[];
    /** Turn the fetched videos into the grid's results. */
    present?: (results: ThemeSearchResult[]) => ThemeSearchResultItem[];
    currentYoutubeId?: string | null;
    busyVideoId?: string | null;
    /** A selection is under way, so no other can start. */
    busy?: boolean;
    selectLabel?: (video: ThemeSearchResultItem) => string;
    /** Select a video; resolves whether it was selected. */
    onselect: (youtubeId: string) => Promise<boolean>;
  } = $props();

  let text = $state(untrack(() => initialQuery));
  let submitted = $state(untrack(() => initialQuery.trim()));
  let linkedId = $derived(isYouTubeUrl(text) ? extractYouTubeId(text) : null);

  const search = createQuery(() => ({
    ...searchYoutubeOptions({ query: { query: submitted, limit: RESULT_LIMIT } }),
    enabled: submitted !== "",
  }));
  // Fetched apart from the search, so a candidate arriving later never
  // repeats the search itself.
  const known = createQuery(() => ({
    ...searchYoutubeOptions({ query: { limit: RESULT_LIMIT, video_ids: videoIds } }),
    enabled: videoIds.length > 0,
  }));
  let results = $derived(
    present([...(known.data?.results ?? []), ...(search.data?.results ?? [])]),
  );

  async function submit() {
    const value = text.trim();
    if (!value || busy) return;
    if (linkedId) {
      if (await onselect(linkedId)) text = "";
    } else if (value === submitted) {
      void search.refetch();
    } else {
      submitted = value;
    }
  }
</script>

<DataStatus
  label="Theme search"
  error={search.error}
  loading={search.isFetching}
  hasData={search.data !== undefined}
  onretry={() => search.refetch()}
/>

<div class="theme-search-row">
  <input
    type="text"
    class="theme-search-input"
    placeholder="Search YouTube or paste URL..."
    aria-label={label}
    bind:value={text}
    onkeydown={(event) => {
      if (event.key === "Enter") void submit();
    }}
  />
  <PendingButton
    class="btn btn-primary btn-sm"
    pending={linkedId ? busy : search.isFetching}
    pendingLabel={linkedId ? "Selecting..." : "Searching..."}
    disabled={busy || !text.trim()}
    onclick={submit}
  >
    {linkedId ? "Select" : "Search"}
  </PendingButton>
</div>

{#if results.length > 0}
  <ThemeResultGrid
    {results}
    {currentYoutubeId}
    {busyVideoId}
    disabled={busy}
    {selectLabel}
    onSelect={(video) => {
      void onselect(video.id);
    }}
  />
{:else if search.isSuccess && !search.isFetching}
  <p class="text-muted" role="status">No themes found. Try a different search.</p>
{/if}

<style>
  .theme-search-row {
    display: flex;
    gap: var(--space-2);
  }

  .theme-search-input {
    flex: 1;
    min-width: 0;
    font-size: var(--text-sm);
  }
</style>
