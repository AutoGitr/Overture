<script lang="ts">
  import type { Snippet } from "svelte";
  import { onMount, tick, untrack } from "svelte";

  let {
    width = "100%",
    itemCount,
    itemSize,
    scrollOffset = 0,
    overscanCount = 4,
    followEnd = false,
    getKey,
    onVisibleRangeChange,
    row,
  }: {
    width?: string | number;
    itemCount: number;
    itemSize: number;
    scrollOffset?: number;
    overscanCount?: number;
    followEnd?: boolean;
    getKey?: (index: number) => string | number;
    /** The rows on screen, without overscan: `first` up to but not including `end`. */
    onVisibleRangeChange?: (first: number, end: number) => void;
    row: Snippet<[number, string]>;
  } = $props();

  let viewport = $state<HTMLDivElement | null>(null);
  let currentOffset = $state(0);
  let followingEnd = $state(true);
  /**
   * How tall the viewport actually is, bound rather than read from the
   * element: the layout resizes it, so a measurement taken once would
   * describe a list that no longer exists.
   */
  let viewportHeight = $state(0);

  let widthStyle = $derived(typeof width === "number" ? `${width}px` : width);
  let safeItemSize = $derived(Math.max(1, itemSize || 1));
  let innerHeight = $derived(itemCount * safeItemSize);
  let visibleCount = $derived(Math.ceil(viewportHeight / safeItemSize));
  let maxOffset = $derived(Math.max(0, innerHeight - viewportHeight));
  let effectiveOffset = $derived(Math.min(Math.max(0, currentOffset), maxOffset));
  let startIndex = $derived(
    Math.max(0, Math.floor(effectiveOffset / safeItemSize) - overscanCount),
  );
  let endIndex = $derived(Math.min(itemCount, startIndex + visibleCount + overscanCount * 2 + 1));
  let firstVisible = $derived(Math.floor(effectiveOffset / safeItemSize));
  let endVisible = $derived(Math.min(itemCount, firstVisible + visibleCount));
  let visibleIndexes = $derived(
    Array.from({ length: Math.max(0, endIndex - startIndex) }, (_, index) => startIndex + index),
  );

  $effect(() => {
    const first = firstVisible;
    const end = endVisible;
    untrack(() => onVisibleRangeChange?.(first, end));
  });

  onMount(() => {
    if (followEnd || scrollOffset <= 0) return;
    void tick().then(() => {
      if (!viewport) return;
      viewport.scrollTop = Math.min(scrollOffset, maxOffset);
      currentOffset = viewport.scrollTop;
    });
  });

  function handleScroll() {
    if (!viewport) return;
    currentOffset = viewport.scrollTop;
    followingEnd =
      viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= safeItemSize * 2;
  }

  function scrollToEnd() {
    if (!viewport) return;
    viewport.scrollTop = Math.max(0, viewport.scrollHeight - viewport.clientHeight);
    currentOffset = viewport.scrollTop;
  }

  $effect(() => {
    if (!followEnd || !followingEnd || itemCount < 1) return;
    void maxOffset;
    void tick().then(scrollToEnd);
  });

  $effect(() => {
    // A filter, sync, or tab switch can shrink the list while preserving an
    // old scroll offset. Keep the virtual window inside the new item range.
    const nextMaxOffset = maxOffset;
    void itemCount;
    void tick().then(() => {
      if (!viewport) return;
      const clamped = Math.min(viewport.scrollTop, nextMaxOffset);
      if (viewport.scrollTop !== clamped) viewport.scrollTop = clamped;
      currentOffset = clamped;
    });
  });
</script>

<div
  bind:this={viewport}
  bind:clientHeight={viewportHeight}
  class="virtual-list-wrapper"
  style:width={widthStyle}
  onscroll={handleScroll}
>
  <div class="virtual-list-inner" style:height={`${innerHeight}px`}>
    {#each visibleIndexes as index (getKey ? getKey(index) : index)}
      {@render row(
        index,
        `position:absolute;top:${index * safeItemSize}px;left:0;width:100%;height:${safeItemSize}px;`,
      )}
    {/each}
  </div>
</div>

<style>
  /*
   * The list takes exactly the room its container gives it and never sizes
   * to its rows: rows arriving, leaving or loading cannot move anything
   * around it. Size containment keeps the rows out of the container's
   * intrinsic size too.
   */
  .virtual-list-wrapper {
    position: relative;
    flex: 1 1 0;
    height: 100%;
    min-height: 0;
    overflow: auto;
    contain: strict;
    will-change: scroll-position;
  }

  .virtual-list-inner {
    position: relative;
    width: 100%;
  }
</style>
