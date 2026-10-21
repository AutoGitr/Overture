<script lang="ts">
  import type { Snippet } from "svelte";

  let { children }: { children: Snippet } = $props();
</script>

<!-- A popup's cards, one under another at the popup's full width. -->
<div class="card-column">
  {@render children()}
</div>

<style>
  .card-column {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .card-column > :global(*) {
    min-width: 0;
    margin: 0;
  }
</style>
