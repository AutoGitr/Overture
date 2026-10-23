import { SvelteMap } from "svelte/reactivity";
import type { DownloadJobEvent } from "../../generated/ws";
import { jobEventErrorMessage } from "../utils/errors";
import { notify } from "./notificationState.svelte";

/** How long a failed download stays listed after its notice. */
const FAILURE_DISPLAY_MS = 5000;

/** The worker pool a download runs in: artwork, or themes of items and collections. */
export type DownloadLane = "art" | "theme";

export function downloadLane(jobType: string): DownloadLane {
  return jobType === "art" ? "art" : "theme";
}

export interface DownloadJob {
  job_id: string;
  media_item_id: number | null;
  collection_id: number | null;
  title: string | null;
  job_type: string;
  art_type: string | null;
  season_id: number | null;
  percent: number;
  stage: string;
  /** The step the download is on, counted from 1, while it reports one. */
  step: number | null;
  steps: number | null;
  status: "pending" | "running" | "failed";
  /**
   * The row a running download holds among its lane's, kept until it ends
   * and then handed to the next one, so finishing a download never moves
   * the others; `-1` while it is not running.
   */
  slot: number;
}

function buildJob(data: DownloadJobEvent, status?: DownloadJob["status"]): DownloadJob {
  const target = data.job.target;
  const itemTarget = target.target_type === "item" ? target : null;
  const collectionTarget = target.target_type === "collection_theme" ? target : null;

  return {
    job_id: data.job.id,
    media_item_id: itemTarget?.media_item_id ?? null,
    collection_id: collectionTarget?.collection_id ?? null,
    title: itemTarget?.title ?? collectionTarget?.title ?? null,
    job_type: itemTarget?.job_type ?? target.target_type,
    art_type: itemTarget?.art_type ?? null,
    season_id: itemTarget?.season_id ?? null,
    percent: data.percent ?? 0,
    stage: data.stage ?? "starting",
    step: data.step,
    steps: data.steps,
    status: status ?? (data.job.status === "pending" ? "pending" : "running"),
    slot: -1,
  };
}

/** What a download is doing, with its step when it reports one: "Transcoding 3/4". */
export function downloadStageLabel(job: DownloadJob): string {
  // A failed download's stage is its error message.
  if (job.status === "failed") return job.stage;
  const stage = job.stage.charAt(0).toUpperCase() + job.stage.slice(1);
  return job.step !== null && job.steps !== null ? `${stage} ${job.step}/${job.steps}` : stage;
}

/** The item or collection a download belongs to, if any. */
function ownerKey(job: DownloadJob): string | null {
  if (job.media_item_id !== null) return `item:${job.media_item_id}`;
  if (job.collection_id !== null) return `collection:${job.collection_id}`;
  return null;
}

class DownloadState {
  /** Running and recently failed downloads by job id. */
  private readonly jobs = new SvelteMap<string, DownloadJob>();
  /** Each owner's job ids, so a row follows only its own downloads' progress. */
  private readonly jobIdsByOwner = new SvelteMap<string, ReadonlySet<string>>();
  /** Each listed failure's removal, so a repeat failure restarts its own timer. */
  private readonly failureTimers = new Map<string, ReturnType<typeof setTimeout>>();

  private put(job: DownloadJob) {
    this.cancelFailureTimer(job.job_id);
    const previous = this.jobs.get(job.job_id);
    if (job.status === "running") {
      job.slot = previous?.status === "running" ? previous.slot : this.freeSlot(job);
    }
    this.jobs.set(job.job_id, job);
    const key = ownerKey(job);
    if (key === null) return;
    const ids = this.jobIdsByOwner.get(key);
    if (!ids?.has(job.job_id)) this.jobIdsByOwner.set(key, new Set([...(ids ?? []), job.job_id]));
  }

  private remove(jobId: string) {
    this.cancelFailureTimer(jobId);
    const job = this.jobs.get(jobId);
    if (!job) return;
    this.jobs.delete(jobId);
    const key = ownerKey(job);
    const ids = key === null ? undefined : this.jobIdsByOwner.get(key);
    if (key === null || !ids) return;
    const rest = [...ids].filter((id) => id !== jobId);
    if (rest.length > 0) this.jobIdsByOwner.set(key, new Set(rest));
    else this.jobIdsByOwner.delete(key);
  }

  /** The lowest row no other running download of the job's lane holds. */
  private freeSlot(job: DownloadJob): number {
    const taken = this.lane(downloadLane(job.job_type)).running.map((other) => other.slot);
    let slot = 0;
    while (taken.includes(slot)) slot++;
    return slot;
  }

  private jobsOf(key: string): DownloadJob[] {
    return [...(this.jobIdsByOwner.get(key) ?? [])].flatMap((id) => this.jobs.get(id) ?? []);
  }

  private cancelFailureTimer(jobId: string) {
    clearTimeout(this.failureTimers.get(jobId));
    this.failureTimers.delete(jobId);
  }

  clearTransientFailures() {
    for (const job of [...this.jobs.values()]) {
      if (job.status === "failed") this.remove(job.job_id);
    }
  }

  handleStarted(data: DownloadJobEvent) {
    this.put(buildJob(data));
  }

  handleProgress(data: DownloadJobEvent) {
    this.put(buildJob(data));
  }

  handleFinished(data: DownloadJobEvent) {
    this.remove(data.job.id);
    // Report a completed collection theme alongside other download notifications.
    const target = data.job.target;
    if (data.job.status === "completed" && target.target_type === "collection_theme") {
      notify.success(`Theme applied to ${target.title}.`);
    }
  }

  handleFailed(data: DownloadJobEvent) {
    const jobId = data.job.id;
    const failed = buildJob(data, "failed");
    failed.stage = jobEventErrorMessage(data, "failed");
    this.put(failed);
    this.failureTimers.set(
      jobId,
      setTimeout(() => this.remove(jobId), FAILURE_DISPLAY_MS),
    );
    notify.error(failed.stage, {
      title: failed.title ? `Download failed: ${failed.title}` : "Download failed",
    });
  }

  trackQueuedItemJob(options: {
    jobId: string;
    mediaItemId: number;
    jobType: string;
    artType?: string | null;
    seasonId?: number | null;
  }) {
    this.put({
      job_id: options.jobId,
      media_item_id: options.mediaItemId,
      collection_id: null,
      title: null,
      job_type: options.jobType,
      art_type: options.artType ?? null,
      season_id: options.seasonId ?? null,
      percent: 0,
      stage: "queued",
      step: null,
      steps: null,
      status: "running",
      slot: -1,
    });
  }

  trackQueuedCollectionJob(options: { jobId: string; collectionId: number; title: string }) {
    this.put({
      job_id: options.jobId,
      media_item_id: null,
      collection_id: options.collectionId,
      title: options.title,
      job_type: "collection_theme",
      art_type: null,
      season_id: null,
      percent: 0,
      stage: "queued",
      step: null,
      steps: null,
      status: "running",
      slot: -1,
    });
  }

  /** Replace every download with the snapshot's queued and running ones. */
  replaceSnapshot(events: DownloadJobEvent[]) {
    for (const timer of this.failureTimers.values()) clearTimeout(timer);
    this.failureTimers.clear();
    this.jobs.clear();
    this.jobIdsByOwner.clear();
    for (const event of events) this.put(buildJob(event));
  }

  getJobsForItem(mediaItemId: number): DownloadJob[] {
    return this.jobsOf(`item:${mediaItemId}`);
  }

  /** Whether a download of the kind runs for the item; `artType` narrows art to one slot. */
  isDownloadingType(mediaItemId: number, jobType: string, artType?: string): boolean {
    return this.getJobsForItem(mediaItemId).some(
      (job) =>
        (job.status === "running" || job.status === "pending") &&
        job.job_type === jobType &&
        (artType === undefined || job.art_type === artType),
    );
  }

  /** The lane's running downloads by row, and how many wait behind them. */
  lane(lane: DownloadLane): { running: DownloadJob[]; waiting: number } {
    const running: DownloadJob[] = [];
    let waiting = 0;
    for (const job of this.jobs.values()) {
      if (downloadLane(job.job_type) !== lane) continue;
      if (job.status === "running") running.push(job);
      else if (job.status === "pending") waiting++;
    }
    return { running: running.sort((a, b) => a.slot - b.slot), waiting };
  }

  /** The collection's download, a running or pending one before a failed one. */
  getCollectionJob(collectionId: number): DownloadJob | null {
    const jobs = this.jobsOf(`collection:${collectionId}`);
    return (
      jobs.find((job) => job.status === "running" || job.status === "pending") ?? jobs[0] ?? null
    );
  }

  isDownloadingCollection(collectionId: number): boolean {
    const status = this.getCollectionJob(collectionId)?.status;
    return status === "running" || status === "pending";
  }

  get activeCount(): number {
    let count = 0;
    for (const job of this.jobs.values()) {
      if (job.status === "running" || job.status === "pending") count += 1;
    }
    return count;
  }
}

export const downloadState = new DownloadState();
