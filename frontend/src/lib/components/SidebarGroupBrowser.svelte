<script lang="ts" generics="T, G">
  import ArrowLeft from "@lucide/svelte/icons/arrow-left";
  import type { Snippet } from "svelte";
  import SidebarList from "./SidebarList.svelte";
  let {
    groups,
    rows,
    selected,
    groupTitle,
    groupKey,
    groupPoster,
    groupEntry,
    entry: renderEntry,
    getKey,
    posterUrl,
    onback,
    scrollOffset = 0,
    loading = false,
    message = "",
  }: {
    groups: G[];
    rows: T[];
    selected: G | null;
    groupTitle: (group: G) => string;
    groupKey: (group: G) => string;
    groupPoster: (group: G) => string | null;
    groupEntry: Snippet<[G, number, string]>;
    entry: Snippet<[T, number, string]>;
    getKey: (row: T) => string | number;
    posterUrl: (row: T) => string | null;
    onback: () => void;
    scrollOffset?: number;
    loading?: boolean;
    message?: string;
  } = $props();
  type Row = { kind: "group"; value: G } | { kind: "item"; value: T };
  let visible = $derived<Row[]>([
    ...(selected === null ? groups.map((value): Row => ({ kind: "group", value })) : []),
    ...rows.map((value): Row => ({ kind: "item", value })),
  ]);
</script>

<div class="group-browser">
  {#if selected !== null}
    <button type="button" class="group-back" onclick={onback}
      ><ArrowLeft size={14} />Back to results</button
    >
    <div class="group-heading truncate">{groupTitle(selected)}</div>
  {/if}
  <div class="group-list">
    {#key selected === null ? "root" : groupKey(selected)}
      <SidebarList
        rows={visible}
        {scrollOffset}
        {loading}
        {message}
        getKey={(row) =>
          row.kind === "group" ? `group:${groupKey(row.value)}` : `item:${getKey(row.value)}`}
        posterUrl={(row) => (row.kind === "group" ? groupPoster(row.value) : posterUrl(row.value))}
      >
        {#snippet entry(row: Row, index: number, style: string)}
          {#if row.kind === "group"}{@render groupEntry(row.value, index, style)}
          {:else}{@render renderEntry(row.value, index, style)}{/if}
        {/snippet}
      </SidebarList>
    {/key}
  </div>
</div>

<style>
  .group-browser {
    display: flex;
    flex-direction: column;
    height: 100%;
  }
  .group-list {
    flex: 1;
    min-height: 0;
  }
  .group-back {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    color: var(--accent);
    font-size: var(--text-sm);
    text-align: left;
  }
  .group-back:hover {
    background: var(--bg-hover);
  }
  .group-heading {
    padding: 0 var(--space-3) var(--space-2);
    color: var(--text-secondary);
    font-size: var(--text-sm);
    font-weight: 500;
    border-bottom: var(--border-subtle);
  }
</style>
