import { appSettings, collection } from "../../../helpers/fixtures";
import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import OperationsPopup from "../../../../lib/popups/OperationsPopup.svelte";
import { invalidateSchedules } from "../../../../lib/rest/cache";
import { queryClient } from "../../../../lib/rest/queryClient";
import { matchState } from "../../../../lib/stores/bulkJobState.svelte";
import { settingsState } from "../../../../lib/stores/settingsState.svelte";
import { syncState } from "../../../../lib/stores/jobStates.svelte";
import { syncSelection } from "../../../../lib/stores/syncSelection.svelte";
import { uiState } from "../../../../lib/stores/uiState.svelte";
import { renderWithQueryClient } from "../../../helpers/render";

const libraries = vi.hoisted(() => vi.fn());
const schedules = vi.hoisted(() => vi.fn());
const catalogStatus = vi.hoisted(() => vi.fn());
const run = vi.hoisted(() => vi.fn());
const createSchedule = vi.hoisted(() => vi.fn());
const updateSchedule = vi.hoisted(() => vi.fn());
const runSchedule = vi.hoisted(() => vi.fn());
const collections = vi.hoisted(() => vi.fn());
const defaultCatalogStatus = vi.hoisted(() => ({
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
  getCatalogStatus: async () => ({ data: await catalogStatus() }),
  listCollectionGroups: async () => ({ data: ["Sagas", "Ungrouped"] }),
  listCollections: async () => ({ data: await collections() }),
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
  last_run: { duration_seconds: 1.25, counts: { added: 3, queued: 2 }, failed: false },
  run_status: "idle" as const,
  waiting_for: null,
  config: {
    mode: "incremental" as const,
    include_collections: true,
    items: true,
    library_ids: ["2"],
    download_overturedb_art: true,
    download_themes: "themerrdb_overturedb" as const,
  },
  state: { checkpoint: "2026-09-19T10:00:00Z" },
};

async function renderSync() {
  renderWithQueryClient(OperationsPopup);
  await screen.findByRole("checkbox", { name: "Movies" });
}

describe("Sync tab", () => {
  beforeEach(() => {
    queryClient.clear();
    localStorage.clear();
    uiState.openOperations("sync");
    syncState.reset();
    matchState.reset();
    settingsState.load(appSettings({ media_server: "plex", tmdb_configured: false }));
    libraries.mockReset().mockResolvedValue([
      { key: "1", title: "Movies", media_type: "movie" },
      { key: "2", title: "Shows", media_type: "show" },
    ]);
    schedules.mockReset().mockResolvedValue([]);
    run.mockReset().mockResolvedValue({ status: "started" });
    createSchedule.mockReset().mockResolvedValue(SAVED_POLL);
    updateSchedule.mockReset().mockResolvedValue(SAVED_POLL);
    runSchedule.mockReset().mockResolvedValue({ status: "queued" });
    catalogStatus.mockReset().mockResolvedValue(defaultCatalogStatus);
    collections.mockReset().mockResolvedValue([]);
  });

  it("preserves saved selections during failure and can retry successfully", async () => {
    localStorage.setItem("syncPopup_selectedLibraries", JSON.stringify(["1"]));
    libraries.mockRejectedValueOnce(new Error("Media server is unavailable"));
    renderWithQueryClient(OperationsPopup);
    expect(await screen.findByText("Media server is unavailable")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
    expect(localStorage.getItem("syncPopup_selectedLibraries")).toBe('["1"]');

    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("checkbox", { name: "Movies" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Shows" })).not.toBeChecked();
    await fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    await waitFor(() =>
      expect(run).toHaveBeenCalledWith(
        { body: { include_collections: true, items: true, library_ids: ["1"] } },
        expect.anything(),
      ),
    );
  });

  it("syncs chosen collection groups instead of every collection", async () => {
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    await renderSync();
    expect(screen.getByRole("checkbox", { name: "Deselect all collections" })).toBeChecked();
    // Every collection includes every group, so unticking one keeps the rest.
    await fireEvent.click(await screen.findByRole("checkbox", { name: "Ungrouped" }));
    expect(screen.getByRole("checkbox", { name: "Select all collections" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Sagas" })).toBeChecked();
    await fireEvent.input(screen.getByPlaceholderText("Hourly sync"), {
      target: { value: "Sagas nightly" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));
    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            config: expect.objectContaining({
              include_collections: false,
              collection_groups: ["Sagas"],
            }),
          }),
        }),
        expect.anything(),
      ),
    );

    await fireEvent.click(screen.getByRole("button", { name: "Run now" }));

    await waitFor(() =>
      expect(run).toHaveBeenCalledWith(
        {
          body: {
            library_ids: ["1", "2"],
            include_collections: false,
            collection_groups: ["Sagas"],
            items: true,
          },
        },
        expect.anything(),
      ),
    );
  });

  it("opens from a shortcut with only its collection chosen", async () => {
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    collections.mockResolvedValue([
      collection({ id: 7, title: "Alien", collection_group: "Sagas", managed: true }),
      collection({ id: 8, title: "Pixar", collection_group: null, managed: true }),
    ]);
    syncSelection.focus({ collectionIds: [8] });
    await renderSync();
    expect(screen.getByRole("checkbox", { name: "Movies" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Select all collections" })).not.toBeChecked();
    await fireEvent.click(screen.getByText(/Specific collections/));
    expect(await screen.findByRole("checkbox", { name: "Pixar" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Alien" })).not.toBeChecked();

    await fireEvent.click(screen.getByRole("button", { name: "Run now" }));

    await waitFor(() =>
      expect(run).toHaveBeenCalledWith(
        {
          body: { library_ids: [], include_collections: false, collection_ids: [8], items: false },
        },
        expect.anything(),
      ),
    );
  });

  it("can exclude collections independently of the selected libraries", async () => {
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    await renderSync();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Deselect all collections" }));
    await fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    await waitFor(() =>
      expect(run).toHaveBeenCalledWith(
        { body: { library_ids: ["1", "2"], include_collections: false, items: true } },
        expect.anything(),
      ),
    );
  });

  it("syncs only the collections when no library is chosen", async () => {
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    await renderSync();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Movies" }));
    await fireEvent.click(screen.getByRole("checkbox", { name: "Shows" }));
    expect(screen.getByRole("button", { name: "Run now" })).toBeEnabled();
    await fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    await waitFor(() =>
      expect(run).toHaveBeenCalledWith(
        { body: { library_ids: [], include_collections: true, items: false } },
        expect.anything(),
      ),
    );
  });

  it("shows an empty result only after a successful empty response", async () => {
    libraries.mockResolvedValue([]);
    renderWithQueryClient(OperationsPopup);
    await screen.findByText("No libraries found on media server.");
    expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
  });

  it("runs a full TMDB season refresh without server libraries", async () => {
    libraries.mockResolvedValue([]);
    settingsState.load(appSettings({ media_server: "plex", tmdb_configured: true }));
    renderWithQueryClient(OperationsPopup);
    await screen.findByText("No libraries found on media server.");

    expect(screen.getByRole("button", { name: "Run now" })).toBeEnabled();
    await fireEvent.click(screen.getByRole("button", { name: "Run now" }));
    await waitFor(() =>
      expect(run).toHaveBeenCalledWith(
        { body: { include_collections: true, items: true, library_ids: [] } },
        expect.anything(),
      ),
    );
  });

  it("still requires a library selection when server libraries exist", async () => {
    settingsState.load(appSettings({ media_server: "plex", tmdb_configured: true }));
    await renderSync();
    await fireEvent.click(screen.getByRole("checkbox", { name: "Deselect all libraries" }));

    expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
    expect(run).not.toHaveBeenCalled();
  });

  it("does not run a TMDB refresh when server libraries failed to load", async () => {
    settingsState.load(appSettings({ media_server: "plex", tmdb_configured: true }));
    libraries.mockRejectedValue(new Error("Media server is unavailable"));
    renderWithQueryClient(OperationsPopup);
    await screen.findByText("Media server is unavailable");

    expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
    expect(run).not.toHaveBeenCalled();
  });

  it("saves a named full sync schedule for the selected libraries", async () => {
    await renderSync();
    const save = screen.getByRole("button", { name: "Save schedule" });
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
              include_collections: true,
              items: true,
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
    catalogStatus.mockResolvedValue({
      ...defaultCatalogStatus,
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
    await fireEvent.click(screen.getByRole("button", { name: "Save schedule" }));

    await waitFor(() =>
      expect(createSchedule).toHaveBeenCalledWith(
        expect.objectContaining({
          body: expect.objectContaining({
            cron_expression: "*/15 * * * *",
            config: {
              mode: "incremental",
              include_collections: true,
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

  it("requires known catalog settings before saving a schedule", async () => {
    catalogStatus.mockRejectedValueOnce(new Error("Catalog status unavailable"));
    await renderSync();
    await fireEvent.input(screen.getByPlaceholderText("Hourly sync"), {
      target: { value: "Nightly" },
    });
    await within(screen.getByRole("tabpanel")).findByText("Catalog status unavailable");
    expect(screen.getByRole("button", { name: "Save schedule" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Run now" })).toBeEnabled();

    await fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Save schedule" })).toBeEnabled(),
    );
  });

  it("lists saved schedules with their last run and loads one for editing", async () => {
    schedules.mockResolvedValue([SAVED_POLL]);
    await renderSync();

    expect(await screen.findByText("New media")).toBeInTheDocument();
    expect(screen.getByText("New-media polling", { selector: ".badge" })).toBeInTheDocument();
    // The last run is shown without expanding the schedule.
    const summary = screen.getByRole("button", {
      name: /Last run: .* · Result: 1.3s, 3 added, 2 queued$/,
    });
    expect(summary).toHaveAttribute("aria-expanded", "false");
    await fireEvent.click(summary);
    expect(summary).toHaveAttribute("aria-expanded", "true");

    await fireEvent.click(screen.getByRole("button", { name: "Edit schedule" }));
    expect(screen.getByRole("combobox", { name: "Schedule type" })).toHaveValue("incremental");
    expect(screen.getByRole("checkbox", { name: "Movies" })).not.toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Shows" })).toBeChecked();
    await fireEvent.click(screen.getByRole("button", { name: "Update schedule" }));

    await waitFor(() =>
      expect(updateSchedule).toHaveBeenCalledWith(
        {
          body: {
            name: "New media",
            enabled: true,
            cron_expression: "*/15 * * * *",
            config: {
              mode: "incremental",
              include_collections: true,
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

  it("stops editing a schedule with its pencil, the only way to cancel", async () => {
    schedules.mockResolvedValue([SAVED_POLL]);
    await renderSync();
    await screen.findByText("New media");

    await fireEvent.click(screen.getByRole("button", { name: "Edit schedule" }));
    expect(screen.getByText('Editing "New media"')).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Update schedule" })).toBeInTheDocument();
    const pencil = screen.getByRole("button", { name: "Cancel editing" });
    expect(pencil).toHaveAttribute("aria-pressed", "true");
    await fireEvent.click(pencil);
    expect(screen.queryByText('Editing "New media"')).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save schedule" })).toBeInTheDocument();
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
    expect(screen.getByRole("button", { name: "Run now" })).toBeDisabled();
    expect(screen.getByText("Wait for Assets to finish.")).toBeInTheDocument();

    matchState.handleCompleted({});
    await waitFor(() => expect(screen.getByRole("button", { name: "Run now" })).toBeEnabled());
    expect(run).not.toHaveBeenCalled();
  });
});
