import { mediaServerState } from "../stores/mediaServerState.svelte";
import type {
  DownloadJobEvent,
  RealtimeSnapshot,
  ServerWebSocketDataMessage,
} from "../../generated/ws";
import {
  applyRestCachePolicy,
  refreshRemovedDownloadTargets,
  storePublicDatasetStatus,
} from "./cache";
import { projectRealtimeMessage, projectRealtimeSnapshot } from "./projector";
import { serverClock } from "./serverClock";

const ACTIVE_DOWNLOAD_STATUSES = new Set(["pending", "running", "started", "progress"]);

type DownloadMessage = Extract<ServerWebSocketDataMessage, { event: `download.${string}` }>;

function isDownloadMessage(message: ServerWebSocketDataMessage): message is DownloadMessage {
  return message.event.startsWith("download.");
}

function snapshotDownloads(snapshot: RealtimeSnapshot): DownloadJobEvent[] {
  return snapshot.downloads ?? [];
}

/**
 * How far this client has followed the server's event stream.
 *
 * The ordering watermark belongs to the connection lifetime, independent of
 * REST cache eviction and which views are currently mounted.
 */
class RealtimeStream {
  private epoch: string | null = null;
  private sequence = -1;
  private downloads: DownloadJobEvent[] = [];

  /** Return whether a snapshot for this epoch has been applied. */
  isSynced(epoch: string): boolean {
    return this.epoch === epoch;
  }

  /** Forget the watermark, so the next snapshot is adopted unconditionally. */
  reset(): void {
    this.epoch = null;
    this.sequence = -1;
    this.downloads = [];
  }

  /** Adopt a snapshot unless it is strictly behind what is already applied. */
  applySnapshot(snapshot: RealtimeSnapshot): boolean {
    if (this.epoch === snapshot.epoch && this.sequence > snapshot.sequence) return false;
    serverClock.sync(snapshot.server_time);
    const previous = this.downloads;
    const continuing = this.epoch === snapshot.epoch;
    this.epoch = snapshot.epoch;
    this.sequence = snapshot.sequence;
    this.downloads = snapshotDownloads(snapshot);
    projectRealtimeSnapshot(snapshot, continuing);
    refreshRemovedDownloadTargets(previous, this.downloads);
    storePublicDatasetStatus(snapshot.public_dataset_status);
    mediaServerState.store(snapshot.media_server);
    return true;
  }

  /** Apply the next event, ignoring one from another epoch or already seen. */
  applyEvent(message: ServerWebSocketDataMessage): boolean {
    if (message.epoch !== this.epoch || message.sequence <= this.sequence) return false;
    this.sequence = message.sequence;
    this.trackDownload(message);
    projectRealtimeMessage(message);
    applyRestCachePolicy(message);
    return true;
  }

  /** Keep the active download set current between snapshots. */
  private trackDownload(message: ServerWebSocketDataMessage): void {
    if (!isDownloadMessage(message)) return;
    const event = message.data;
    const remaining = this.downloads.filter((job) => job.job.id !== event.job.id);
    this.downloads = ACTIVE_DOWNLOAD_STATUSES.has(event.job.status)
      ? [...remaining, event]
      : remaining;
  }
}

export const realtimeStream = new RealtimeStream();
