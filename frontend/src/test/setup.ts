import "@testing-library/jest-dom/vitest";
import { cleanup, render, setup } from "@testing-library/svelte";
import { afterEach, beforeEach, expect, vi } from "vitest";
import NotificationHost from "../lib/components/NotificationHost.svelte";
import { notificationState } from "../lib/stores/notificationState.svelte";
import { criteriaClipboard } from "../lib/stores/criteriaClipboard.svelte";
import { sidebarState } from "../lib/stores/sidebarState.svelte";

// jsdom doesn't implement IntersectionObserver. sv-router uses it internally
// to preload routes for links that scroll into view, regardless of whether
// any component actually renders an <a data-preload> element in a given
// test, so it needs a stub even for tests that never touch routing directly.
class MockIntersectionObserver implements IntersectionObserver {
  readonly root: Element | Document | null = null;
  readonly rootMargin: string = "";
  readonly scrollMargin: string = "";
  readonly thresholds: ReadonlyArray<number> = [];
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
  takeRecords(): IntersectionObserverEntry[] {
    return [];
  }
}
globalThis.IntersectionObserver = MockIntersectionObserver;

// jsdom doesn't implement ResizeObserver, which Svelte's element dimension
// bindings use. Sizes are always zero without a layout engine, so a stub that
// never reports is all a test can observe anyway.
class MockResizeObserver implements ResizeObserver {
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}
globalThis.ResizeObserver = MockResizeObserver;

// jsdom has no layout engine, so window.scrollTo() is a "Not implemented"
// stub that logs to stderr. sv-router calls it on every navigation, which
// buries real output under the notice - a no-op keeps the run readable.
window.scrollTo = () => {};
Element.prototype.scrollIntoView = () => {};

// jsdom doesn't implement matchMedia, which the "system" theme and Svelte's
// MediaQuery read. Tests run as a device that prefers dark mode and matches
// no other query.
window.matchMedia = (query: string): MediaQueryList => ({
  matches: query === "(prefers-color-scheme: dark)",
  media: query,
  onchange: null,
  addEventListener: () => {},
  removeEventListener: () => {},
  addListener: () => {},
  removeListener: () => {},
  dispatchEvent: () => false,
});

// jsdom exposes dialog elements but not their modal lifecycle. Browser tests
// cover native focus containment, background inertness, and Escape handling.
HTMLDialogElement.prototype.showModal = function () {
  this.setAttribute("open", "");
};
HTMLDialogElement.prototype.close = function () {
  this.removeAttribute("open");
};

// The app root hosts toasts and confirmations; components under test raise
// them through the shared notification state, so every test gets a host too.
beforeEach(async () => {
  await setup();
  render(NotificationHost);
});

// Tests never reach the network: a request a test does not stub fails it.
// unstubGlobals restores these after each test, so a test's own stub wins.
beforeEach(() => {
  vi.stubGlobal("fetch", (input: RequestInfo | URL) => {
    throw new Error(`Unstubbed fetch: ${String(input)}`);
  });
  vi.stubGlobal(
    "WebSocket",
    class {
      constructor(url: string | URL) {
        throw new Error(`Unstubbed WebSocket: ${String(url)}`);
      }
    },
  );
});

// Svelte's runtime warns on the console of what is likely a bug, such as
// reading a derived of an ended component; a test that causes one fails.
const svelteWarnings: string[] = [];
const warn = console.warn.bind(console);
beforeEach(() => {
  svelteWarnings.length = 0;
  vi.spyOn(console, "warn").mockImplementation((...args: unknown[]) => {
    const message = args.map(String).join(" ");
    if (message.includes("[svelte]")) svelteWarnings.push(message);
    else warn(...args);
  });
});

afterEach(() => {
  cleanup();
  expect(svelteWarnings, "Svelte warned").toEqual([]);
  notificationState.settleConfirm(null);
  // Auto-advance keeps its walk between selections, never between tests.
  sidebarState.walk = null;
  criteriaClipboard.copied = null;
  for (const toast of notificationState.toasts) notificationState.dismiss(toast.id);
  localStorage.clear();
  sessionStorage.clear();
  document.cookie.split(";").forEach((cookie) => {
    const name = cookie.split("=")[0]?.trim();
    if (name) {
      document.cookie = `${name}=; Max-Age=0; path=/`;
    }
  });
  vi.useRealTimers();
});
