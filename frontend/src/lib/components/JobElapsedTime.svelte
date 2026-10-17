<script lang="ts">
  import { serverClock } from "../realtime/serverClock";
  import { formatElapsedTime } from "../utils/jobTime";

  let {
    startedAt,
    finishedAt,
  }: {
    startedAt: string | null | undefined;
    finishedAt: string | null | undefined;
  } = $props();

  // Both ends come from the server's clock, so a run counts from 0s and its
  // final time continues from the last running value.
  let elapsed = $derived(
    startedAt ? formatElapsedTime(startedAt, finishedAt || serverClock.now) : "",
  );
</script>

{#if elapsed}
  <div class="stat-item">
    time taken: <span class="stat-value">{elapsed}</span>
  </div>
{/if}
