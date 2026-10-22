import { createSubscriber } from "svelte/reactivity";

/**
 * The server's clock as seen from this browser.
 *
 * Job timestamps come from the server, so a running duration measured against
 * the browser's own clock is off by however far the two clocks disagree. The
 * realtime snapshot carries the server time, which fixes the offset.
 */
class ServerClock {
  private serverMs = Date.now();
  private sampledAt = performance.now();
  private notify: (() => void) | undefined;

  /** Sample inside each second so scheduler jitter cannot skip a displayed second. */
  private readonly tick = createSubscriber((update) => {
    this.notify = update;
    const interval = setInterval(update, 250);
    return () => {
      clearInterval(interval);
      this.notify = undefined;
    };
  });

  /** Align with a timestamp the server has just sent. */
  sync(serverTime: string): void {
    const server = Date.parse(serverTime);
    if (Number.isNaN(server)) return;
    this.serverMs = server;
    this.sampledAt = performance.now();
    this.notify?.();
  }

  /** Advance from server time without following browser wall-clock corrections. */
  get now(): number {
    this.tick();
    return this.serverMs + performance.now() - this.sampledAt;
  }

  /** The server's current time as an ISO timestamp, for client-side job stamps. */
  isoNow(): string {
    return new Date(this.now).toISOString();
  }
}

export const serverClock = new ServerClock();
