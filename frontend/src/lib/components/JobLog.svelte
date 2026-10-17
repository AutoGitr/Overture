<script lang="ts">
  import type { JobLogEntry } from "../../generated/ws";
  import { OUTCOME_TONES, logEntryTime } from "../utils/jobLog";
  import VirtualList from "./VirtualList.svelte";

  let { entries }: { entries: JobLogEntry[] } = $props();
</script>

<div class="job-log">
  <VirtualList
    width="100%"
    maxHeight="min(20vh, 288px)"
    itemCount={entries.length}
    itemSize={24}
    overscanCount={3}
    followEnd
  >
    {#snippet row(index: number, style: string)}
      {@const entry = entries[index]}
      {#if entry}
        <div class="job-log-row" {style} title="{entry.target} - {entry.reason}">
          <time class="log-time" datetime={entry.at}>{logEntryTime(entry)}</time>
          <span class="log-outcome {OUTCOME_TONES[entry.outcome]}">{entry.outcome}</span>
          <span class="log-target">{entry.target}</span>
          <span class="log-reason">{entry.reason}</span>
        </div>
      {/if}
    {/snippet}
  </VirtualList>
</div>
