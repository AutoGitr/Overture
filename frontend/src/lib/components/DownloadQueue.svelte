<script lang="ts">
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import type { ServerAsset } from "../../generated/rest/types.gen";
  import {
    type DownloadJob,
    type DownloadLane,
    downloadStageLabel,
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
  <section class={["downloads", lane]} aria-label={label}>
    <header class="heading-row downloads-header">
      <span class="form-label">{label}</span>
      {#if queue.waiting > 0}
        <span class="hint" role="status">{queue.waiting} queued</span>
      {/if}
    </header>
    {#each rows as job, slot (job?.job_id ?? `slot-${slot}`)}
      {#if job}
        {@const what = kind(job)}
        {@const stage = downloadStageLabel(job)}
        <div class="download-row" style:--download-progress="{job.percent}%">
          <LoaderCircle size={12} class="animate-spin download-spinner" />
          <span class="download-title truncate" title={job.title ?? undefined}
            >{job.title || "Queued download"}</span
          >
          <span class="download-kind truncate"
            ><span class="badge {what.badge}">{what.label}</span>{#if job.source}
              <span class="text-muted">{job.source}</span>{/if}</span
          >
          <span class="download-stage truncate" title={stage}>{stage}</span>
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

  .art {
    --download-accent: var(--asset-art);
  }

  .theme {
    --download-accent: var(--asset-theme);
  }

  .downloads-header {
    height: 24px;
  }

  .downloads-header .form-label {
    color: var(--download-accent);
  }

  /* Every row shares one column grid, so titles, kinds and steps line up
     across rows and a changing step moves nothing. Its progress is a line
     along its bottom edge. */
  .download-row {
    position: relative;
    display: grid;
    grid-template-columns: 12px minmax(0, 1fr) 11rem 9rem;
    align-items: center;
    gap: var(--space-2);
    height: 28px;
    padding: 0 var(--space-3);
    overflow: hidden;
    font-size: var(--text-xs);
    color: var(--text-secondary);
    background: var(--bg-root);
    border: var(--border-subtle);
    border-radius: var(--radius-sm);
  }

  .download-row::after {
    content: "";
    position: absolute;
    left: 0;
    bottom: 0;
    width: var(--download-progress, 0%);
    height: 2px;
    background: var(--download-accent);
    transition: width 0.3s ease;
  }

  .download-row :global(.download-spinner) {
    color: var(--download-accent);
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
    font-weight: 500;
  }

  .download-stage {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  @container (max-width: 30rem) {
    .download-row {
      grid-template-columns: 12px minmax(0, 1fr) 11rem;
    }

    .download-row .badge {
      display: none;
    }
  }
</style>
