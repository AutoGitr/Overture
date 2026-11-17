import { checkConnectivity } from "../../generated/rest/sdk.gen";
import type { MediaServerStatus } from "../../generated/ws";
import { sdkData } from "../rest/sdk";

/** Whether each media server answered Overture's last request, as the server reports it. */
class MediaServerState {
  /** Each configured server's state, the lead first. */
  statuses = $state<MediaServerStatus[]>([]);
  checking = $state(false);

  /** The servers that are down or refuse their credentials. */
  get down(): MediaServerStatus[] {
    return this.statuses.filter(
      (status) => status.state === "unreachable" || status.state === "rejected",
    );
  }

  /** Replace every server's state, as a snapshot reports them. */
  storeAll(statuses: MediaServerStatus[]): void {
    this.statuses = statuses;
  }

  /** Replace one server's state, as an event reports it. */
  store(status: MediaServerStatus): void {
    const known = this.statuses.some((current) => current.server_id === status.server_id);
    this.statuses = known
      ? this.statuses.map((current) => (current.server_id === status.server_id ? status : current))
      : [...this.statuses, status];
  }

  /** Ask the servers again; the answers arrive as status events. */
  async check(): Promise<void> {
    this.checking = true;
    try {
      await sdkData(checkConnectivity());
    } finally {
      this.checking = false;
    }
  }
}

export const mediaServerState = new MediaServerState();
