<script lang="ts">
  let {
    job,
    unit,
  }: {
    job: { planning: boolean; done: number; total: number | null };
    /** What the run counts, such as "items" or "folders". */
    unit: string;
  } = $props();
</script>

<div class="stat-item">
  {#if job.planning}
    Planning...
  {:else}
    <span class="stat-value">{job.done}</span>/<span>{job.total ?? 0}</span> {unit}
  {/if}
</div>
