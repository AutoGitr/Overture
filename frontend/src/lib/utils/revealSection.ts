import { tick } from "svelte";

/** How long a revealed section is kept in place while what loads around it settles. */
const SETTLE_MS = 1500;

/** What ends the settling: the person taking over the scrolling. */
const TAKEOVER_EVENTS = ["wheel", "touchstart", "keydown", "pointerdown"] as const;

let settling: AbortController | null = null;

function scrollParent(element: HTMLElement): HTMLElement {
  for (let parent = element.parentElement; parent; parent = parent.parentElement) {
    if (/(auto|scroll)/.test(getComputedStyle(parent).overflowY)) return parent;
  }
  // The page is in standards mode, where the root element scrolls the viewport.
  return document.documentElement;
}

/** Open the section's own collapsed parts; one inside another part's body stays as it is. */
function expand(section: HTMLElement): void {
  const toggles = [...section.querySelectorAll<HTMLButtonElement>("button[aria-controls]")];
  const bodies = new Set(toggles.map((toggle) => toggle.getAttribute("aria-controls")));
  for (const toggle of toggles) {
    if (toggle.getAttribute("aria-expanded") !== "false") continue;
    let parent = toggle.parentElement;
    while (parent && parent !== section && !bodies.has(parent.id)) parent = parent.parentElement;
    if (parent === section) toggle.click();
  }
}

/**
 * Bring a page section into view: open its collapsed parts, put its top at the
 * top of the scrolling area and move focus there, so a section link lands on it
 * wherever it was. No other section is opened.
 *
 * The page below a late section may be too short for its top to reach the top,
 * so the section's container gets just enough space after it; and what loads
 * above it can still move it, so it is kept in place until that settles or the
 * person scrolls.
 */
export async function revealSection(id: string): Promise<void> {
  settling?.abort();
  const section = document.getElementById(id);
  if (!section) return;
  expand(section);
  // Opened parts render on the next tick; scrolling before would stop short.
  await tick();
  const container = section.parentElement;
  const scroller = scrollParent(section);
  const margin = parseFloat(getComputedStyle(section).scrollMarginTop) || 0;

  const place = () => {
    if (container) container.style.paddingBlockEnd = "";
    const top = scroller === document.documentElement ? 0 : scroller.getBoundingClientRect().top;
    const offset = section.getBoundingClientRect().top - top - margin;
    const room = scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop;
    if (container && offset > room) container.style.paddingBlockEnd = `${offset - room}px`;
    scroller.scrollTop += offset;
  };

  place();
  section.focus({ preventScroll: true });

  const controller = new AbortController();
  settling = controller;
  const observer = new ResizeObserver(place);
  // Anything between the section and the scrolling area growing moves it.
  for (let element: HTMLElement | null = section; element && element !== scroller;) {
    observer.observe(element);
    element = element.parentElement;
  }
  const stop = () => controller.abort();
  for (const event of TAKEOVER_EVENTS) {
    window.addEventListener(event, stop, { once: true, passive: true, signal: controller.signal });
  }
  const timer = setTimeout(stop, SETTLE_MS);
  controller.signal.addEventListener("abort", () => {
    observer.disconnect();
    clearTimeout(timer);
  });
}
