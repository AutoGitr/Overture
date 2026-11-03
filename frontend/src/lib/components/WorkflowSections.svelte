<script lang="ts">
  import type { Snippet } from "svelte";
  let { children }: { children: Snippet } = $props();
</script>

<div class="workflow-sections">{@render children()}</div>

<style>
  .workflow-sections {
    --section-border: 0;
    /* Each heading's accent rule already parts the sections. */
    --section-divider: 0;
    --section-radius: 0;
    --section-background: transparent;
    --section-header-padding: var(--space-4) 0;
    --section-header-border: 0;
    --form-padding: var(--space-4) 0;
    --section-padding: var(--space-4) 0;
    width: 100%;
    min-width: 0;
  }
</style>
