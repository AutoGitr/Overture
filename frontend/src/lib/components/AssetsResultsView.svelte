<script lang="ts">
  import type { BulkArtJobEvent, BulkThemeJobEvent } from "../../generated/ws";
  import DownloadQueue from "./DownloadQueue.svelte";
  import JobPanel from "./JobPanel.svelte";
  import { type BulkJobState, matchState, themeJobState } from "../stores/bulkJobState.svelte";
  import type { DownloadLane } from "../stores/downloadState.svelte";
  import { settingsState } from "../stores/settingsState.svelte";
  import { workflowStatusLabel } from "../utils/assetsPopup";

  type Run = BulkJobState<BulkArtJobEvent | BulkThemeJobEvent>;

  const WORKFLOWS: { lane: DownloadLane; title: string; unit: string; run: Run }[] = [
    { lane: "art", title: "Art", unit: "slots", run: matchState },
    { lane: "theme", title: "Themes", unit: "items", run: themeJobState },
  ];

  function workers(lane: DownloadLane): number {
    const settings = settingsState.current;
    return lane === "art" ? settings.art_download_workers : settings.theme_download_workers;
  }

  /** Once a running run has queued a download, each lane worker keeps a row until it ends. */
  function reserved(run: Run, lane: DownloadLane): number {
    return run.running && run.counters.queued > 0 ? workers(lane) : 0;
  }
</script>

<!-- Each run is a few rows of the Operations grid, so their logs share its room. -->
{#each WORKFLOWS as { lane, title, unit, run } (lane)}
  {#if run.hasRun}
    <JobPanel
      --job-accent={lane === "art" ? "var(--asset-art)" : "var(--asset-theme)"}
      job={run}
      {unit}
      {title}
      status={workflowStatusLabel(run)}
      stats={[
        {
          label: "queued",
          value: run.unsettled,
          title: "Downloads waiting or still running",
          tone: "info",
        },
        {
          label: "downloaded",
          value: run.counters.downloaded,
          title: "Files downloaded and saved to disk",
          tone: "success",
        },
        {
          label: "adopted",
          value: run.counters.adopted,
          title: "Existing file kept and linked to an art URL or YouTube ID",
          tone: "violet",
        },
        { label: "skipped", value: run.counters.skipped },
        { label: "no match", value: run.counters.no_match, tone: "warning" },
        { label: "errors", value: run.errors, tone: "danger" },
      ]}
    >
      {#snippet sections()}
        <DownloadQueue {lane} label="Downloads" reserved={reserved(run, lane)} />
      {/snippet}
    </JobPanel>
  {/if}
{/each}
