import { SvelteMap } from "svelte/reactivity";
import type { DownloadJobsPage, MediaItemRead } from "../../generated/rest/types.gen";
import type { DownloadJobEvent } from "../../generated/ws";
import { getDownloadBacklog } from "../../generated/rest/sdk.gen";
import { sdkData } from "../rest/sdk";
import { errorMessage, jobEventErrorMessage } from "../utils/errors";
import { notify } from "./notificationState.svelte";

/** How long a failed download stays listed after its notice. */
const FAILURE_DISPLAY_MS = 5000;

export interface DownloadJob {
  job_id: string;
  media_item_id: number | null;
  collection_server_id: string | null;
  media_type: MediaItemRead["media_type"] | null;
  title: string | null;
  job_type: string;
  art_type: string | null;
  season_id: number | null;
  percent: number;
  stage: string;
  status: "running" | "failed";
}

function buildJob(data: DownloadJobEvent, status: DownloadJob["status"] = "running"): DownloadJob {
  const target = data.job.target;
  const itemTarget = target.target_type === "item" ? target : null;
  const collectionTarget = target.target_type === "collection_theme" ? target : null;

  return {
    job_id: data.job.id,
    media_item_id: itemTarget?.media_item_id ?? null,
    collection_server_id: collectionTarget?.collection_server_id ?? null,
    media_type: collectionTarget?.media_type ?? null,
    title: itemTarget?.title ?? collectionTarget?.title ?? null,
    job_type: itemTarget?.job_type ?? data.job.kind,
    art_type: itemTarget?.art_type ?? null,
    season_id: itemTarget?.season_id ?? null,
    percent: data.percent ?? 0,
    stage: data.stage ?? "starting",
    status,
  };
}

/** The item or collection a download belongs to, if any. */
function ownerKey(job: DownloadJob): string | null {
  if (job.media_item_id !== null) return `item:${job.media_item_id}`;
  if (job.collection_server_id !== null) return `collection:${job.collection_server_id}`;
  return null;
}

class DownloadState {
  /** Running and recently failed downloads by job id. */
  private readonly jobs = new SvelteMap<string, DownloadJob>();
  /** Each owner's job ids, so a row follows only its own downloads' progress. */
  private readonly jobIdsByOwner = new SvelteMap<string, ReadonlySet<string>>();
  /** Each listed failure's removal, so a repeat failure restarts its own timer. */
  private readonly failureTimers = new Map<string, ReturnType<typeof setTimeout>>();
  loadingPending = $state(false);
  pendingError = $state("");
  private pendingRequest: AbortController | null = null;
  private changedDuringRequest = new Set<string>();

  private trackLiveChange(jobId: string) {
    if (this.pendingRequest) this.changedDuringRequest.add(jobId);
  }

  private put(job: DownloadJob) {
    this.cancelFailureTimer(job.job_id);
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
    this.trackLiveChange(data.job.id);
    this.put(buildJob(data));
  }

  handleProgress(data: DownloadJobEvent) {
    this.trackLiveChange(data.job.id);
    this.put(buildJob(data));
  }

  handleFinished(data: DownloadJobEvent) {
    this.trackLiveChange(data.job.id);
    this.remove(data.job.id);
  }

  handleFailed(data: DownloadJobEvent) {
    this.trackLiveChange(data.job.id);
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
    this.trackLiveChange(options.jobId);
    this.put({
      job_id: options.jobId,
      media_item_id: options.mediaItemId,
      collection_server_id: null,
      media_type: null,
      title: null,
      job_type: options.jobType,
      art_type: options.artType ?? null,
      season_id: options.seasonId ?? null,
      percent: 0,
      stage: "queued",
      status: "running",
    });
  }

  trackQueuedCollectionJob(options: {
    jobId: string;
    serverId: string;
    mediaType: MediaItemRead["media_type"];
    title: string;
  }) {
    this.trackLiveChange(options.jobId);
    this.put({
      job_id: options.jobId,
      media_item_id: null,
      collection_server_id: options.serverId,
      media_type: options.mediaType,
      title: options.title,
      job_type: "collection_theme",
      art_type: null,
      season_id: null,
      percent: 0,
      stage: "queued",
      status: "running",
    });
  }

  replaceSnapshot(events: DownloadJobEvent[], pending = false) {
    this.pendingRequest?.abort();
    this.pendingRequest = null;
    this.changedDuringRequest.clear();
    this.loadingPending = false;
    this.pendingError = "";
    for (const timer of this.failureTimers.values()) clearTimeout(timer);
    this.failureTimers.clear();
    this.jobs.clear();
    this.jobIdsByOwner.clear();
    for (const event of events) this.put(buildJob(event));
    if (pending) void this.loadPending();
  }

  async loadPending() {
    this.pendingRequest?.abort();
    const request = new AbortController();
    this.pendingRequest = request;
    this.changedDuringRequest.clear();
    this.loadingPending = true;
    this.pendingError = "";
    let after: string | null = null;
    try {
      do {
        const page: DownloadJobsPage = await sdkData(
          getDownloadBacklog({
            query: { limit: 100, after },
            signal: request.signal,
            throwOnError: true,
          }),
        );
        if (request !== this.pendingRequest) return;
        for (const event of page.items) {
          // A live event after this fetch began always supersedes its database page.
          if (!this.changedDuringRequest.has(event.job.id)) {
            this.put(buildJob(event));
          }
        }
        if (page.next_cursor === after && after !== null)
          throw new Error("Invalid download page cursor");
        after = page.next_cursor;
      } while (after !== null);
    } catch (error) {
      if (request === this.pendingRequest && !request.signal.aborted) {
        this.pendingError = errorMessage(error, "Could not load queued downloads. Please retry.");
      }
    } finally {
      if (request === this.pendingRequest) {
        this.pendingRequest = null;
        this.changedDuringRequest.clear();
        this.loadingPending = false;
      }
    }
  }

  getJobsForItem(mediaItemId: number): DownloadJob[] {
    return this.jobsOf(`item:${mediaItemId}`);
  }

  /** Whether a download of the kind runs for the item; `artType` narrows art to one slot. */
  isDownloadingType(mediaItemId: number, jobType: string, artType?: string): boolean {
    return this.getJobsForItem(mediaItemId).some(
      (job) =>
        job.status === "running" &&
        job.job_type === jobType &&
        (artType === undefined || job.art_type === artType),
    );
  }

  /** Return the running downloads of one kind, so a run can show its queue. */
  activeJobsByType(jobType: string): DownloadJob[] {
    return [...this.jobs.values()].filter(
      (job) => job.status === "running" && job.job_type === jobType,
    );
  }

  /** The collection's download, a running one before a failed one. */
  getCollectionJob(serverId: string): DownloadJob | null {
    const jobs = this.jobsOf(`collection:${serverId}`);
    return jobs.find((job) => job.status === "running") ?? jobs[0] ?? null;
  }

  isDownloadingCollection(serverId: string): boolean {
    return this.getCollectionJob(serverId)?.status === "running";
  }

  get activeCount(): number {
    let count = 0;
    for (const job of this.jobs.values()) if (job.status === "running") count += 1;
    return count;
  }
}

export const downloadState = new DownloadState();
