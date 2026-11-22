<script lang="ts">
  let {
    label,
    value,
    detail = null,
  }: {
    label: string;
    value: string;
    /** Shown dimmed after the value, such as its unit or what it is out of. */
    detail?: string | null;
  } = $props();
</script>

<!-- One figure of a statistics card: its name over its value. -->
<div class="metric">
  <span class="metric-label">{label}</span>
  <span class="metric-value">
    {value}
    {#if detail}
      <span class="metric-detail">({detail})</span>
    {/if}
  </span>
</div>

<style>
  .metric {
    display: flex;
    flex-direction: column;
    gap: 2px;
  }

  .metric-label {
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  .metric-value {
    font-family: var(--font-mono);
    font-size: var(--text-sm);
    font-weight: 600;
    color: var(--text-primary);
  }

  .metric-detail {
    color: var(--text-tertiary);
    font-size: var(--text-xs);
    font-weight: normal;
  }
</style>
