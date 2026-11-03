<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    checked,
    onselect,
    children,
  }: { checked: boolean; onselect: () => void; children: Snippet } = $props();
</script>

<button
  type="button"
  class={["option", { checked }]}
  role="menuitemradio"
  aria-checked={checked}
  tabindex="-1"
  onclick={onselect}
>
  {@render children()}
</button>

<style>
  .option {
    display: flex;
    align-items: center;
    justify-content: space-between;
    width: 100%;
    padding: var(--space-2) var(--space-3);
    background: transparent;
    border: none;
    text-align: left;
    font-size: var(--text-sm);
    color: var(--text-secondary);
    cursor: pointer;
  }

  .option:hover {
    background: var(--bg-hover);
    color: var(--text-primary);
  }

  .checked {
    color: var(--accent);
    font-weight: 500;
  }
</style>
