import {
  isWebSocketEventName,
  routeServerWebSocketMessage,
  type RealtimeSnapshot,
  type ServerWebSocketDataMessage,
  type WebSocketDataEventName,
  type WebSocketHandlerMap,
} from "../../generated/ws";
import { artPreviewState } from "../stores/artPreviewState.svelte";
import { downloadState } from "../stores/downloadState.svelte";
import { invalidateSchedules } from "../rest/cache";
import { storePublicDatasetStatus } from "./cache";
import { clearJobSnapshot, JOB_PROJECTION_HANDLERS, jobKindOf, resetJobStates } from "./jobs";

const PROJECTION_HANDLERS: WebSocketHandlerMap = {
  "realtime.snapshot": () => {},
  ...JOB_PROJECTION_HANDLERS,
  "download.started": (data) => downloadState.handleStarted(data),
  "download.progress": (data) => downloadState.handleProgress(data),
  "download.completed": (data) => {
    downloadState.handleFinished(data);
    // A file already in place brings no new art for a preview to wait for.
    if (data.unchanged) artPreviewState.jobEnded(data.job.id);
  },
  "download.cancelled": (data) => {
    downloadState.handleFinished(data);
    artPreviewState.jobEnded(data.job.id);
  },
  "download.failed": (data) => {
    downloadState.handleFailed(data);
    artPreviewState.jobEnded(data.job.id);
  },
  "collection.theme.updated": () => {},
  "library.item.upserted": () => {},
  "library.item.removed": () => {},
  "library.items.changed": () => {},
  "public-dataset.updated": (data) => storePublicDatasetStatus(data),
  "item.updated": () => {},
  "job.snapshot.cleared": (data) => {
    clearJobSnapshot(data.kind);
  },
  "schedules.changed": (data) => void invalidateSchedules(data.kind),
};

export function projectRealtimeMessage(message: ServerWebSocketDataMessage): void {
  routeServerWebSocketMessage(message, PROJECTION_HANDLERS);
}

export function resetRealtimeProjection(): void {
  resetJobStates();
  downloadState.replaceSnapshot([]);
  downloadState.clearTransientFailures();
  artPreviewState.reset();
}

/**
 * Adopt a snapshot. One from a new epoch replaces everything the client
 * showed. One that continues the current epoch resumes the jobs it names, so
 * a run's log survives a brief reconnect, and forgets the jobs it no longer
 * names, whose result was cleared meanwhile.
 */
export function projectRealtimeSnapshot(snapshot: RealtimeSnapshot, continuing: boolean): void {
  if (continuing) {
    resetJobStates(new Set((snapshot.jobs ?? []).map((job) => jobKindOf(job.event))));
  } else {
    resetRealtimeProjection();
  }
  downloadState.replaceSnapshot(snapshot.downloads ?? [], snapshot.downloads_pending ?? false);

  for (const job of snapshot.jobs ?? []) {
    if (
      !isWebSocketEventName(job.event) ||
      job.event === "ping" ||
      job.event === "realtime.snapshot"
    ) {
      continue;
    }
    routeServerWebSocketMessage(
      {
        epoch: snapshot.epoch,
        sequence: snapshot.sequence,
        event: job.event,
        data: job.data,
      } as ServerWebSocketDataMessage & { event: WebSocketDataEventName },
      PROJECTION_HANDLERS,
    );
  }
}
