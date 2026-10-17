import { OPERATIONS } from "./operations";

const list = new Intl.ListFormat("en", { type: "conjunction" });

/**
 * The server's library gate, as the client can see it: Assets, Renamer and
 * Server Audit run together, but never alongside a full sync. Knowing the
 * blocker up front lets a tab hold its start button and say why, instead of
 * submitting a run the server refuses.
 *
 * New-media polling shares the sync slot without publishing sync events, so
 * a running `syncState` is always a full sync.
 */
export const libraryGate = {
  /** Why Assets, Renamer or Server Audit cannot start now, or `null`. */
  get itemsBlocked(): string | null {
    return OPERATIONS.sync.running ? "Wait for the full sync to finish." : null;
  },

  /** Why a full sync cannot start now, or `null`. */
  get syncBlocked(): string | null {
    const running = [OPERATIONS.assets, OPERATIONS.renamer, OPERATIONS.audit]
      .filter((operation) => operation.running)
      .map((operation) => operation.label);
    return running.length ? `Wait for ${list.format(running)} to finish.` : null;
  },
};
