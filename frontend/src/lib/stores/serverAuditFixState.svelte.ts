/** State for the job that fixes server-audit findings and verifies each fix. */
import type { ServerAuditFixEvent } from "../../generated/ws";
import { JobLifecycleState } from "./jobLifecycleState.svelte";

class ServerAuditFixState extends JobLifecycleState<ServerAuditFixEvent, "verified" | "unchanged"> {
  /**
   * Keys of the audit rows this browser asked to fix, until the run ends.
   * A row among them without an outcome yet is still waiting on the server.
   */
  pending = $state<ReadonlySet<string>>(new Set());

  constructor() {
    super({
      failureMessage: "Fixing the audit findings failed",
      counters: ["verified", "unchanged"],
    });
  }

  override handleCompleted(data: ServerAuditFixEvent) {
    super.handleCompleted(data);
    this.pending = new Set();
  }

  override handleStopped(data: ServerAuditFixEvent) {
    super.handleStopped(data);
    this.pending = new Set();
  }

  override handleFailed(data: ServerAuditFixEvent) {
    super.handleFailed(data);
    this.pending = new Set();
  }

  /** Remember the rows a fix request names, before the server can answer. */
  markSubmitted(rowKeys: string[]) {
    this.pending = new Set(rowKeys);
  }

  override reset() {
    super.reset();
    this.pending = new Set();
  }
}

export const serverAuditFixState = new ServerAuditFixState();
