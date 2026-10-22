<script lang="ts">
  import type { Snippet } from "svelte";

  let { label, note, children }: { label: string; note?: string; children: Snippet } = $props();
</script>

<div class="section">
  <div class="heading-row">
    <span class="form-label">{label}</span>
    {#if note}
      <span class="hint">{note}</span>
    {/if}
  </div>
  {@render children()}
</div>

<style>
  .section {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
</style>
