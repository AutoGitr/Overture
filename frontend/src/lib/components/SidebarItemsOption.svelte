<script lang="ts">
  import type { SidebarTab } from "../utils/sidebarDomain";

  let {
    checked,
    sidebarItems,
    muted = false,
    collectionIds,
    onchange,
  }: {
    checked: boolean;
    sidebarItems: { type: SidebarTab; itemIds: number[] } | null;
    /** Dims the option while another selection is in effect. */
    muted?: boolean;
    collectionIds?: number[];
    onchange: (checked: boolean) => void;
  } = $props();

  let count = $derived(collectionIds?.length ?? sidebarItems?.itemIds.length ?? 0);
  let noun = $derived(
    collectionIds
      ? count === 1
        ? "collection"
        : "collections"
      : sidebarItems?.type === "movie"
        ? count === 1
          ? "movie"
          : "movies"
        : count === 1
          ? "show"
          : "shows",
  );
</script>

<hr />
<label class={["checkbox-group", { muted }]}>
  <input
    type="checkbox"
    {checked}
    disabled={!count && !checked}
    onchange={(event) => onchange(event.currentTarget.checked)}
  />
  <span>Current sidebar items</span>
  {#if sidebarItems || collectionIds}
    <span class="item-count">{count.toLocaleString()} {noun}</span>
  {:else}
    <span class="hint">Show movies or shows in the sidebar to use this.</span>
  {/if}
</label>

<style>
  .muted {
    opacity: 0.5;
  }

  hr {
    width: 100%;
    margin: 0;
    border: 0;
    border-top: var(--border-subtle);
  }
</style>
