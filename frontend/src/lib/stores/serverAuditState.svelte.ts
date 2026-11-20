/** State for the server audit job. */
import type { ServerAuditProgressEvent, ServerAuditResult } from "../../generated/ws";
import { ASSET_LABELS } from "../utils/artTypes";
import { AUDIT_STATUS_LABELS, auditRowKey } from "../utils/serverAuditPopup";
import { CollectingJobState, type Selectable } from "./collectingJobState.svelte";
import { settingsState } from "./settingsState.svelte";

export type SelectableServerAuditResult = Selectable<ServerAuditResult>;

/** The group of the results about one media server, named as it is configured now. */
function serverGroup(serverId: number, name: string | null | undefined) {
  const server = settingsState.server(serverId);
  return [
    `server:${serverId}`,
    server?.title ?? name ?? `Server ${serverId}`,
    server?.type,
  ] as const;
}

class ServerAuditState extends CollectingJobState<ServerAuditProgressEvent, ServerAuditResult> {
  constructor() {
    super({
      items: (event) => event.results,
      found: (event) => event.results_found,
      groupsOf: (result) => [
        [`type:${result.art_type}`, ASSET_LABELS[result.art_type]],
        [`status:${result.status}`, AUDIT_STATUS_LABELS[result.status]],
        ...(result.server_id != null ? [serverGroup(result.server_id, result.server)] : []),
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
