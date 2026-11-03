<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    title,
    kind,
    enabled = $bindable(),
    children,
  }: {
    title: string;
    /** The asset kind the workflow fetches, which colours it. */
    kind: "art" | "theme";
    /** Whether the run includes this workflow; its settings show only then. */
    enabled: boolean;
    children: Snippet;
  } = $props();

  const bodyId = $props.id();
</script>

<section class={["option-card workflow-card", kind]} aria-label={title}>
  <div class="heading-row">
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
    gap: var(--space-2);
  }

  .art {
    --section-accent: var(--asset-art);
  }

  .theme {
    --section-accent: var(--asset-theme);
  }

  .heading-row .form-label {
    color: var(--section-accent);
  }

  .workflow-body {
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }
</style>
