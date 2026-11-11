import { syncState } from "../stores/jobStates.svelte";
import { syncSelection, type SyncFocus } from "../stores/syncSelection.svelte";
import { uiState } from "../stores/uiState.svelte";
import { clearJobResult } from "./jobSnapshots";

/**
 * Open Sync in Operations with only these groups and collections chosen, as
 * every sync runs from there. The last finished run's result gives way to the
 * choice; a running one stays in view.
 */
export async function openSync(focus: SyncFocus): Promise<void> {
  syncSelection.focus(focus);
  if (!syncState.running && syncState.hasRun) await clearJobResult("sync");
  uiState.openOperations("sync");
}
