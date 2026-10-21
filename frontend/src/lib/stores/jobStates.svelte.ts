/** Jobs whose state is their lifecycle and counters, and nothing more. */
import type { BackupJobEvent, PublicDatasetSyncEvent, SyncJobEvent } from "../../generated/ws";
import { JobLifecycleState } from "./jobLifecycleState.svelte";

export const syncState = new JobLifecycleState<
  SyncJobEvent,
  "added" | "updated" | "unchanged" | "removed"
>({
  failureMessage: "Sync failed",
  counters: ["added", "updated", "unchanged", "removed"],
});

export const backupState = new JobLifecycleState<BackupJobEvent>({
  failureMessage: "Backup failed",
});

export const publicDatasetSyncState = new JobLifecycleState<PublicDatasetSyncEvent>({
  failureMessage: "OvertureDB sync failed",
});
