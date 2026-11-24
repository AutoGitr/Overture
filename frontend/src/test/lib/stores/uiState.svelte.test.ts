import { describe, expect, it, vi } from "vitest";

describe("uiState popups", () => {
  it("never reflects the open popup in the URL (path, hash, or search params)", async () => {
    vi.resetModules();

    const { uiState } = await import("../../../lib/stores/uiState.svelte");
    // Importing uiState pulls in the router, which normalizes the URL once
    // on load (e.g. to a default route) - capture the baseline *after*
    // that settles, so we're only asserting popups themselves never touch it.
    const originalHref = window.location.href;

    uiState.openPopupByName("settings");
    expect(uiState.openPopup).toBe("settings");
    // Opening/closing a popup is pure in-memory UI state - it must never be
    // written to the address bar, so it can't be linked, bookmarked, or
    // recreated by browser back/forward navigation.
    expect(window.location.href).toBe(originalHref);

    uiState.openPopupByName("operations");
    expect(uiState.openPopup).toBe("operations");
    expect(window.location.href).toBe(originalHref);

    uiState.closePopup();
    expect(uiState.openPopup).toBeNull();
    expect(window.location.href).toBe(originalHref);
  });
});
