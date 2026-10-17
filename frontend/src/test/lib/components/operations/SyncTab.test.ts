import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OperationsPopup from "../../../../lib/popups/OperationsPopup.svelte";
import { invalidateSchedules } from "../../../../lib/rest/cache";
import { queryClient } from "../../../../lib/rest/queryClient";
import { matchState } from "../../../../lib/stores/matchState.svelte";
import { settingsState } from "../../../../lib/stores/settingsState.svelte";
import { syncState } from "../../../../lib/stores/jobStates.svelte";
import { renderWithQueryClient } from "../../../helpers/render";

const libraries = vi.hoisted(() => vi.fn());
const schedules = vi.hoisted(() => vi.fn());
const datasetStatus = vi.hoisted(() => vi.fn());
const run = vi.hoisted(() => vi.fn());
const createSchedule = vi.hoisted(() => vi.fn());
const updateSchedule = vi.hoisted(() => vi.fn());
const runSchedule = vi.hoisted(() => vi.fn());
const defaultDatasetStatus = vi.hoisted(() => ({
  enabled: false,
  repo_url: "https://example.test/repo",
  catalog_url: "https://example.test/catalog.jsonl.gz",
  last_synced_at: null,
  last_status: "success" as const,
  last_stats: null,
  next_run: null,
  timezone: "UTC",
}));

vi.mock("../../../../generated/rest/sdk.gen", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../../../generated/rest/sdk.gen")>()),
  listServerLibraries: async () => ({ data: await libraries() }),
  listSyncSchedules: async () => ({ data: await schedules() }),
  getPublicDatasetStatus: async () => ({ data: await datasetStatus() }),
}));
vi.mock("../../../../generated/rest/@tanstack/svelte-query.gen", async (importOriginal) => ({
  ...(await importOriginal<
    typeof import("../../../../generated/rest/@tanstack/svelte-query.gen")
  >()),
  runSyncMutation: () => ({ mutationFn: run }),
  createSyncScheduleMutation: () => ({ mutationFn: createSchedule }),
  updateSyncScheduleMutation: () => ({ mutationFn: updateSchedule }),
  runSyncScheduleMutation: () => ({ mutationFn: runSchedule }),
}));

const SAVED_POLL = {
  id: 7,
  kind: "sync" as const,
  name: "New media",
  enabled: true,
  cron_expression: "*/15 * * * *",
  timezone: "UTC",
  next_run: "2026-09-19T10:15:00Z",
  created_at: "2026-09-01T00:00:00Z",
  updated_at: "2026-09-01T00:00:00Z",
  last_run_at: "2026-09-19T10:00:00Z",
  run_status: "idle" as const,
  waiting_for: null,
  config: {
    mode: "incremental" as const,
    library_ids: ["2"],
    download_overturedb_art: true,
    download_themes: "themerrdb_overturedb" as const,
  },
  state: {
    checkpoint: "2026-09-19T10:00:00Z",
    last_duration_seconds: 1.25,
    last_items_added: 3,
    last_downloads: 2,
  },
};

async function renderSync() {
  renderWithQueryClient(OperationsPopup, { initialTab: "sync" });
  await screen.findByRole("checkbox", { name: "Movies" });
}

describe("Sync tab", () => {
  beforeEach(() => {
    queryClient.clear();
    localStorage.clear();
    syncState.reset();
    matchState.reset();
    settingsState.load({ tmdb_configured: false });
    libraries.mockReset().mockResolvedValue([
      { key: "1", title: "Movies", media_type: "movie" },
      { key: "2", title: "Shows", media_type: "show" },
    ]);
    schedules.mockReset().mockResolvedValue([]);
    run.mockReset().mockResolvedValue({ status: "started" });
    createSchedule.mockReset().mockResolvedValue(SAVED_POLL);
    updateSchedule.mockReset().mockResolvedValue(SAVED_POLL);
    runSchedule.mockReset().mockResolvedValue({ status: "queued" });
    datasetStatus.mockReset().mockResolvedValue(defaultDatasetStatus);
  });

  it("preserves saved selections during failure and can retry successfully", async () => {
    localStorage.setItem("syncPopup_selectedLibraries", JSON.stringify(["1"]));
    libraries.mockRejectedValueOnce(new Error("Media server is unavailable"));
    renderWithQueryClient(OperationsPopup, { initialTab: "sync" });
    expect(await screen.findByText("Media server is unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run Now" })).toBeDisabled();
    expect(localStorage.getItem("syncPopup_selectedLibraries")).toBe('["1"]');

    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("checkbox", { name: "Movies" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Shows" })).not.toBeChecked();
    await fireEvent.click(screen.getByRole("button", { name: "Run Now" }));
    await waitFor(() =>
      expect(run).toHaveBeenCalledWith({ body: { library_ids: ["1"] } }, expect.anything()),
    );
  });

  it("shows an empty result only after a successful empty response", async () => {
    libraries.mockResolvedValue([]);
    renderWithQueryClient(OperationsPopup, { initialTab: "sync" });
    await screen.findByText("No libraries found on media server.");
    expect(screen.getByRole("button", { name: "Run Now" })).toBeDisabled();
  });

  it("runs a full TMDB season refresh without server libraries", async () => {
    libraries.mockResolvedValue([]);
    settingsState.load({ tmdb_configured: true });
    renderWithQueryClient(OperationsPopup, { initialTab: "sync" });
    await screen.findByText("No libraries found on media server.");

    expect(screen.getByRole("button", { name: "Run Now" })).toBeEnabled();
    await fireEvent.click(screen.getByRole("button", { name: "Run Now" }));
    await waitFor(() =>
      expect(run).toHaveBeenCalledWith({ body: { library_ids: [] } }, expect.anything()),
    );
  });

  it("still requires a library selection when server libraries exist", async () => {
    settingsState.load({ tmdb_configured: true });
    await renderSync();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Deselect All" }));

    expect(screen.getByRole("button", { name: "Run Now" })).toBeDisabled();
    expect(run).not.toHaveBeenCalled();
  });

  it("does not run a TMDB refresh when server libraries failed to load", async () => {
    settingsState.load({ tmdb_configured: true });
    libraries.mockRejectedValue(new Error("Media server is unavailable"));
    renderWithQueryClient(OperationsPopup, { initialTab: "sync" });
    await screen.findByText("Media server is unavailable");

    expect(screen.getByRole("button", { name: "Run Now" })).toBeDisabled();
    expect(run).not.toHaveBeenCalled();
  });

  it("saves a named full sync schedule for the selected libraries", async () => {
    await renderSync();
    const save = screen.getByRole("button", { name: "Save Schedule" });
    expect(save).toBeDisabled();

    await fireEvent.input(screen.getByPlaceholderText("Hourly sync"), {
      target: { value: " Nightly " },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Daily 03:00" }));
    await fireEvent.click(save);

    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledWith(
        {
          body: {
            name: "Nightly",
            enabled: true,
            cron_expression: "0 3 * * *",
            config: {
              mode: "full",
              library_ids: ["1", "2"],
              download_overturedb_art: false,
              download_themes: "off",
            },
          },
        },
        expect.anything(),
      ),
    );
    expect(await screen.findByText("Schedule saved.")).toBeInTheDocument();
    expect(schedules).toHaveBeenCalledTimes(2);
  });

  it("saves new-media polling downloads only when OvertureDB is enabled", async () => {
    datasetStatus.mockResolvedValue({
      ...defaultDatasetStatus,
      enabled: true,
    });
    await renderSync();

    await fireEvent.change(screen.getByRole("combobox", { name: "Schedule type" }), {
      target: { value: "incremental" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Every 15 min" }));
    const downloadArt = screen.getByRole("checkbox", {
      name: "Download OvertureDB art for new media",
    });
    await waitFor(() => expect(downloadArt).toBeEnabled());
    await fireEvent.click(downloadArt);
    await fireEvent.change(
      screen.getByRole("combobox", { name: /Download themes for new media/i }),
      { target: { value: "overturedb_themerrdb" } },
    );
    await fireEvent.input(screen.getByPlaceholderText("Hourly sync"), {
      target: { value: "Poll" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save Schedule" }));

    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            cron_expression: "*/15 * * * *",
            config: {
              mode: "incremental",
              library_ids: ["1", "2"],
              download_overturedb_art: true,
              download_themes: "overturedb_themerrdb",
            },
          }),
        }),
        expect.anything(),
      ),
    );
  });

  it("requires known dataset settings before saving a schedule", async () => {
    datasetStatus.mockRejectedValueOnce(new Error("Dataset status unavailable"));
    await renderSync();
    await fireEvent.input(screen.getByPlaceholderText("Hourly sync"), {
      target: { value: "Nightly" },
    });
    await within(screen.getByRole("tabpanel")).findByText("Dataset status unavailable");
    expect(screen.getByRole("button", { name: "Save Schedule" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run Now" })).toBeEnabled();

    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save Schedule" })).toBeEnabled(),
    );
  });

  it("lists saved schedules with their last poll and loads one for editing", async () => {
    schedules.mockResolvedValue([SAVED_POLL]);
    await renderSync();

    expect(await screen.findByText("New media")).toBeInTheDocument();
    expect(screen.getByText("New-media polling", { selector: ".badge" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "View schedule" }));
    expect(screen.getByText(/1\.3s,\s+3 items added,\s+2 downloads/)).toBeInTheDocument();
    const hide = screen.getByRole("button", { name: "Hide schedule" });
    expect(hide).toHaveAttribute("aria-expanded", "true");

    await fireEvent.click(screen.getByRole("button", { name: "Edit schedule" }));
    expect(screen.getByRole("combobox", { name: "Schedule type" })).toHaveValue("incremental");
    expect(screen.getByRole("checkbox", { name: "Movies" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Shows" })).toBeChecked();
    await fireEvent.click(screen.getByRole("button", { name: "Update Schedule" }));

    await waitFor(() =>
      expect(updateSchedule).toHaveBeenCalledWith(
        {
          body: {
            name: "New media",
            enabled: true,
            cron_expression: "*/15 * * * *",
            config: {
              mode: "incremental",
              library_ids: ["2"],
              download_overturedb_art: false,
              download_themes: "off",
            },
          },
          path: { schedule_id: 7 },
        },
        expect.anything(),
      ),
    );
  });

  it("queues a saved schedule to run now", async () => {
    schedules.mockResolvedValue([SAVED_POLL]);
    await renderSync();
    await screen.findByText("New media");

    await fireEvent.click(screen.getByRole("button", { name: "Run schedule" }));

    await waitFor(() =>
      expect(runSchedule).toHaveBeenCalledWith({ path: { schedule_id: 7 } }, expect.anything()),
    );
    expect(await screen.findByText('"New media" queued.')).toBeInTheDocument();
  });

  it("shows why a schedule waits and reloads when the server announces a change", async () => {
    schedules.mockResolvedValue([
      { ...SAVED_POLL, run_status: "waiting", waiting_for: "asset scan" },
    ]);
    await renderSync();
    expect(await screen.findByRole("status")).toHaveTextContent("Waiting for asset scan");

    schedules.mockResolvedValue([{ ...SAVED_POLL, run_status: "running" }]);
    void invalidateSchedules("sync");

    await waitFor(() => expect(screen.getByRole("status")).toHaveTextContent("Running"));
    schedules.mockResolvedValue([SAVED_POLL]);
    void invalidateSchedules("assets");
    await screen.findByText("New media");
    expect(schedules).toHaveBeenCalledTimes(2);
  });

  it("holds a full sync while Assets runs and says why", async () => {
    localStorage.setItem("syncPopup_selectedLibraries", JSON.stringify(["1"]));
    matchState.markStartAccepted();
    await renderSync();
    expect(screen.getByRole("button", { name: "Run Now" })).toBeDisabled();
    expect(screen.getByText("Wait for Assets to finish.")).toBeInTheDocument();

    matchState.handleCompleted({});
    await waitFor(() => expect(screen.getByRole("button", { name: "Run Now" })).toBeEnabled());
    expect(run).not.toHaveBeenCalled();
  });
});
