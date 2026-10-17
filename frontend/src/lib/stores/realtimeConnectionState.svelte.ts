export type RealtimeConnectionPhase = "disconnected" | "connecting" | "syncing" | "connected";

class RealtimeConnectionState {
  phase = $state<RealtimeConnectionPhase>("disconnected");
  error = $state("");
  refreshing = $state(false);
  lastSyncedAt = $state<number | null>(null);

  reset(): void {
    this.phase = "disconnected";
    this.error = "";
    this.refreshing = false;
    this.lastSyncedAt = null;
  }

  synced(): void {
    this.lastSyncedAt = Date.now();
    this.error = "";
  }

  setPhase(phase: RealtimeConnectionPhase) {
    this.phase = phase;
  }

  get connected(): boolean {
    return this.phase === "connected";
  }
}

export const realtimeConnectionState = new RealtimeConnectionState();
