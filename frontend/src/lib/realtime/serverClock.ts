import { createSubscriber } from "svelte/reactivity";

/**
 * The server's clock as seen from this browser.
 *
 * Job timestamps come from the server, so a running duration measured against
 * the browser's own clock is off by however far the two clocks disagree. The
 * realtime snapshot carries the server time, which fixes the offset.
 */
class ServerClock {
  private offsetMs = 0;

  /** One shared one-second tick, running only while something reads `now`. */
  private readonly tick = createSubscriber((update) => {
    const interval = setInterval(update, 1000);
    return () => clearInterval(interval);
  });

  /** Align with a timestamp the server has just sent. */
  sync(serverTime: string): void {
    const server = Date.parse(serverTime);
    if (!Number.isNaN(server)) this.offsetMs = server - Date.now();
  }

  /** The server's current time in milliseconds; reactive reads update every second. */
  get now(): number {
    this.tick();
    return Date.now() + this.offsetMs;
  }

  /** The server's current time as an ISO timestamp, for client-side job stamps. */
  isoNow(): string {
    return new Date(this.now).toISOString();
  }
}

export const serverClock = new ServerClock();
