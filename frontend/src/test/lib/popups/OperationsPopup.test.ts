import { fireEvent, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OperationsPopup from "../../../lib/popups/OperationsPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { assetManagerState } from "../../../lib/stores/assetManagerState.svelte";
import { matchState } from "../../../lib/stores/matchState.svelte";
import { serverAuditState } from "../../../lib/stores/serverAuditState.svelte";
import { syncState } from "../../../lib/stores/jobStates.svelte";
import { themeJobState } from "../../../lib/stores/bulkJobState.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { renderWithQueryClient } from "../../helpers/render";

vi.mock("../../../generated/rest/sdk.gen", () => ({
  getFolderRoots: vi.fn(() => Promise.resolve({ data: { movies: [], shows: [] } })),
  getLibraries: vi.fn(() => Promise.resolve({ data: [] })),
  getPublicDatasetStatus: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
  listBulkAssetsSchedules: vi.fn(() => Promise.resolve({ data: [] })),
  listServerLibraries: vi.fn(() => Promise.resolve({ data: [] })),
  listSyncSchedules: vi.fn(() => Promise.resolve({ data: [] })),
}));

describe("OperationsPopup tab navigation", () => {
  it("keeps each tab's purpose behind the help button", async () => {
    renderWithQueryClient(OperationsPopup, { initialTab: "assets" });

    const help = screen.getByRole("button", { name: "What does this do?" });
    expect(help).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText(/Finds and downloads art/)).not.toBeInTheDocument();

    await fireEvent.click(help);
    expect(help).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText(/Finds and downloads art/)).toBeInTheDocument();

    await fireEvent.click(screen.getByRole("tab", { name: /Sync/i }));
    expect(screen.getByText(/Imports your media server's libraries/)).toBeInTheDocument();

    await fireEvent.click(help);
    expect(screen.queryByText(/Imports your media server's libraries/)).not.toBeInTheDocument();
  });

  beforeEach(() => {
    queryClient.clear();
    localStorage.clear();
    uiState.openOperations("assets");
    matchState.reset();
    themeJobState.reset();
    syncState.reset();
    assetManagerState.reset();
    serverAuditState.reset();
  });

  it("renders with the initial tab and allows switching between all tabs", async () => {
    renderWithQueryClient(OperationsPopup, { initialTab: "assets" });

    const assetsTab = screen.getByRole("tab", { name: /Assets/i });
    const syncTab = screen.getByRole("tab", { name: /Sync/i });
    const renamerTab = screen.getByRole("tab", { name: /Renamer/i });
    const auditTab = screen.getByRole("tab", { name: /Server Audit/i });

    expect(assetsTab).toHaveAttribute("aria-selected", "true");
    expect(syncTab).toHaveAttribute("aria-selected", "false");
    expect(renamerTab).toHaveAttribute("aria-selected", "false");
    expect(auditTab).toHaveAttribute("aria-selected", "false");

    // Switch to Sync
    await fireEvent.click(syncTab);
    expect(syncTab).toHaveAttribute("aria-selected", "true");
    expect(assetsTab).toHaveAttribute("aria-selected", "false");
    expect(uiState.operationsTab).toBe("sync");

    // Switch to Renamer
    await fireEvent.click(renamerTab);
    expect(renamerTab).toHaveAttribute("aria-selected", "true");
    expect(syncTab).toHaveAttribute("aria-selected", "false");
    expect(uiState.operationsTab).toBe("renamer");

    // Switch to Server Audit
    await fireEvent.click(auditTab);
    expect(auditTab).toHaveAttribute("aria-selected", "true");
    expect(renamerTab).toHaveAttribute("aria-selected", "false");
    expect(uiState.operationsTab).toBe("audit");

    // Switch back to Assets
    await fireEvent.click(assetsTab);
    expect(assetsTab).toHaveAttribute("aria-selected", "true");
    expect(auditTab).toHaveAttribute("aria-selected", "false");
    expect(uiState.operationsTab).toBe("assets");
  });

  it("shows running spinner badges on tab buttons when jobs are active", async () => {
    matchState.handleStarted({});
    syncState.handleStarted({});

    renderWithQueryClient(OperationsPopup, { initialTab: "renamer" });

    const assetsTab = screen.getByRole("tab", { name: /Assets/i });
    const syncTab = screen.getByRole("tab", { name: /Sync/i });
    const renamerTab = screen.getByRole("tab", { name: /Renamer/i });

    expect(assetsTab.querySelector(".tab-badge")).toBeInTheDocument();
    expect(syncTab.querySelector(".tab-badge")).toBeInTheDocument();
    expect(renamerTab.querySelector(".tab-badge")).not.toBeInTheDocument();
  });
});
