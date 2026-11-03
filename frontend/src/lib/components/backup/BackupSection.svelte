<script lang="ts">
  import type { Component, Snippet } from "svelte";

  let {
    icon: Icon,
    title,
    count = 0,
    children,
  }: {
    icon: Component<{ size?: number; class?: string }>;
    title: string;
    /** Shown beside the title when there is something to count. */
    count?: number;
    children: Snippet;
  } = $props();
</script>

<section class="option-card">
  <div class="section-header">
    <Icon size={16} class="section-icon" />
    <span class="form-label mb-0">
      {title}
      {#if count > 0}
        <span class="count-badge">{count}</span>
      {/if}
    </span>
  </div>
  {@render children()}
</section>

<style>
  .section-header {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    margin-bottom: var(--space-2);
  }

  .section-header :global(.section-icon) {
    color: var(--accent);
    flex-shrink: 0;
  }

  .count-badge {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-size: var(--text-xs);
    font-weight: 600;
    background: var(--accent-muted);
    color: var(--accent);
    border-radius: 99px;
    padding: 0 6px;
    min-width: 20px;
    height: 18px;
    margin-left: var(--space-2);
    vertical-align: middle;
  }
</style>
