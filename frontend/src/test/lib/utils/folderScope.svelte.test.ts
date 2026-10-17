import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OperationsPopup from "../../../lib/popups/OperationsPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { ApiError } from "../../../lib/rest/transport";
import { assetManagerState } from "../../../lib/stores/assetManagerState.svelte";
import { serverAuditState } from "../../../lib/stores/serverAuditState.svelte";
import { sidebarState } from "../../../lib/stores/sidebarState.svelte";
import { renderWithQueryClient } from "../../helpers/render";

const { getFolderRoots, startScan, startServerAudit, stopScan, stopServerAudit } = vi.hoisted(
  () => ({
    getFolderRoots: vi.fn(),
    startScan: vi.fn(),
    startServerAudit: vi.fn(),
    stopScan: vi.fn(),
    stopServerAudit: vi.fn(),
  }),
);
vi.mock("../../../generated/rest/sdk.gen", () => ({
  getFolderRoots,
  startScan,
  startServerAudit,
  stopScan,
  stopServerAudit,
}));

// The folder-based jobs share one scope: library roots or the sidebar's items.

describe.each([
  {
    name: "asset scan",
    initialTab: "renamer" as const,
    state: assetManagerState,
    start: startScan,
    stop: stopScan,
    startLabel: "Scan",
    selectionKey: "assetPopup_selectedMovieFolders",
    sidebarKey: "assetPopup_useSidebarItems",
  },
  {
    name: "server audit",
    initialTab: "audit" as const,
    state: serverAuditState,
    start: startServerAudit,
    stop: stopServerAudit,
    startLabel: "Audit Server",
    selectionKey: "serverAudit_selectedMovieFolders",
    sidebarKey: "serverAudit_useSidebarItems",
  },
])(
  "folder scope of the $name",
  ({ initialTab, state, start, stop, startLabel, selectionKey, sidebarKey }) => {
    beforeEach(() => {
      vi.resetAllMocks();
      queryClient.clear();
      sidebarState.current = null;
      state.reset();
      getFolderRoots.mockResolvedValue({ data: { movies: ["/movies"], shows: [] } });
      start.mockResolvedValue({ data: { status: "started" } });
      stop.mockResolvedValue({ data: { status: "stopping" } });
    });

    it("keeps failed folder loading distinct from empty folders and permits retry", async () => {
      getFolderRoots.mockRejectedValue(new ApiError("Folders unavailable", 403));
      renderWithQueryClient(OperationsPopup, { initialTab });
      expect(await screen.findByRole("alert")).toHaveTextContent("Folders unavailable");
      expect(screen.queryByText("No media folders found.")).not.toBeInTheDocument();
      expect(screen.getByRole("button", { name: startLabel })).toBeDisabled();
      getFolderRoots.mockResolvedValue({ data: { movies: ["/movies"], shows: [] } });
      await fireEvent.click(screen.getByRole("button", { name: "Retry folders" }));
      expect(await screen.findByRole("checkbox", { name: "/movies" })).toBeVisible();
    });

    it("shows a failed stop request without claiming the job stopped and permits retry", async () => {
      state.handleStarted({});
      stop.mockRejectedValueOnce(new ApiError("Stop unavailable", 503, "stop-request"));
      renderWithQueryClient(OperationsPopup, { initialTab });
      await fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Stop unavailable (Request ID: stop-request)",
      );
      expect(state.running).toBe(true);
      await fireEvent.click(screen.getByRole("button", { name: "Stop" }));
      await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
      expect(stop).toHaveBeenCalledTimes(2);
      expect(state.running).toBe(true);
    });

    it("starts with the persisted folder selection and marks the accepted job as running", async () => {
      localStorage.setItem(selectionKey, JSON.stringify(["/movies"]));
      renderWithQueryClient(OperationsPopup, { initialTab });
      expect(await screen.findByRole("checkbox", { name: "/movies" })).toBeChecked();

      await fireEvent.click(screen.getByRole("button", { name: startLabel }));

      await waitFor(() => {
        expect(start).toHaveBeenCalledOnce();
        expect(state.running).toBe(true);
      });
      expect(start.mock.calls[0]?.[0]).toEqual(
        expect.objectContaining({
          body: expect.objectContaining({ movie_folders: ["/movies"], show_folders: [] }),
        }),
      );
    });

    it("starts with a snapshot of the current sidebar items instead of folders", async () => {
      localStorage.setItem(selectionKey, JSON.stringify(["/movies"]));
      localStorage.setItem(sidebarKey, "true");
      sidebarState.current = { type: "movie", itemIds: [4, 9] };
      renderWithQueryClient(OperationsPopup, { initialTab });
      expect(
        await screen.findByRole("checkbox", { name: "Current sidebar items 2 movies" }),
      ).toBeChecked();
      expect(await screen.findByRole("checkbox", { name: "/movies" })).not.toBeChecked();

      await fireEvent.click(screen.getByRole("button", { name: startLabel }));

      await waitFor(() => expect(start).toHaveBeenCalledOnce());
      const body = (start.mock.calls[0]?.[0] as { body: Record<string, unknown> }).body;
      expect(body.item_ids).toEqual([4, 9]);
      expect(body).not.toHaveProperty("movie_folders");
    });

    it("returns to folder selection when a folder is chosen", async () => {
      localStorage.setItem(sidebarKey, "true");
      sidebarState.current = { type: "movie", itemIds: [4] };
      renderWithQueryClient(OperationsPopup, { initialTab });
      const sidebarOption = await screen.findByRole("checkbox", { name: /Current sidebar items/ });
      expect(sidebarOption).toBeChecked();

      await fireEvent.click(await screen.findByRole("checkbox", { name: "/movies" }));

      expect(sidebarOption).not.toBeChecked();
      expect(screen.getByRole("checkbox", { name: "/movies" })).toBeChecked();
    });
  },
);
