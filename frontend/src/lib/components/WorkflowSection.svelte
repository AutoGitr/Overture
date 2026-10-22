<script lang="ts">
  import type { Snippet } from "svelte";

  let { label, note, children }: { label: string; note?: string; children: Snippet } = $props();
</script>

<div class="section">
  <div class="section-heading">
    <span class="form-label">{label}</span>
    {#if note}
      <span class="text-muted">{note}</span>
    {/if}
  </div>
  {@render children()}
</div>

<style>
  .section-heading {
    display: flex;
    flex-wrap: wrap;
    align-items: baseline;
    gap: var(--space-1) var(--space-3);
    font-size: var(--text-sm);
  }

  .section {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
</style>
