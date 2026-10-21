<script lang="ts">
  import type { Snippet } from "svelte";

  let { label, note, children }: { label: string; note?: string; children: Snippet } = $props();
</script>

<div class="section">
  <span class="form-label">{label}</span>
  {#if note}
    <p class="option-note">{note}</p>
  {/if}
  {@render children()}
</div>

<style>
  .section {
    display: flex;
    flex-direction: column;
    gap: var(--space-2);
  }
</style>
