import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OperationsPopup from "../../../../lib/popups/OperationsPopup.svelte";
import { queryClient } from "../../../../lib/rest/queryClient";
import { ApiError } from "../../../../lib/rest/transport";
import { sidebarState } from "../../../../lib/stores/sidebarState.svelte";
import { syncState } from "../../../../lib/stores/jobStates.svelte";
import { matchState, themeJobState } from "../../../../lib/stores/bulkJobState.svelte";
import { downloadState } from "../../../../lib/stores/downloadState.svelte";
import { settingsState } from "../../../../lib/stores/settingsState.svelte";
import { uiState } from "../../../../lib/stores/uiState.svelte";
import { renderWithQueryClient } from "../../../helpers/render";
import { appSettings, bulkAssetsSchedule } from "../../../helpers/fixtures";

const startBulkAssets = vi.hoisted(() => vi.fn());
const stopBulkAssets = vi.hoisted(() => vi.fn());
const createBulkAssetsSchedule = vi.hoisted(() => vi.fn());
const updateBulkAssetsSchedule = vi.hoisted(() => vi.fn());
const deleteBulkAssetsSchedule = vi.hoisted(() => vi.fn());
const runBulkAssetsSchedule = vi.hoisted(() => vi.fn());

const SAVED_SCHEDULE = bulkAssetsSchedule();

const schedules = vi.hoisted(() => ({ value: [] as unknown[] }));

const reads = vi.hoisted(() => ({
  listBulkAssetsSchedules: vi.fn(() => Promise.resolve({ data: schedules.value })),
  getLibraries: vi.fn((options: { query?: { media_type?: string } }) =>
    Promise.resolve({
      data: options.query?.media_type === "movie" ? [{ id: "1", title: "Movies", count: 1 }] : [],
    }),
  ),
  getPublicDatasetStatus: vi.fn(() => Promise.resolve({ data: { enabled: true } })),
  clearJobSnapshot: vi.fn(() => Promise.resolve({ data: { status: "cleared" } })),
  listCollectionGroups: vi.fn((options: { query?: { media_type?: string } }) =>
    Promise.resolve({ data: options.query?.media_type === "movie" ? ["Sagas", "Studios"] : [] }),
  ),
}));

vi.mock("../../../../generated/rest/sdk.gen", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../../generated/rest/sdk.gen")>()),
  ...reads,
}));

vi.mock("../../../../generated/rest/@tanstack/svelte-query.gen", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("../../../../generated/rest/@tanstack/svelte-query.gen")>();
  return {
    ...original,
    createBulkAssetsScheduleMutation: () => ({
      mutationFn: ({ body }: { body: unknown }) => createBulkAssetsSchedule(body),
    }),
    deleteBulkAssetsScheduleMutation: () => ({
      mutationFn: ({ path }: { path: { schedule_id: number } }) =>
        deleteBulkAssetsSchedule(path.schedule_id),
    }),
    runBulkAssetsScheduleMutation: () => ({
      mutationFn: ({ path }: { path: { schedule_id: number } }) =>
        runBulkAssetsSchedule(path.schedule_id),
    }),
    startBulkAssetsMutation: () => ({
      mutationFn: ({ body }: { body: unknown }) => startBulkAssets(body),
    }),
    stopBulkAssetsMutation: () => ({
      mutationFn: (variables?: { body?: unknown }) => stopBulkAssets(variables),
    }),
    updateBulkAssetsScheduleMutation: () => ({
      mutationFn: ({ body, path }: { body: unknown; path: { schedule_id: number } }) =>
        updateBulkAssetsSchedule(path.schedule_id, body),
    }),
  };
});

/** The visible operations panel; the other tabs stay mounted but hidden. */
function assetsPanel() {
  return within(screen.getByRole("tabpanel"));
}

describe("AssetsPopup", () => {
  beforeEach(() => {
    queryClient.clear();
    localStorage.clear();
    sidebarState.current = null;
    uiState.openOperations("assets");
    matchState.reset();
    themeJobState.reset();
    syncState.reset();
    downloadState.replaceSnapshot([]);
    startBulkAssets.mockResolvedValue({ art: "started", themes: "started" });
    stopBulkAssets.mockResolvedValue({ status: "stopping" });
    createBulkAssetsSchedule.mockResolvedValue({});
    updateBulkAssetsSchedule.mockResolvedValue({});
    deleteBulkAssetsSchedule.mockResolvedValue({ status: "deleted" });
    runBulkAssetsSchedule.mockResolvedValue({ status: "queued" });
    schedules.value = [];
    settingsState.reset();
  });

  it("runs art and themes over chosen collection groups", async () => {
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    renderWithQueryClient(OperationsPopup);
    await fireEvent.click(assetsPanel().getByRole("radio", { name: "Collections" }));
    expect(assetsPanel().getByText(/Every collection/)).toBeInTheDocument();
    await fireEvent.click(await assetsPanel().findByRole("checkbox", { name: "Sagas" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Poster" }));
    await fireEvent.click(screen.getByRole("button", { name: "Run Now" }));

    await waitFor(() =>
      expect(startBulkAssets).toHaveBeenCalledWith(
        expect.objectContaining({
          library_ids: [],
          collection_groups: ["Sagas"],
          art: expect.objectContaining({ art_types: ["poster"] }),
        }),
      ),
    );
  });

  it("shows independent downloads alongside the bulk configuration", () => {
    downloadState.trackQueuedCollectionJob({
      jobId: "independent-collection",
      collectionId: 1,
      title: "Movies collection",
    });
    renderWithQueryClient(OperationsPopup);

    expect(assetsPanel().getByRole("region", { name: "Theme downloads" })).toHaveTextContent(
      "Movies collection",
    );
    expect(screen.getByRole("button", { name: "Run Now" })).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: /Assets/i }).querySelector(".tab-badge"),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();
    expect(stopBulkAssets).not.toHaveBeenCalled();
  });

  it("runs the complete current sidebar snapshot instead of persisted libraries", async () => {
    localStorage.setItem("assetsPopup_selectedLibraries", JSON.stringify(["1"]));
    sidebarState.current = { type: "movie", itemIds: [7, 12, 25] };
    renderWithQueryClient(OperationsPopup);
    await screen.findByRole("checkbox", { name: /Movies/ });
    await fireEvent.click(screen.getByRole("checkbox", { name: /Current sidebar items/ }));
    expect(assetsPanel().getByText("3 movies")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: /Movies/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Season Poster" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Poster" }));
    expect(screen.queryByPlaceholderText("Nightly assets")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save Schedule" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("button", { name: "Run Now" }));
    await waitFor(() =>
      expect(startBulkAssets).toHaveBeenCalledWith(
        expect.objectContaining({
          library_ids: [],
          item_ids: [7, 12, 25],
          include_unmonitored: false,
          overwrite_existing: false,
        }),
      ),
    );
    sidebarState.current.itemIds = [99];
    expect(startBulkAssets.mock.calls[0]?.[0].item_ids).toEqual([7, 12, 25]);
  });

  it("remembers sidebar scope after reopening and clearing results, using fresh item IDs", async () => {
    startBulkAssets.mockResolvedValue({ art: "not_requested", themes: "started" });
    localStorage.setItem("assetsPopup_selectedLibraries", JSON.stringify(["1"]));
    sidebarState.current = { type: "movie", itemIds: [7, 12] };
    const popup = renderWithQueryClient(OperationsPopup);
    await screen.findByRole("checkbox", { name: /Movies/ });
    await fireEvent.click(screen.getByRole("checkbox", { name: /Current sidebar items/ }));
    await fireEvent.click(
      within(screen.getByRole("region", { name: "Art" })).getByRole("checkbox", {
        name: "Enabled",
      }),
    );
    await fireEvent.click(screen.getByRole("button", { name: "Run Now" }));
    await waitFor(() => expect(themeJobState.running).toBe(true));
    themeJobState.handleCompleted({ total: 2, done: 2, finished_at: "2026-09-09T12:00:00Z" });
    popup.unmount();

    sidebarState.current = { type: "movie", itemIds: [25] };
    renderWithQueryClient(OperationsPopup);
    await fireEvent.click(await screen.findByRole("button", { name: "Clear Results" }));
    const sidebarCheckbox = await screen.findByRole("checkbox", { name: /Current sidebar items/ });
    expect(sidebarCheckbox).toBeChecked();
    expect(sidebarCheckbox).toHaveAccessibleName("Current sidebar items 1 movie");
    expect(screen.getByRole("checkbox", { name: /Movies/ })).not.toBeChecked();
    await fireEvent.click(screen.getByRole("button", { name: "Run Now" }));
    await waitFor(() =>
      expect(startBulkAssets).toHaveBeenLastCalledWith(
        expect.objectContaining({ library_ids: [], item_ids: [25] }),
      ),
    );
  });

  it("supports show artwork and switches back to a clicked library", async () => {
    localStorage.setItem("assetsPopup_selectedLibraries", JSON.stringify(["1"]));
    sidebarState.current = { type: "show", itemIds: [8] };
    renderWithQueryClient(OperationsPopup);
    await screen.findByRole("checkbox", { name: /Movies/ });
    await fireEvent.click(screen.getByRole("checkbox", { name: /Current sidebar items/ }));
    expect(assetsPanel().getByText("1 show")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Season Poster" }));
    expect(screen.getByRole("checkbox", { name: "Season Poster" })).toBeChecked();
    await fireEvent.click(screen.getByRole("checkbox", { name: /Movies/ }));
    expect(screen.getByRole("checkbox", { name: /Movies/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /Current sidebar items/ })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Season Poster" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Season Poster" })).toBeDisabled();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Poster" }));
    await fireEvent.click(screen.getByRole("button", { name: "Run Now" }));
    await waitFor(() =>
      expect(startBulkAssets).toHaveBeenCalledWith(expect.objectContaining({ library_ids: ["1"] })),
    );
    expect(startBulkAssets.mock.calls[0]?.[0]).not.toHaveProperty("item_ids");
    expect(localStorage.getItem("assetsPopup_useSidebarItems")).toBe("false");
  });

  it("prevents empty or unavailable sidebar results from running", async () => {
    sidebarState.current = { type: "movie", itemIds: [7] };
    renderWithQueryClient(OperationsPopup);
    await screen.findByRole("checkbox", { name: /Movies/ });
    await fireEvent.click(screen.getByRole("checkbox", { name: /Current sidebar items/ }));
    await fireEvent.click(
      within(screen.getByRole("region", { name: "Art" })).getByRole("checkbox", {
        name: "Enabled",
      }),
    );
    expect(screen.getByRole("button", { name: "Run Now" })).toBeEnabled();
    sidebarState.current = { type: "movie", itemIds: [] };
    await waitFor(() => expect(screen.getByRole("button", { name: "Run Now" })).toBeDisabled());
    expect(assetsPanel().getByText("0 movies")).toBeInTheDocument();
    sidebarState.current = null;
    await waitFor(() => expect(assetsPanel().queryByText("0 movies")).not.toBeInTheDocument());
    expect(screen.getByRole("button", { name: "Run Now" })).toBeDisabled();
    expect(startBulkAssets).not.toHaveBeenCalled();
  });

  it("shows a failed stop request while retaining the running job for retry", async () => {
    matchState.handleStarted({});
    stopBulkAssets.mockRejectedValueOnce(new ApiError("Stop unavailable", 503));
    renderWithQueryClient(OperationsPopup);
    await fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Stop unavailable");
    expect(matchState.running).toBe(true);
    await fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
    expect(stopBulkAssets).toHaveBeenCalledTimes(2);
  });

  it("starts selected art and theme workflows with shared skip settings", async () => {
    renderWithQueryClient(OperationsPopup);

    await screen.findByRole("checkbox", { name: /Movies/ });
    await fireEvent.click(screen.getByRole("checkbox", { name: "Select All" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Poster" }));

    const skipInput = screen.getByRole("spinbutton");
    await fireEvent.input(skipInput, { target: { value: "2" } });
    await fireEvent.change(screen.getByRole("combobox"), {
      target: { value: "days" },
    });
    await fireEvent.click(screen.getByText("Run Now"));

    await waitFor(() => {
      expect(startBulkAssets).toHaveBeenCalledWith(
        expect.objectContaining({
          library_ids: ["1"],
          skip_recent_val: 2,
          skip_recent_unit: "days",
          include_unmonitored: false,
          overwrite_existing: false,
          art: expect.objectContaining({
            art_types: ["poster"],
            source_order: ["overturedb", "local_art_matching"],
          }),
          themes: expect.objectContaining({
            source_order: ["overturedb", "themerrdb", "youtube_search"],
          }),
        }),
      );
    });
  });

  it("uses current assetsPopup settings for the unified assets request", async () => {
    localStorage.setItem("assetsPopup_artTypes", JSON.stringify(["poster"]));
    localStorage.setItem("assetsPopup_selectedLibraries", JSON.stringify(["1"]));
    localStorage.setItem("assetsPopup_selectedArtSources", JSON.stringify(["local_art_matching"]));
    localStorage.setItem(
      "assetsPopup_artSourceOrder",
      JSON.stringify(["local_art_matching", "overturedb"]),
    );
    localStorage.setItem("assetsPopup_threshold", "7");

    renderWithQueryClient(OperationsPopup);

    await screen.findByRole("checkbox", { name: /Movies/ });
    await fireEvent.click(screen.getByText("Run Now"));

    await waitFor(() => {
      expect(startBulkAssets).toHaveBeenCalledWith(
        expect.objectContaining({
          library_ids: ["1"],
          art: expect.objectContaining({
            art_types: ["poster"],
            source_order: ["local_art_matching"],
            threshold: 7,
          }),
          themes: expect.objectContaining({
            source_order: ["overturedb", "themerrdb", "youtube_search"],
          }),
        }),
      );
    });
  });

  it("stops only the running asset workflow", async () => {
    matchState.handleStarted({ total: 1 });
    renderWithQueryClient(OperationsPopup);

    await screen.findByText("Running");
    await fireEvent.click(screen.getByText("Stop"));

    await waitFor(() => {
      expect(stopBulkAssets).toHaveBeenCalledWith({
        body: { art: true, themes: false },
      });
    });
  });

  it("saves the current configuration as a named schedule", async () => {
    renderWithQueryClient(OperationsPopup);

    await screen.findByRole("checkbox", { name: /Movies/ });
    await fireEvent.click(screen.getByRole("checkbox", { name: "Select All" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Poster" }));
    await fireEvent.input(screen.getByPlaceholderText("Nightly assets"), {
      target: { value: "Nightly" },
    });
    await fireEvent.click(screen.getByRole("checkbox", { name: "Include unmonitored items" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Replace existing" }));
    await fireEvent.input(assetsPanel().getByPlaceholderText("0 3 * * *"), {
      target: { value: "0 5 * * *" },
    });

    await fireEvent.click(screen.getByText("Save Schedule"));

    await waitFor(() => {
      expect(createBulkAssetsSchedule).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Nightly",
          enabled: true,
          cron_expression: "0 5 * * *",
          config: expect.objectContaining({
            library_ids: ["1"],
            include_unmonitored: true,
            overwrite_existing: true,
          }),
        }),
      );
    });
  });

  it("keeps the save button disabled until the schedule is runnable", async () => {
    renderWithQueryClient(OperationsPopup);
    await screen.findByRole("checkbox", { name: /Movies/ });

    const save = screen.getByText("Save Schedule");
    expect(save).toBeDisabled();

    await fireEvent.click(screen.getByRole("checkbox", { name: "Select All" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Poster" }));
    expect(save).toBeDisabled();

    await fireEvent.input(screen.getByPlaceholderText("Nightly assets"), {
      target: { value: "Nightly" },
    });
    await waitFor(() => expect(save).toBeEnabled());
  });

  it("loads a saved schedule back into the configuration form", async () => {
    schedules.value = [SAVED_SCHEDULE];
    renderWithQueryClient(OperationsPopup);

    await fireEvent.click(await screen.findByLabelText("Edit schedule"));

    await waitFor(() => {
      expect(screen.getByPlaceholderText("Nightly assets")).toHaveValue("Nightly");
      expect(assetsPanel().getByPlaceholderText("0 3 * * *")).toHaveValue("0 4 * * *");
      expect(screen.getByRole("spinbutton")).toHaveValue(4);
    });
    // The saved config disabled themes, so its card is gone from the form.
    expect(screen.queryByText(/Theme Search Query/)).not.toBeInTheDocument();
    expect(screen.getByText("Update Schedule")).toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Include unmonitored items" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Replace existing" })).toBeChecked();
    expect(screen.getByText("Replace existing: Yes")).toBeInTheDocument();
    await fireEvent.click(screen.getByText("Update Schedule"));
    await waitFor(() =>
      expect(updateBulkAssetsSchedule).toHaveBeenCalledWith(
        5,
        expect.objectContaining({
          config: expect.objectContaining({
            include_unmonitored: true,
            overwrite_existing: true,
          }),
        }),
      ),
    );
  });

  it("persists overrides and sends them with a sidebar run", async () => {
    sidebarState.current = { type: "movie", itemIds: [7] };
    const popup = renderWithQueryClient(OperationsPopup);
    await screen.findByRole("checkbox", { name: /Movies/ });
    await fireEvent.click(screen.getByRole("checkbox", { name: /Current sidebar items/ }));
    await fireEvent.click(
      within(screen.getByRole("region", { name: "Art" })).getByRole("checkbox", {
        name: "Enabled",
      }),
    );
    await fireEvent.click(screen.getByRole("checkbox", { name: "Include unmonitored items" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Replace existing" }));
    await waitFor(() => expect(localStorage.getItem("assetsPopup_overwriteExisting")).toBe("true"));
    popup.unmount();
    renderWithQueryClient(OperationsPopup);
    expect(
      await screen.findByRole("checkbox", { name: "Include unmonitored items" }),
    ).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Replace existing" })).toBeChecked();
    await waitFor(() => expect(screen.getByRole("button", { name: "Run Now" })).toBeEnabled());
    await fireEvent.click(screen.getByRole("button", { name: "Run Now" }));
    await waitFor(() =>
      expect(startBulkAssets).toHaveBeenCalledWith(
        expect.objectContaining({
          item_ids: [7],
          include_unmonitored: true,
          overwrite_existing: true,
        }),
      ),
    );
  });

  it("runs a saved schedule on demand", async () => {
    schedules.value = [SAVED_SCHEDULE];
    renderWithQueryClient(OperationsPopup);

    await fireEvent.click(await screen.findByLabelText("Run schedule"));

    await waitFor(() => expect(runBulkAssetsSchedule).toHaveBeenCalledWith(5));
  });

  it("preserves settings when library loading fails and supports retry", async () => {
    localStorage.setItem("assetsPopup_selectedLibraries", '["1"]');
    localStorage.setItem("assetsPopup_artTypes", '["poster"]');
    reads.getLibraries.mockRejectedValueOnce(new Error("Libraries unavailable"));
    renderWithQueryClient(OperationsPopup);
    expect(await screen.findByRole("alert")).toHaveTextContent("Libraries unavailable");
    expect(screen.getByRole("button", { name: "Run Now" })).toBeDisabled();
    expect(localStorage.getItem("assetsPopup_selectedLibraries")).toBe('["1"]');
    expect(localStorage.getItem("assetsPopup_artTypes")).toBe('["poster"]');
    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("checkbox", { name: /Movies/ })).toBeChecked();
    expect(screen.getByRole("button", { name: "Run Now" })).toBeEnabled();
  });

  it("preserves preferred sources while dataset status is unavailable", async () => {
    localStorage.setItem("assetsPopup_selectedArtSources", '["overturedb"]');
    reads.getPublicDatasetStatus.mockRejectedValueOnce(new Error("Dataset unavailable"));
    renderWithQueryClient(OperationsPopup);
    await assetsPanel().findByText("Dataset unavailable");
    await screen.findByRole("checkbox", { name: /Movies/ });
    expect(localStorage.getItem("assetsPopup_selectedArtSources")).toBe('["overturedb"]');
  });

  it("shows the stop button immediately upon starting without getting stuck on starting", async () => {
    localStorage.setItem("assetsPopup_selectedLibraries", '["1"]');
    localStorage.setItem("assetsPopup_artTypes", '["poster"]');
    renderWithQueryClient(OperationsPopup);

    await screen.findByRole("checkbox", { name: /Movies/ });
    const runButton = screen.getByRole("button", { name: "Run Now" });
    await fireEvent.click(runButton);

    await waitFor(() => expect(startBulkAssets).toHaveBeenCalled());
    const stopButton = await screen.findByRole("button", { name: "Stop" });
    expect(stopButton).toBeInTheDocument();
    expect(stopButton).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Starting..." })).not.toBeInTheDocument();
  });

  it("keeps the form in place when the server refuses a run, without flashing results", async () => {
    localStorage.setItem("assetsPopup_selectedLibraries", '["1"]');
    localStorage.setItem("assetsPopup_artTypes", '["poster"]');
    startBulkAssets.mockRejectedValueOnce(new ApiError("Wait for full sync to finish", 409));
    renderWithQueryClient(OperationsPopup);
    const library = await screen.findByRole("checkbox", { name: /Movies/ });
    const body = document.querySelector(".popup-body") as HTMLElement;

    // Record every frame-visible change the start attempt makes to the popup.
    const changes: string[] = [];
    const observer = new MutationObserver((records) => {
      for (const record of records) {
        if (record.type === "attributes" && body.classList.contains("fill")) changes.push("fill");
        for (const node of record.removedNodes) if (node.contains(library)) changes.push("form");
        for (const node of record.addedNodes) {
          if (/Starting|Stop|Clear Results/.test(node.textContent ?? "")) changes.push("results");
        }
      }
    });
    observer.observe(body.closest("dialog") as HTMLElement, {
      subtree: true,
      childList: true,
      attributes: true,
      attributeFilter: ["class"],
    });

    await fireEvent.click(screen.getByRole("button", { name: "Run Now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Wait for full sync to finish");
    observer.disconnect();

    expect(changes).toEqual([]);
    expect(library).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Now" })).toBeEnabled();
  });

  it("holds Run Now while a full sync runs and says why", async () => {
    localStorage.setItem("assetsPopup_selectedLibraries", '["1"]');
    localStorage.setItem("assetsPopup_artTypes", '["poster"]');
    syncState.markStartAccepted();
    renderWithQueryClient(OperationsPopup);
    await screen.findByRole("checkbox", { name: /Movies/ });

    expect(screen.getByRole("button", { name: "Run Now" })).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Wait for the full sync to finish.");

    syncState.handleCompleted({});
    await waitFor(() => expect(screen.getByRole("button", { name: "Run Now" })).toBeEnabled());
    expect(screen.queryByText("Wait for the full sync to finish.")).not.toBeInTheDocument();
  });

  it("keeps showing Stopping from the accepted stop until the run ends", async () => {
    matchState.handleStarted({ total: 1 });
    renderWithQueryClient(OperationsPopup);
    await fireEvent.click(await screen.findByRole("button", { name: "Stop" }));
    await waitFor(() => expect(stopBulkAssets).toHaveBeenCalled());
    const stopping = await screen.findByRole("button", { name: "Stopping..." });
    // The stop request has settled; only the end of the run clears "Stopping".
    await waitFor(() => expect(queryClient.isMutating()).toBe(0));
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(stopping).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Stop" })).not.toBeInTheDocument();

    matchState.handleStopped({});
    expect(await screen.findByRole("button", { name: "Clear Results" })).toBeEnabled();
  });

  it("closes cleanly and returns focus to the control that opened it", async () => {
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    const view = renderWithQueryClient(OperationsPopup);
    await screen.findByRole("checkbox", { name: /Movies/ });
    await view.unmount();
    expect(opener).toHaveFocus();
    opener.remove();
  });
});
