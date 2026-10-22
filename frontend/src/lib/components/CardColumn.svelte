<script lang="ts">
  import type { Snippet } from "svelte";

  let { children }: { children: Snippet } = $props();
</script>

<!-- A popup's sections, one under another across the popup's full width,
     parted by hairlines. A section that sets `--section-accent` is marked
     with that colour along its left edge. -->
<div class="card-column">
  {@render children()}
</div>

<style>
  .card-column {
    display: flex;
    flex-direction: column;
    margin-inline: calc(-1 * var(--popup-pad));
  }

  .card-column > :global(*) {
    min-width: 0;
    margin: 0;
    padding: var(--space-4) var(--popup-pad);
    background: none;
    border: 0;
    border-radius: 0;
    box-shadow: inset 3px 0 0 var(--section-accent, transparent);
  }

  .card-column > :global(* + *) {
    border-top: var(--border-subtle);
  }
</style>
