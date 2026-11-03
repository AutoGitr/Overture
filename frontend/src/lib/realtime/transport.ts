import {
  isServerWebSocketMessage,
  type ClientWebSocketMessage,
  type ServerWebSocketDataMessage,
} from "../../generated/ws";
import { invalidateReconnectData } from "../rest/cache";
import { reportUnauthorized } from "../rest/transport";
import { realtimeConnectionState } from "../stores/realtimeConnectionState.svelte";
import { errorMessage } from "../utils/errors";
import { loadRealtimeSnapshot } from "./bootstrap";
import { realtimeStream } from "./stream";

/** Reconnect when the bounded pre-snapshot buffer fills. */
const MAX_BUFFERED_EVENTS = 500;
/** The shortest gap between two snapshot requests on one connection. */
const RESYNC_INTERVAL = 2000;
const IDLE_TIMEOUT = 45000;
const FALLBACK_INTERVAL = 5000;
const SNAPSHOT_TIMEOUT = 15000;

class RealtimeTransport {
  private socket: WebSocket | null = null;
  private reconnectDelay = 1000;
  private readonly maxDelay = 60000;
  private timeoutId: ReturnType<typeof setInterval> | null = null;
  private fallbackId: ReturnType<typeof setInterval> | null = null;
  private reconnectId: ReturnType<typeof setTimeout> | null = null;
  private snapshotController: AbortController | null = null;
  private syncedConnection = false;
  private openedAt = 0;
  private lastMessage = 0;
  private running = false;
  private resyncRequestedAt = 0;
  private buffered: ServerWebSocketDataMessage[] = [];

  connect(): void {
    if (this.socket) return;
    const starting = !this.running;
    this.running = true;
    this.startFallbackLoop();
    realtimeConnectionState.setPhase("connecting");
    if (starting) {
      this.reconnectDelay = 1000;
      void this.refreshSnapshot();
    }

    const protocol = location.protocol === "https:" ? "wss:" : "ws:";
    const url = `${protocol}//${location.host}/ws`;

    let socket: WebSocket;
    try {
      socket = new WebSocket(url);
      this.socket = socket;
      this.openedAt = this.lastMessage = Date.now();
      this.startTimeout();
    } catch {
      realtimeConnectionState.setPhase("disconnected");
      this.scheduleReconnect();
      return;
    }

    socket.onopen = () => {
      if (this.socket !== socket) return;
      this.reconnectDelay = 1000;
      this.lastMessage = Date.now();
      this.openedAt = this.lastMessage;
      this.resetStream();
      realtimeConnectionState.setPhase("syncing");
      this.requestResync();
    };

    socket.onmessage = (event: MessageEvent) => {
      if (this.socket !== socket) return;
      try {
        const message: unknown = JSON.parse(event.data);
        if (!isServerWebSocketMessage(message)) return;
        this.lastMessage = Date.now();
        if (message.event === "ping") return;
        this.handleMessage(message);
      } catch {
        realtimeConnectionState.error = "Could not read a live update. Reconnecting...";
        socket.close();
      }
    };

    socket.onclose = (event: CloseEvent) => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.resetStream();
      this.stopTimeout();
      realtimeConnectionState.setPhase("disconnected");
      if (event.code === 4001) {
        this.disconnect();
        reportUnauthorized();
        return;
      }
      if (this.running) this.scheduleReconnect();
    };

    socket.onerror = () => {
      if (this.socket === socket) socket.close();
    };
  }

  disconnect(): void {
    this.running = false;
    this.stopTimeout();
    this.stopFallbackLoop();
    this.stopReconnect();
    const socket = this.socket;
    this.socket = null;
    socket?.close();
    this.snapshotController?.abort();
    this.snapshotController = null;
    this.resetStream();
    realtimeConnectionState.reset();
  }

  async retry(): Promise<void> {
    this.stopReconnect();
    this.connect();
    await this.refreshSnapshot();
  }

  private async refreshSnapshot(): Promise<void> {
    if (!this.running || this.snapshotController) return;
    const controller = new AbortController();
    this.snapshotController = controller;
    realtimeConnectionState.refreshing = true;
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(SNAPSHOT_TIMEOUT)]);
    try {
      await loadRealtimeSnapshot(signal);
      signal.throwIfAborted();
      await invalidateReconnectData();
      signal.throwIfAborted();
      realtimeConnectionState.synced();
    } catch (error) {
      if (!controller.signal.aborted) {
        realtimeConnectionState.error =
          error instanceof Error && error.name === "TimeoutError"
            ? "Live data did not respond. Retrying automatically."
            : errorMessage(error, "Could not load live data. Retrying automatically.");
      }
    } finally {
      if (this.snapshotController === controller) {
        this.snapshotController = null;
        realtimeConnectionState.refreshing = false;
      }
    }
  }

  private handleMessage(message: ServerWebSocketDataMessage): void {
    if (message.event === "realtime.snapshot") {
      this.syncedConnection = true;
      this.applySnapshot(message.data);
      return;
    }
    if (this.syncedConnection && realtimeStream.isSynced(message.epoch)) {
      realtimeStream.applyEvent(message);
      return;
    }
    this.bufferUntilSynced(message);
  }

  /**
   * Hold an event that arrived before this client's snapshot, and ask for one.
   *
   * Bound both buffered events and concurrent snapshot requests so a slow
   * resync cannot cause unbounded memory growth or a request storm.
   */
  private bufferUntilSynced(message: ServerWebSocketDataMessage): void {
    this.buffered.push(message);
    if (this.buffered.length > MAX_BUFFERED_EVENTS) {
      this.socket?.close();
      return;
    }
    realtimeConnectionState.setPhase("syncing");
    if (this.syncedConnection) this.openedAt = Date.now();
    this.syncedConnection = false;
    this.requestResync();
  }

  private applySnapshot(
    snapshot: Extract<ServerWebSocketDataMessage, { event: "realtime.snapshot" }>["data"],
  ): void {
    realtimeStream.applySnapshot(snapshot);
    const buffered = this.buffered.sort((left, right) => left.sequence - right.sequence);
    this.buffered = [];
    // The stream discards whatever the snapshot already covers.
    for (const message of buffered) realtimeStream.applyEvent(message);
    realtimeConnectionState.setPhase("connected");
    const socket = this.socket;
    void invalidateReconnectData().then(
      () => {
        if (this.socket === socket) realtimeConnectionState.synced();
      },
      (error: unknown) => {
        if (this.socket === socket)
          realtimeConnectionState.error = errorMessage(
            error,
            "Could not refresh live data. Please retry.",
          );
      },
    );
  }

  private resetStream(): void {
    realtimeStream.reset();
    this.buffered = [];
    this.resyncRequestedAt = 0;
    this.syncedConnection = false;
  }

  private requestResync(): void {
    const now = Date.now();
    if (this.resyncRequestedAt && now - this.resyncRequestedAt < RESYNC_INTERVAL) return;
    this.resyncRequestedAt = now;
    const command: ClientWebSocketMessage = { event: "client.resync" };
    this.socket?.send(JSON.stringify(command));
  }

  private scheduleReconnect(): void {
    if (!this.running || this.reconnectId) return;
    this.reconnectId = setTimeout(() => {
      this.reconnectId = null;
      if (this.running) this.connect();
    }, this.reconnectDelay);
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, this.maxDelay);
  }

  private stopReconnect(): void {
    if (!this.reconnectId) return;
    clearTimeout(this.reconnectId);
    this.reconnectId = null;
  }

  private startTimeout(): void {
    this.stopTimeout();
    this.timeoutId = setInterval(() => {
      const now = Date.now();
      if (
        now - this.lastMessage > IDLE_TIMEOUT ||
        (!this.syncedConnection && now - this.openedAt > SNAPSHOT_TIMEOUT)
      ) {
        this.socket?.close();
      }
    }, 5000);
  }

  private stopTimeout(): void {
    if (!this.timeoutId) return;
    clearInterval(this.timeoutId);
    this.timeoutId = null;
  }

  private startFallbackLoop(): void {
    if (this.fallbackId) return;
    this.fallbackId = setInterval(() => {
      if (!this.running || (realtimeConnectionState.connected && !realtimeConnectionState.error)) {
        return;
      }
      void this.refreshSnapshot();
    }, FALLBACK_INTERVAL);
  }

  private stopFallbackLoop(): void {
    if (!this.fallbackId) return;
    clearInterval(this.fallbackId);
    this.fallbackId = null;
  }
}

export const realtimeTransport = new RealtimeTransport();
