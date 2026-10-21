<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    title,
    enabled = $bindable(),
    children,
  }: {
    title: string;
    /** Whether the run includes this workflow; its settings show only then. */
    enabled: boolean;
    children: Snippet;
  } = $props();

  const bodyId = $props.id();
</script>

<section class="option-card workflow-card" aria-label={title}>
  <div class="workflow-header">
    <span class="form-label">{title}</span>
    <label class="checkbox-group">
      <input type="checkbox" bind:checked={enabled} aria-controls={bodyId} />
      <span>Enabled</span>
    </label>
  </div>
  {#if enabled}
    <div class="workflow-body" id={bodyId}>
      {@render children()}
    </div>
  {/if}
</section>

<style>
  .workflow-card {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }

  .workflow-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-3);
  }

  .workflow-header .form-label {
    margin: 0;
  }

  .workflow-body {
    display: flex;
    flex-direction: column;
    gap: var(--space-4);
  }
</style>
