<script lang="ts">
  import type { Snippet } from "svelte";
  import type { JobLogEntry } from "../../generated/ws";
  import JobLog from "./JobLog.svelte";

  let {
    progress,
    log = [],
    stats,
    children,
  }: {
    progress: number;
    log?: JobLogEntry[];
    stats: Snippet;
    children?: Snippet;
  } = $props();
</script>

<div class="progress-section">
  <div class="progress-bar">
    <div class="progress-bar-fill" style="width:{progress}%"></div>
  </div>

  {@render stats()}

  {#if log.length > 0}
    <JobLog entries={log} />
  {/if}

  {#if children}
    {@render children()}
  {/if}
</div>
