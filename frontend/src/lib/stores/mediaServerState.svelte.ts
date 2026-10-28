import { checkConnectivity } from "../../generated/rest/sdk.gen";
import type { MediaServerStatus } from "../../generated/ws";
import { sdkData } from "../rest/sdk";

/** Whether the media server answered Overture's last request, as the server reports it. */
class MediaServerState {
  current = $state<MediaServerStatus>({ state: "unknown", message: "" });
  checking = $state(false);

  /** The server is down or refuses its credentials. */
  get down(): boolean {
    return this.current.state === "unreachable" || this.current.state === "rejected";
  }

  store(status: MediaServerStatus): void {
    this.current = status;
  }

  /** Ask the server again; the answer arrives as a status event. */
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
