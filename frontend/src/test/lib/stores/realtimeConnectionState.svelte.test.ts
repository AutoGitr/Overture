import { describe, expect, it } from "vitest";
import { realtimeConnectionState } from "../../../lib/stores/realtimeConnectionState.svelte";

describe("realtimeConnectionState", () => {
  it("tracks connection phases, sync time, and resets cleanly", () => {
    realtimeConnectionState.reset();
    expect(realtimeConnectionState.connected).toBe(false);
    expect(realtimeConnectionState.phase).toBe("disconnected");

    realtimeConnectionState.setPhase("connecting");
    expect(realtimeConnectionState.connected).toBe(false);

    realtimeConnectionState.setPhase("connected");
    expect(realtimeConnectionState.connected).toBe(true);

    realtimeConnectionState.synced();
    expect(realtimeConnectionState.lastSyncedAt).not.toBeNull();
    expect(realtimeConnectionState.error).toBe("");

    realtimeConnectionState.reset();
    expect(realtimeConnectionState.phase).toBe("disconnected");
    expect(realtimeConnectionState.connected).toBe(false);
    expect(realtimeConnectionState.lastSyncedAt).toBeNull();
  });
});
