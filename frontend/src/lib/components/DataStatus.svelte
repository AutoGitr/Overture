<script lang="ts">
  import { delayedFlag } from "../utils/delayedFlag.svelte";
  import { errorMessage } from "../utils/errors";

  let {
    label,
    error,
    loading = false,
    hasData = false,
    onretry,
  }: {
    label: string;
    error?: unknown;
    loading?: boolean;
    hasData?: boolean;
    onretry: () => unknown;
  } = $props();

  // A load that answers quickly never shows its placeholder at all.
  const showLoading = delayedFlag(() => loading && !hasData);
  const showRetrying = delayedFlag(() => loading);
</script>

{#if error}
  <div class="data-status" role="alert">
    <span
      >{label}: {errorMessage(error, "Could not load data.")}
      {hasData ? "Showing last loaded data." : "Data is unavailable."}</span
    >
    <button
      type="button"
      class="btn btn-ghost btn-sm"
      disabled={showRetrying.current}
      onclick={() => {
        if (!loading) onretry();
      }}
    >
      {showRetrying.current ? "Retrying..." : `Retry ${label}`}
    </button>
  </div>
{:else if showLoading.current}
  <p class="data-loading" role="status">Loading {label.toLowerCase()}...</p>
{/if}

<style>
  .data-status {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: var(--space-2);
    padding: var(--space-2) var(--space-3);
    font-size: var(--text-sm);
    color: var(--danger);
    background: var(--danger-muted);
    border: 1px solid oklch(from var(--danger) l c h / 0.25);
    border-radius: var(--radius-sm);
    overflow-wrap: anywhere;
  }

  .data-status span {
    flex: 1;
    min-width: min(200px, 100%);
  }

  .data-loading {
    padding: var(--space-4);
    color: var(--text-secondary);
  }
</style>
