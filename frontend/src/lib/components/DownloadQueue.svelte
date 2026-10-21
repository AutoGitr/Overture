<script lang="ts">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import type { ServerAsset } from "../../generated/rest/types.gen";
  import {
    type DownloadJob,
    type DownloadLane,
    downloadState,
  } from "../stores/downloadState.svelte";
  import { ASSET_BADGES, ASSET_LABELS } from "../utils/artTypes";

  let {
    lane,
    label,
    reserved = 0,
  }: {
    lane: DownloadLane;
    label: string;
    /**
     * Rows a run holds for the downloads it still waits on: the lane's busy
     * workers keep their rows between one download and the next.
     */
    reserved?: number;
  } = $props();

  let queue = $derived(downloadState.lane(lane));
  /** Each row's download, or `null` for a reserved row between downloads. */
  let rows = $derived.by((): (DownloadJob | null)[] => {
    if (reserved === 0) return queue.running;
    const count = Math.max(reserved, ...queue.running.map((job) => job.slot + 1));
    const bySlot = new Map(queue.running.map((job) => [job.slot, job]));
    return Array.from({ length: count }, (_, slot) => bySlot.get(slot) ?? null);
  });
  let shown = $derived(rows.length > 0 || queue.waiting > 0);

  function isAsset(value: string | null): value is ServerAsset {
    return value !== null && value in ASSET_LABELS;
  }

  /** What a download fetches, so art and theme rows read apart at a glance. */
  function kind(job: DownloadJob): { label: string; badge: string } {
    if (job.job_type === "collection_theme") return { label: "Collection", badge: "badge-muted" };
    const asset = job.job_type === "theme" ? "theme" : job.art_type;
    return isAsset(asset)
      ? { label: ASSET_LABELS[asset], badge: ASSET_BADGES[asset] }
      : { label: "Art", badge: "badge-muted" };
  }
</script>

{#if shown}
  <section class="downloads" aria-label={label}>
    <header class="downloads-header">
      <span class="form-label">{label}</span>
      {#if queue.waiting > 0}
        <span class="downloads-note" role="status">{queue.waiting} queued</span>
      {/if}
    </header>
    {#each rows as job, slot (job?.job_id ?? `slot-${slot}`)}
      {#if job}
        {@const what = kind(job)}
        <div class="download-row">
          <LoaderCircle size={12} class="animate-spin" />
          <span class="download-title truncate" title={job.title ?? undefined}
            >{job.title || "Queued download"}</span
          >
          <span class="badge {what.badge}">{what.label}</span>
          <span class="download-stage truncate" title={job.stage}>{job.stage}</span>
          <div class="progress-bar progress-bar-sm">
            <div class="progress-bar-fill" style:width="{job.percent}%"></div>
          </div>
          <span class="download-percent">{Math.round(job.percent)}%</span>
        </div>
      {:else}
        <div class="download-row idle">
          <span></span>
          <span class="download-title">Idle</span>
        </div>
      {/if}
    {/each}
  </section>
{/if}

<style>
  .downloads {
    display: flex;
    flex-direction: column;
    gap: var(--space-1);
    flex: none;
    container-type: inline-size;
  }

  .downloads-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: var(--space-2);
    height: 24px;
  }

  .downloads-note {
    display: flex;
    align-items: center;
    gap: var(--space-2);
    font-size: var(--text-xs);
    color: var(--text-tertiary);
  }

  /* Every row shares one column grid, so titles, kinds, stages and bars line
     up across rows and a changing stage or percentage moves nothing. */
  .download-row {
    display: grid;
    grid-template-columns: 12px minmax(0, 1fr) 7.5rem 6.5rem 80px 4ch;
    align-items: center;
    gap: var(--space-2);
    height: 28px;
    padding: 0 var(--space-2);
    font-size: var(--text-xs);
    color: var(--text-secondary);
    background: var(--bg-secondary);
    border-radius: var(--radius-sm);
  }

  .download-row .badge {
    justify-self: start;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .download-row.idle .download-title {
    grid-column: 2 / -1;
    color: var(--text-tertiary);
  }

  .download-title {
    color: var(--text-primary);
  }

  .download-percent {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  @container (max-width: 30rem) {
    .download-row {
      grid-template-columns: 12px minmax(0, 1fr) 6rem 48px 4ch;
    }

    .download-stage {
      display: none;
    }
  }
</style>
