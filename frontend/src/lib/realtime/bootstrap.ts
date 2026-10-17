import { getRealtimeSnapshot } from "../../generated/rest/sdk.gen";
import type { RealtimeSnapshot } from "../../generated/ws";
import { sdkData } from "../rest/sdk";
import { realtimeStream } from "./stream";

/**
 * Read the realtime snapshot over REST and apply it.
 */
export async function loadRealtimeSnapshot(signal: AbortSignal): Promise<void> {
  const snapshot = await sdkData(getRealtimeSnapshot({ signal, throwOnError: true }));
  signal.throwIfAborted();
  realtimeStream.applySnapshot(snapshot as RealtimeSnapshot);
}
