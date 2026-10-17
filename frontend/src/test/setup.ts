import "@testing-library/jest-dom/vitest";
import { cleanup, render } from "@testing-library/svelte";
import { afterEach, beforeEach, vi } from "vitest";
import NotificationHost from "../lib/components/NotificationHost.svelte";
import { notificationState } from "../lib/stores/notificationState.svelte";

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
beforeEach(() => {
  render(NotificationHost);
});

afterEach(() => {
  cleanup();
  notificationState.settleConfirm(false);
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
