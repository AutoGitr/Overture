import {
  JOB_EVENT_PREFIXES,
  JOB_KIND_LABELS,
  type JobKind,
  type LifecycleStatus,
  type WebSocketHandlerMap,
} from "../../generated/ws";
import { assetManagerState } from "../stores/assetManagerState.svelte";
import { matchState, themeJobState } from "../stores/bulkJobState.svelte";
import { backupState, publicDatasetSyncState, syncState } from "../stores/jobStates.svelte";
import { serverAuditFixState } from "../stores/serverAuditFixState.svelte";
import { notify } from "../stores/notificationState.svelte";
import { serverAuditState } from "../stores/serverAuditState.svelte";
import { jobEventErrorMessage, type JobEventErrorLike } from "../utils/errors";

/** Every job a popup follows, by its kind. Downloads are tracked per item. */
export const JOB_STATES = {
  sync: syncState,
  bulk_art: matchState,
  bulk_theme: themeJobState,
  asset_scan: assetManagerState,
  server_audit: serverAuditState,
  server_audit_fix: serverAuditFixState,
  public_dataset_sync: publicDatasetSyncState,
  backup: backupState,
} as const;

type FollowedKind = keyof typeof JOB_STATES;
type JobEventName = {
  [Kind in FollowedKind]: `${(typeof JOB_EVENT_PREFIXES)[Kind]}.${LifecycleStatus}`;
}[FollowedKind];

const STATUS_HANDLERS = {
  started: "handleStarted",
  progress: "handleProgress",
  completed: "handleCompleted",
  stopped: "handleStopped",
  failed: "handleFailed",
} as const satisfies Record<LifecycleStatus, string>;

/** Say how a run ended; a run that is still going says nothing. */
function announceEnding(kind: FollowedKind, status: string, data: JobEventErrorLike): void {
  const name = JOB_KIND_LABELS[kind];
  const run = `${name.slice(0, 1).toUpperCase()}${name.slice(1)}`;
  if (status === "completed") notify.success(`${run} finished.`);
  else if (status === "stopped") notify.info(`${run} stopped.`);
  else if (status === "failed")
    notify.error(jobEventErrorMessage(data, "See its log in Operations."), {
      title: `${run} failed`,
    });
}

/** Route each job's lifecycle events to the state that follows it, and announce endings. */
// Object.fromEntries types its keys as string, so the cast restores the event
// names; the entries come from the same JOB_STATES and STATUS_HANDLERS as
// JobEventName.
export const JOB_PROJECTION_HANDLERS = Object.fromEntries(
  Object.entries(JOB_STATES).flatMap(([kind, state]) =>
    Object.entries(STATUS_HANDLERS).map(([status, handler]) => [
      `${JOB_EVENT_PREFIXES[kind as FollowedKind]}.${status}`,
      (data: never) => {
        state[handler](data);
        announceEnding(kind as FollowedKind, status, data);
      },
    ]),
  ),
) as unknown as Pick<WebSocketHandlerMap, JobEventName>;

/** Forget the job's last result, as the server announced. */
export function clearJobSnapshot(kind: JobKind): void {
  if (kind in JOB_STATES) JOB_STATES[kind as FollowedKind].reset();
}

/**
 * Forget the state of every job, or, with *except*, of every job but those
 * kinds, as before a snapshot that restores them.
 */
export function resetJobStates(except: ReadonlySet<string | null> = new Set()): void {
  for (const [kind, state] of Object.entries(JOB_STATES)) {
    if (!except.has(kind)) state.reset();
  }
}

/** Return the job kind a lifecycle event belongs to, if a popup follows it. */
export function jobKindOf(event: string): FollowedKind | null {
  for (const kind of Object.keys(JOB_STATES) as FollowedKind[]) {
    const prefix = JOB_EVENT_PREFIXES[kind];
    if (Object.keys(STATUS_HANDLERS).some((status) => event === `${prefix}.${status}`)) {
      return kind;
    }
  }
  return null;
}
