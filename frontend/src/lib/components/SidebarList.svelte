<script lang="ts" generics="T">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import type { Snippet } from "svelte";
  import { preloadImages } from "../utils/imagePreload";
  import { preloadRowIndexes, SIDEBAR_OVERSCAN_ROWS } from "../utils/sidebarDomain";
  import VirtualList from "./VirtualList.svelte";

  let {
    rows,
    loading = false,
    message = "",
    scrollOffset,
    getKey,
    posterUrl,
    entry,
  }: {
    rows: T[];
    /** Loading with nothing to show yet. */
    loading?: boolean;
    /** Shown instead of the rows: an error, or why there are none. */
    message?: string;
    scrollOffset: number;
    getKey: (row: T) => string | number;
    posterUrl: (row: T) => string | null;
    entry: Snippet<[T, number, string]>;
  } = $props();

  /** How long scrolling must rest before posters around the viewport are fetched. */
  const PRELOAD_IDLE_MS = 150;
  let visibleRange = $state<[number, number]>([0, 0]);

  $effect(() => {
    const [first, end] = visibleRange;
    const posters = preloadRowIndexes(first, end, rows.length).map((index) => {
      const shown = rows[index];
      return shown === undefined ? null : posterUrl(shown);
    });
    const timer = setTimeout(() => preloadImages(posters, "sidebar"), PRELOAD_IDLE_MS);
    return () => clearTimeout(timer);
  });
</script>

{#if loading}
  <div class="notice">
    <LoaderCircle size={24} class="animate-spin" />
  </div>
{:else if message}
  <div class="notice">{message}</div>
{:else}
  <VirtualList
    width="100%"
    itemCount={rows.length}
    itemSize={88}
    {scrollOffset}
    overscanCount={SIDEBAR_OVERSCAN_ROWS}
    onVisibleRangeChange={(first, end) => (visibleRange = [first, end])}
    getKey={(index) => {
      const shown = rows[index];
      return shown === undefined ? index : getKey(shown);
    }}
  >
    {#snippet row(index: number, style: string)}
      {@const shown = rows[index]}
      {#if shown !== undefined}
        {@render entry(shown, index, style)}
      {/if}
    {/snippet}
  </VirtualList>
{/if}

<style>
  .notice {
    display: flex;
    align-items: center;
    justify-content: center;
    padding: var(--space-10);
    color: var(--text-tertiary);
    font-size: var(--text-sm);
  }
</style>
