/** Jobs whose state is their lifecycle and counters, and nothing more. */
import type { BackupJobEvent, CatalogSyncEvent, SyncJobEvent } from "../../generated/ws";
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

export const catalogSyncState = new JobLifecycleState<CatalogSyncEvent>({
  failureMessage: "OvertureDB sync failed",
});
