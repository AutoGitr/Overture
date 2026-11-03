import { SvelteSet } from "svelte/reactivity";

/**
 * Sources that have loaded in this session. They are in the browser's cache,
 * so an image showing one appears at once instead of waiting.
 */
const loadedSources = new SvelteSet<string>();

/** Preloads in flight at once: few enough that an image on screen never queues behind them. */
const MAX_PRELOADS = 3;

/**
 * Who wants images fetched ahead: the item auto-advance opens next goes before
 * the sidebar's rows around its viewport.
 */
type Purpose = "next" | "sidebar";

const queues: Record<Purpose, string[]> = { next: [], sidebar: [] };
const inFlight = new Set<string>();

export function isImageLoaded(src: string): boolean {
  return loadedSources.has(src);
}

export function markImageLoaded(src: string): void {
  loadedSources.add(src);
}

type SaveDataNavigator = Navigator & { connection?: { saveData?: boolean } };

/** Whether the browser asks to save data, in which case nothing is fetched ahead. */
function savingData(): boolean {
  return (navigator as SaveDataNavigator).connection?.saveData === true;
}

function pump(): void {
  while (inFlight.size < MAX_PRELOADS) {
    const src = queues.next.shift() ?? queues.sidebar.shift();
    if (src === undefined) return;
    if (loadedSources.has(src) || inFlight.has(src)) continue;
    inFlight.add(src);
    const image = new Image();
    image.fetchPriority = "low";
    image.decoding = "async";
    // As every shown image: a remote artwork site never learns the page.
    image.referrerPolicy = "no-referrer";
    image.onload = () => {
      loadedSources.add(src);
      settle(src);
    };
    image.onerror = () => settle(src);
    image.src = src;
  }
}

function settle(src: string): void {
  inFlight.delete(src);
  pump();
}

/**
 * Fetch images the page is about to show, so they appear at once.
 *
 * Each purpose's sources replace its earlier ones that have not started, so a
 * sidebar window scrolled away from, or a next item no longer next, is never
 * fetched.
 */
export function preloadImages(
  sources: readonly (string | null | undefined)[],
  purpose: Purpose,
): void {
  if (savingData()) return;
  queues[purpose] = sources.filter(
    (src): src is string => !!src && !loadedSources.has(src) && !inFlight.has(src),
  );
  pump();
}
