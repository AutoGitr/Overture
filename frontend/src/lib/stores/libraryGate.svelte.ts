import { OPERATION_TABS, OPERATIONS } from "./operations";
import { downloadState } from "./downloadState.svelte";
import type { OperationsTab } from "./uiState.svelte";

const list = new Intl.ListFormat("en", { type: "conjunction" });

/**
 * The server's library gate, as the client can see it: one operation runs at
 * a time, and a full sync also waits for downloads. Knowing the blocker up
 * front lets a tab hold its start button and say why, instead of submitting
 * a run the server refuses.
 *
 * New-media polling shares the sync slot without publishing sync events, so
 * a running `syncState` is always a full sync.
 */
export const libraryGate = {
  /** Why *tab*'s operation cannot start now, or `null`. */
  blocked(tab: OperationsTab): string | null {
    const running = OPERATION_TABS.filter(
      (other) => other !== tab && OPERATIONS[other].running,
    ).map((other) => (other === "sync" ? "the full sync" : OPERATIONS[other].label));
    if (tab === "sync" && downloadState.activeCount > 0) running.push("downloads");
    return running.length ? `Wait for ${list.format(running)} to finish.` : null;
  },
};
