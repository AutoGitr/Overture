/** State for the Server Audit job. */
import type { ServerAuditProgressEvent, ServerAuditResult } from "../../generated/ws";
import { ASSET_LABELS } from "../utils/artTypes";
import { AUDIT_STATUS_LABELS, auditRowKey } from "../utils/serverAuditPopup";
import { CollectingJobState, type Selectable } from "./collectingJobState.svelte";

export type SelectableServerAuditResult = Selectable<ServerAuditResult>;

class ServerAuditState extends CollectingJobState<ServerAuditProgressEvent, ServerAuditResult> {
  constructor() {
    super({
      items: (event) => event.results,
      found: (event) => event.results_found,
      groupsOf: (result) => [
        [`type:${result.art_type}`, ASSET_LABELS[result.art_type]],
        [`status:${result.status}`, AUDIT_STATUS_LABELS[result.status]],
      ],
      groupOrder: [
        ...Object.keys(ASSET_LABELS).map((type) => `type:${type}`),
        ...Object.keys(AUDIT_STATUS_LABELS).map((status) => `status:${status}`),
      ],
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
