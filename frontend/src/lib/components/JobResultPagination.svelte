<script lang="ts">
  let {
    page,
    running = false,
  }: {
    page: {
      runId: string | null;
      total: number;
      offset: number;
      size: number;
      loading: boolean;
      error: string;
      load: (offset?: number) => Promise<void>;
    };
    running?: boolean;
  } = $props();
</script>

{#if page.runId}
  <div class="result-pagination" aria-label="Result pages">
    {#if running}
      <span>Showing recent results. All results are available when the job finishes.</span>
    {:else}
      <button
        class="btn btn-ghost"
        disabled={page.loading || page.offset === 0}
        onclick={() => page.load(Math.max(0, page.offset - page.size))}>Previous</button
      >
      <span aria-live="polite">
        {#if page.loading}Loading results...
        {:else if page.total === 0}No results
        {:else}Results {page.offset + 1}-{Math.min(page.offset + page.size, page.total)} of {page.total}{/if}
      </span>
      <button
        class="btn btn-ghost"
        disabled={page.loading || page.offset + page.size >= page.total}
        onclick={() => page.load(page.offset + page.size)}>Next</button
      >
    {/if}
    {#if page.error}
      <span class="text-danger" role="alert">{page.error}</span>
      <button class="btn btn-ghost" disabled={page.loading} onclick={() => page.load()}
        >Retry</button
      >
    {/if}
  </div>
{/if}

<style>
  .result-pagination {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: var(--space-2);
    font-size: var(--text-xs);
  }
</style>
