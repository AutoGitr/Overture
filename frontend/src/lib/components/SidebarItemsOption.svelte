<script lang="ts">
  import type { SidebarTab } from "../utils/sidebarDomain";

  let {
    checked,
    sidebarItems,
    muted = false,
    onchange,
  }: {
    checked: boolean;
    sidebarItems: { type: SidebarTab; itemIds: number[] } | null;
    /** Dims the option while another selection is in effect. */
    muted?: boolean;
    onchange: (checked: boolean) => void;
  } = $props();

  let count = $derived(sidebarItems?.itemIds.length ?? 0);
  let noun = $derived(
    sidebarItems?.type === "movie"
      ? count === 1
        ? "movie"
        : "movies"
      : count === 1
        ? "show"
        : "shows",
  );
</script>

<hr />
<div>
  <label class="checkbox-group" class:muted>
    <input
      type="checkbox"
      {checked}
      disabled={!count && !checked}
      onchange={(event) => onchange(event.currentTarget.checked)}
    />
    <span
      >Current sidebar items
      {#if sidebarItems}
        <span class="item-count">{count.toLocaleString()} {noun}</span>
      {/if}
    </span>
  </label>
  <div class="option-note">
    {#if sidebarItems}
      Uses the items matching the sidebar's filters and search instead of the selection above.
    {:else}
      Show movies or shows in the sidebar to use this.
    {/if}
  </div>
</div>

<style>
  .muted {
    opacity: 0.5;
  }

  hr {
    border: 0;
    border-top: var(--border-subtle);
    margin: var(--space-3) 0;
  }
</style>
