<script lang="ts">
  import type { Component } from "svelte";
  import type { Coverage } from "../../generated/rest/types.gen";
  import { formatBytes } from "../utils/popupFormat";

  /** How much of some assets Overture holds locally and has matched. */
  let {
    title,
    icon: Icon,
    coverage,
    breakdown = [],
    showAverage = false,
  }: {
    title: string;
    icon: Component<{ size?: number; class?: string }>;
    coverage: Coverage;
    /** The same figures for parts of the whole, such as movies and shows. */
    breakdown?: readonly { label: string; coverage: Coverage }[];
    showAverage?: boolean;
  } = $props();

  let localWidth = $derived(Math.min(100, Math.max(0, coverage.local_percentage)));
</script>

<div class="coverage-card">
  <div class="coverage-header">
    <div class="coverage-title">
      <Icon size={18} class="accent" />
      <h3>{title}</h3>
    </div>
    <span class="coverage-badge">
      {coverage.local_percentage}% Local &middot; {coverage.matched_percentage}% Matched
    </span>
  </div>

  <div
    class="progress-bar coverage-progress"
    role="progressbar"
    aria-label="{title}: held locally"
    aria-valuenow={coverage.local_percentage}
    aria-valuemin={0}
    aria-valuemax={100}
  >
    <div class="progress-bar-fill" style:width="{localWidth}%"></div>
  </div>

  <div class="metrics-row">
    <div class="metric-item">
      <span class="metric-label">Local Files</span>
      <span class="metric-val">
        {coverage.local_files.toLocaleString()} / {coverage.total.toLocaleString()}
      </span>
    </div>
    <div class="metric-item">
      <span class="metric-label">DB Matched</span>
      <span class="metric-val">
        {coverage.matched_files.toLocaleString()} / {coverage.total.toLocaleString()}
      </span>
    </div>
    <div class="metric-item">
      <span class="metric-label">Total Size</span>
      <span class="metric-val">{formatBytes(coverage.total_size_bytes)}</span>
    </div>
    {#if showAverage}
      <div class="metric-item">
        <span class="metric-label">Average Size</span>
        <span class="metric-val">{formatBytes(coverage.avg_size_bytes)}</span>
      </div>
    {/if}
  </div>

  {#if breakdown.length}
    <div class="sub-breakdown">
      {#each breakdown as part (part.label)}
        <div class="sub-item">
          <span class="sub-label">{part.label}:</span>
          <span>
            Local: {part.coverage.local_files.toLocaleString()} ({part.coverage.local_percentage}%)
            &middot; DB Matched: {part.coverage.matched_files.toLocaleString()}
            ({part.coverage.matched_percentage}%) &middot; {formatBytes(
              part.coverage.total_size_bytes,
            )}
          </span>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .coverage-card {
    background: var(--bg-secondary);
    border: var(--border-subtle);
    border-radius: var(--radius-md);
    padding: var(--space-4);
    display: flex;
    flex-direction: column;
    gap: var(--space-3);
  }

  .coverage-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .coverage-title {
    display: flex;
    align-items: center;
    gap: var(--space-2);
  }

  .coverage-title h3 {
    margin: 0;
    font-size: var(--text-base);
    font-weight: 600;
    color: var(--text-primary);
  }

  .coverage-title :global(.accent) {
    color: var(--accent);
  }

  .coverage-badge {
    font-family: var(--font-mono);
    font-size: var(--text-xs);
    font-weight: 600;
    padding: 2px 8px;
    border-radius: var(--radius-full);
    background: var(--badge-muted-bg);
    color: var(--accent);
  }

  /* Raised above the card's secondary surface. */
  .coverage-progress {
    background: var(--bg-elevated);
  }

  .metrics-row {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
    gap: var(--space-3);
  }

  .metric-item {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .metric-label {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  .metric-val {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-primary);
  }

  .sub-breakdown {
    display: flex;
    flex-wrap: wrap;
    gap: var(--space-4);
    padding-top: var(--space-2);
    border-top: var(--border-subtle);
    font-size: var(--text-xs);
    color: var(--text-secondary);
  }

  .sub-item {
    display: flex;
    gap: var(--space-1);
    word-break: break-word;
  }

  .sub-label {
    font-weight: 500;
    color: var(--text-primary);
  }
</style>
