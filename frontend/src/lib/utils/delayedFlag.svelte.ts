/** How long a state must last before it is worth showing. */
export const SETTLE_DELAY_MS = 400;

/**
 * Follow `source`, but turn on only once it has stayed on for `delayMs`.
 *
 * Short-lived states - a request that answers at once, a reconnect that
 * succeeds straight away - would otherwise blink on and off. Turning off is
 * immediate, so the real outcome is never held back. Create it during
 * component initialisation.
 */
export function delayedFlag(source: () => boolean, delayMs = SETTLE_DELAY_MS) {
  // Track the boolean, not what it is computed from: a state handing over to
  // another (a request's pending flag to the job it started) must not restart
  // the delay while the flag stays on.
  const active = $derived(source());
  let on = $state(false);
  $effect(() => {
    if (!active) {
      on = false;
      return;
    }
    const timer = setTimeout(() => (on = true), delayMs);
    return () => clearTimeout(timer);
  });
  return {
    get current(): boolean {
      return on;
    },
  };
}

/**
 * Follow `source` once it has stopped changing for `delayMs`, so typing does
 * not send a request per keystroke. Create it during component initialisation.
 */
export function debounced<T>(source: () => T, delayMs = SETTLE_DELAY_MS) {
  let value = $state(source());
  $effect(() => {
    const next = source();
    const timer = setTimeout(() => (value = next), delayMs);
    return () => clearTimeout(timer);
  });
  return {
    get current(): T {
      return value;
    },
  };
}
