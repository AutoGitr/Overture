/** State for the Server Audit job. */
import type { ServerAuditProgressEvent, ServerAuditResult } from "../../generated/ws";
import { auditRowKey } from "../utils/serverAuditPopup";
import { CollectingJobState, type Selectable } from "./collectingJobState.svelte";

export type SelectableServerAuditResult = Selectable<ServerAuditResult>;

class ServerAuditState extends CollectingJobState<ServerAuditProgressEvent, ServerAuditResult> {
  constructor() {
    super({
      itemsKey: "results",
      foundKey: "results_found",
      failureMessage: "Server audit failed",
      actionable: (result) => !result.refreshed,
    });
  }

  /** Forget the last fix outcome of the rows *keys* names, as a new fix begins. */
  clearRefreshErrors(keys: ReadonlySet<string>) {
    this.items = this.items.map((result) =>
      keys.has(auditRowKey(result)) ? { ...result, refresh_error: null } : result,
    );
  }
}

export const serverAuditState = new ServerAuditState();
