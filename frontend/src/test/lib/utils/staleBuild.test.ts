import { describe, expect, it, vi } from "vitest";
import { reloadOnStaleBuild } from "../../../lib/utils/staleBuild";

function staleTab() {
  const reload = vi.fn();
  const target = new EventTarget() as Window;
  Object.defineProperty(target, "location", { value: { reload } });
  return { target, reload };
}

function failImport(target: Window): Event {
  const event = new Event("vite:preloadError", { cancelable: true });
  target.dispatchEvent(event);
  return event;
}

describe("reloadOnStaleBuild", () => {
  it("reloads a tab whose build lost a file, once per build", () => {
    sessionStorage.clear();
    const old = staleTab();
    reloadOnStaleBuild(old.target, "/assets/index-old.js");

    const first = failImport(old.target);
    expect(first.defaultPrevented).toBe(true);
    expect(old.reload).toHaveBeenCalledOnce();

    // The same build failing again shows its error rather than reloading.
    const again = failImport(old.target);
    expect(again.defaultPrevented).toBe(false);
    expect(old.reload).toHaveBeenCalledOnce();

    // A newer build gets its own reload.
    const current = staleTab();
    reloadOnStaleBuild(current.target, "/assets/index-new.js");
    failImport(current.target);
    expect(current.reload).toHaveBeenCalledOnce();
  });
});
