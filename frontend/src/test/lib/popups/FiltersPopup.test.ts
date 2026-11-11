import { fireEvent, waitFor, within } from "@testing-library/svelte";
import { storePublicDatasetStatus } from "../../../lib/realtime/cache";
import { beforeEach, describe, expect, it } from "vitest";
import {
  listCatalogEntriesOptions,
  listCollectionsOptions,
  listItemsOptions,
} from "../../../generated/rest/@tanstack/svelte-query.gen";
import type { MediaItemListResponse } from "../../../generated/rest/types.gen";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import FiltersPopup from "../../../lib/popups/FiltersPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { navigate, openSidebarGroup } from "../../../lib/router/routes";
import { defaultFilters, uiState } from "../../../lib/stores/uiState.svelte";
import { mockFetch, mockFetchRoutes, mockFetchSequence } from "../../helpers/fetch";
import {
  appSettings,
  catalogRow,
  collection,
  collectionCapabilities,
  mediaItem,
  publicDatasetStatus,
} from "../../helpers/fixtures";
import { answerConfirmation } from "../../helpers/notifications";
import { renderWithQueryClient } from "../../helpers/render";

// sidebarTab/sidebarMode are derived from the URL, so the route sets them.
describe("FiltersPopup edits one draft of the filter set", () => {
  beforeEach(async () => {
    await navigate("/movies", { replace: true });
    queryClient.clear();
    mockFetch([]);
    uiState.setFilters(defaultFilters());
    uiState.searchQuery = "";
    uiState.searchField = "title";
    storePublicDatasetStatus(publicDatasetStatus({ enabled: false }));
    queryClient.setQueryData(listItemsOptions({ query: { media_type: "show" } }).queryKey, {
      items: [],
      total: 0,
    });
  });

  it("offers an ID mismatch as a metadata issue while OvertureDB is enabled", async () => {
    storePublicDatasetStatus(publicDatasetStatus({ enabled: true }));
    const view = renderWithQueryClient(FiltersPopup);
    const issues = view.getByRole("region", { name: "Metadata issues" });
    await fireEvent.click(within(issues).getByRole("checkbox", { name: "ID mismatch" }));
    await fireEvent.click(view.getByRole("button", { name: "Apply filters" }));
    expect(uiState.movieFilters.metadataIssues.flags).toEqual(["id_mismatch"]);
  });

  it("applies the draft to the active tab's filters", async () => {
    const view = renderWithQueryClient(FiltersPopup);

    await fireEvent.click(view.getByRole("radio", { name: "Monitored" }));
    await fireEvent.click(view.getByRole("button", { name: "Apply filters" }));

    expect(uiState.movieFilters.monitored).toBe("monitored");
    expect(uiState.showFilters.monitored).toBe("all");
  });

  it("clears back to the shared defaults rather than a second copy of them", async () => {
    uiState.setFilters({ ...defaultFilters(), themeLength: { min: 30, max: 400 } });

    const view = renderWithQueryClient(FiltersPopup);
    await fireEvent.click(view.getByRole("button", { name: "Reset filters" }));
    await fireEvent.click(view.getByRole("button", { name: "Apply filters" }));

    expect(uiState.movieFilters).toEqual(defaultFilters());
  });

  it("applies theme length and resolution ranges, leaving empty limits open", async () => {
    const view = renderWithQueryClient(FiltersPopup);

    await fireEvent.input(view.getByLabelText("Min length (s)"), { target: { value: "30" } });
    await fireEvent.input(view.getByLabelText("Max length (s)"), { target: { value: "90" } });
    await fireEvent.click(
      within(view.getByRole("radiogroup", { name: "Resolution art type" })).getByRole("radio", {
        name: "Background",
      }),
    );
    await fireEvent.input(view.getByLabelText("Max width (px)"), { target: { value: "1280" } });
    await fireEvent.click(view.getByRole("button", { name: "Apply filters" }));

    expect(uiState.movieFilters.themeLength).toEqual({ min: 30, max: 90 });
    expect(uiState.movieFilters.resolution).toEqual({
      artType: "background",
      min: null,
      max: 1280,
    });
  });

  it("applies selected theme sources", async () => {
    const view = renderWithQueryClient(FiltersPopup);

    await fireEvent.click(view.getByRole("checkbox", { name: "File ID tag" }));
    await fireEvent.click(view.getByRole("checkbox", { name: "Downloaded" }));
    await fireEvent.click(view.getByRole("button", { name: "Apply filters" }));

    expect(uiState.movieFilters.themeSources).toEqual(["download", "embedded_id"]);
  });

  it("applies selected art sources for the chosen artwork", async () => {
    const view = renderWithQueryClient(FiltersPopup);

    await fireEvent.click(
      within(view.getByRole("radiogroup", { name: "Art source art type" })).getByRole("radio", {
        name: "Poster",
      }),
    );
    await fireEvent.click(view.getByRole("checkbox", { name: "ThePosterDB" }));
    await fireEvent.click(view.getByRole("checkbox", { name: "TMDB" }));
    await fireEvent.click(view.getByRole("button", { name: "Apply filters" }));

    expect(uiState.movieFilters.artSource).toEqual({
      artType: "poster",
      // Sources keep the list's alphabetical order.
      sources: ["tpdb", "tmdb"],
    });
    expect(view.queryByRole("checkbox", { name: "OvertureDB" })).toBeNull();
  });

  it("offers the TVDB ID metadata filter for shows only", async () => {
    const movieView = renderWithQueryClient(FiltersPopup);
    expect(movieView.getByRole("checkbox", { name: "No TMDB ID" })).toBeInTheDocument();
    expect(movieView.queryByRole("checkbox", { name: "No TVDB ID" })).toBeNull();
    movieView.unmount();

    await navigate("/shows", { replace: true });
    const showView = renderWithQueryClient(FiltersPopup);
    expect(showView.getByRole("checkbox", { name: "No TVDB ID" })).toBeInTheDocument();
  });

  it("drops selections for libraries that no longer exist when applying", async () => {
    mockFetch([
      { id: "lib-1", title: "Films", count: 3 },
      { id: "lib-2", title: "Kids", count: 1 },
    ]);
    uiState.setFilters({ ...defaultFilters(), libraryIds: ["gone", "lib-1"] });
    const view = renderWithQueryClient(FiltersPopup);

    expect(await view.findByText("1 of 2 selected")).toBeInTheDocument();
    await fireEvent.click(view.getByRole("button", { name: "Apply filters" }));

    expect(uiState.movieFilters.libraryIds).toEqual(["lib-1"]);
  });

  it("leaves the stored filters untouched until Apply", async () => {
    const view = renderWithQueryClient(FiltersPopup);

    await fireEvent.click(view.getByRole("radio", { name: "Unmonitored" }));

    expect(uiState.movieFilters.monitored).toBe("all");
  });

  it("applies the media server and themerrdb filter drafts when active", async () => {
    storePublicDatasetStatus(publicDatasetStatus());
    const view = renderWithQueryClient(FiltersPopup);

    await fireEvent.click(view.getByRole("radio", { name: "Missing" }));
    await fireEvent.click(
      within(view.getByRole("radiogroup", { name: "ThemerrDB" })).getByRole("radio", {
        name: "Complete",
      }),
    );
    await fireEvent.click(view.getByRole("button", { name: "Apply filters" }));

    expect(uiState.movieFilters.mediaServer).toBe("missing");
    expect(uiState.movieFilters.themerrDb).toBe("complete");
  });

  it("unmonitors currently filtered items after user confirmation", async () => {
    const item1 = mediaItem({ id: 1, title: "Item 1", monitored: true });
    const item2 = mediaItem({ id: 2, title: "Item 2", monitored: true });
    queryClient.setQueryData(listItemsOptions({ query: { media_type: "movie" } }).queryKey, {
      items: [item1, item2],
      total: 2,
    });

    const { calls } = mockFetchSequence([
      { body: [] },
      { body: { item_ids: [1, 2], operation: "unmonitor" } },
    ]);

    const view = renderWithQueryClient(FiltersPopup);
    await waitFor(() => expect(calls).toHaveLength(1));
    const unmonitorBtn = view.getByRole("button", { name: "Unmonitor 2" });
    expect(unmonitorBtn).not.toBeDisabled();

    await fireEvent.click(unmonitorBtn);

    expect((await answerConfirmation(true)).title).toBe("Unmonitor 2 filtered movies?");
    await waitFor(() => {
      const bulkCall = calls.find((call) => call.url === "/api/library/items/bulk-operation");
      expect(bulkCall).toBeDefined();
      expect(bulkCall?.init.method).toBe("POST");
      expect(JSON.parse(bulkCall?.init.body as string)).toEqual({
        item_ids: [1, 2],
        operation: "unmonitor",
      });

      const updatedData = queryClient.getQueryData<MediaItemListResponse>(
        listItemsOptions({ query: { media_type: "movie" } }).queryKey,
      );
      expect(updatedData?.items.every((item) => !item.monitored)).toBe(true);
    });
    expect(await view.findByRole("status")).toHaveTextContent("Unmonitored 2 movies.");
  });

  it("monitors currently unmonitored filtered items after user confirmation", async () => {
    const item1 = mediaItem({ id: 1, title: "Item 1", monitored: false });
    const item2 = mediaItem({ id: 2, title: "Item 2", monitored: false });
    queryClient.setQueryData(listItemsOptions({ query: { media_type: "movie" } }).queryKey, {
      items: [item1, item2],
      total: 2,
    });

    const { calls } = mockFetchSequence([
      { body: [] },
      { body: { item_ids: [1, 2], operation: "monitor" } },
    ]);

    const view = renderWithQueryClient(FiltersPopup);
    await waitFor(() => expect(calls).toHaveLength(1));
    const monitorBtn = view.getByRole("button", { name: "Monitor 2" });
    const unmonitorBtn = view.getByRole("button", { name: "Unmonitor 0" });
    expect(monitorBtn).not.toBeDisabled();
    expect(unmonitorBtn).toBeDisabled();

    await fireEvent.click(monitorBtn);

    expect((await answerConfirmation(true)).title).toBe("Monitor 2 filtered movies?");
    await waitFor(() => {
      const bulkCall = calls.find((call) => call.url === "/api/library/items/bulk-operation");
      expect(bulkCall).toBeDefined();
      expect(bulkCall?.init.method).toBe("POST");
      expect(JSON.parse(bulkCall?.init.body as string)).toEqual({
        item_ids: [1, 2],
        operation: "monitor",
      });

      const updatedData = queryClient.getQueryData<MediaItemListResponse>(
        listItemsOptions({ query: { media_type: "movie" } }).queryKey,
      );
      expect(updatedData?.items.every((item) => item.monitored)).toBe(true);
    });
  });

  it("counts operations using draft filters and the active search field", async () => {
    queryClient.setQueryData(listItemsOptions({ query: { media_type: "movie" } }).queryKey, {
      items: [
        mediaItem({ id: 1, directors: ["Alice"], youtube_id: "theme" }),
        mediaItem({ id: 2, directors: ["Alice"], monitored: false }),
        mediaItem({ id: 3, title: "Alice", directors: ["Bob"], youtube_id: "other" }),
      ],
      total: 3,
    });
    uiState.searchQuery = "Alice";
    uiState.searchField = "director";
    const view = renderWithQueryClient(FiltersPopup);

    expect(view.getByRole("region", { name: "Bulk operations" })).toBeInTheDocument();
    expect(view.getByRole("button", { name: "Monitor 1" })).toBeEnabled();
    expect(view.getByRole("button", { name: "Unmonitor 1" })).toBeEnabled();
    expect(view.getByRole("button", { name: "Remove themes 2" })).toBeEnabled();
    expect(view.getByRole("button", { name: "Remove art 2" })).toBeEnabled();
    expect(view.getByRole("button", { name: "Delete from Overture 2" })).toBeEnabled();

    await fireEvent.click(view.getByRole("radio", { name: "Unmonitored" }));
    expect(view.getByRole("button", { name: "Remove themes 1" })).toBeEnabled();
    expect(view.getByRole("button", { name: "Delete from Overture 1" })).toBeEnabled();
    expect(uiState.movieFilters.monitored).toBe("all");
  });

  it.each([
    ["artwork", "art", "Remove art 2", "Delete the local image files"],
    ["themes", "theme", "Remove themes 2", "Delete the local MP3 files"],
  ])(
    "removes %s as chosen in one request for a fixed filtered target set",
    async (operation, asset, label, deleteFiles) => {
      const items = [1, 2].map((id) =>
        mediaItem({ id, title: `Item ${id}`, youtube_id: "theme", theme_status: "complete" }),
      );
      queryClient.setQueryData(listItemsOptions({ query: { media_type: "movie" } }).queryKey, {
        items: [...items, mediaItem({ id: 3 })],
        total: 3,
      });
      uiState.setFilters({ ...defaultFilters(), theme: "complete" });
      const { calls } = mockFetchSequence([
        { body: [] }, // Libraries query on mount.
        {
          body: {
            forget: { count: 2 },
            delete_file: { count: 1 },
            delete_from_server: { count: 0, unavailable: "Plex's API cannot delete artwork" },
          },
        },
        { body: { item_ids: [1, 2], operation, errors: {} } },
      ]);
      const view = renderWithQueryClient(FiltersPopup);
      await waitFor(() => expect(calls).toHaveLength(1));
      await fireEvent.click(view.getByRole("button", { name: label }));
      const dialog = await view.findByRole("dialog", { name: /^Remove the/ });
      // What cannot apply is shown, with why, and cannot be ticked.
      expect(
        within(dialog).getByRole("checkbox", { name: "Delete from the media server" }),
      ).toBeDisabled();
      expect(within(dialog).getByText("Plex's API cannot delete artwork")).toBeInTheDocument();
      expect(within(dialog).getByRole("checkbox", { name: "Forget the selection" })).toBeChecked();
      await answerConfirmation(true, undefined, [deleteFiles]);

      await waitFor(() =>
        expect(view.getByRole("status")).toHaveTextContent(
          "of 2 movies: forgot the selection and deleted the local files.",
        ),
      );
      expect(calls[1]?.url).toBe("/api/art/removal-options");
      expect(JSON.parse(calls[1]?.init.body as string)).toEqual({ asset, item_ids: [1, 2] });
      expect(calls[2]?.url).toBe("/api/library/items/bulk-operation");
      expect(calls[2]?.init.method).toBe("POST");
      expect(JSON.parse(calls[2]?.init.body as string)).toEqual({
        item_ids: [1, 2],
        operation,
        removal: { forget: true, delete_file: true, delete_from_server: false },
      });
      // Clearing changes completeness, so the list is fetched again from the server.
      await waitFor(() =>
        expect(
          calls.slice(2).some((call) => call.url === "/api/library/items?media_type=movie"),
        ).toBe(true),
      );
    },
  );

  it("deletes only draft-filtered items and removes them from the cache", async () => {
    queryClient.setQueryData(listItemsOptions({ query: { media_type: "movie" } }).queryKey, {
      items: [mediaItem({ id: 1 }), mediaItem({ id: 2, monitored: false })],
      total: 2,
    });
    const { calls } = mockFetchSequence([
      { body: [] },
      { body: { item_ids: [2], operation: "delete", errors: {} } },
    ]);
    const view = renderWithQueryClient(FiltersPopup);
    await waitFor(() => expect(calls).toHaveLength(1));
    await fireEvent.click(view.getByRole("radio", { name: "Unmonitored" }));
    await fireEvent.click(view.getByRole("button", { name: "Delete from Overture 1" }));
    expect((await answerConfirmation(true)).title).toBe("Delete 1 filtered movies?");

    await waitFor(() => expect(view.getByRole("status")).toHaveTextContent("Deleted 1 movies"));
    const mutations = calls.filter((call) => call.init.method === "POST");
    expect(mutations).toHaveLength(1);
    expect(JSON.parse(mutations[0]?.init.body as string)).toEqual({
      item_ids: [2],
      operation: "delete",
    });
    expect(
      queryClient
        .getQueryData<MediaItemListResponse>(
          listItemsOptions({ query: { media_type: "movie" } }).queryKey,
        )
        ?.items.map((item) => item.id),
    ).toEqual([1]);
  });

  it.each(["Remove art 1", "Remove themes 1", "Delete from Overture 1"])(
    "does not run %s when confirmation is cancelled",
    async (label) => {
      queryClient.setQueryData(listItemsOptions({ query: { media_type: "movie" } }).queryKey, {
        items: [mediaItem({ youtube_id: "theme" })],
        total: 1,
      });
      const { calls } = mockFetchRoutes({
        "/api/library/libraries": [],
        "/api/art/removal-options": {
          forget: { count: 1 },
          delete_file: { count: 0 },
          delete_from_server: { count: 1 },
        },
      });
      const view = renderWithQueryClient(FiltersPopup);
      await fireEvent.click(view.getByRole("button", { name: label }));
      await answerConfirmation(false);
      expect(calls.some((call) => call.url.endsWith("/bulk-operation"))).toBe(false);
    },
  );

  it("keeps the complete target set in cache when a bulk request fails", async () => {
    queryClient.setQueryData(listItemsOptions({ query: { media_type: "movie" } }).queryKey, {
      items: [1, 2, 3].map((id) => mediaItem({ id, title: `Item ${id}` })),
      total: 3,
    });
    const { calls } = mockFetchSequence([
      { body: [] },
      { body: { detail: "Delete failed" }, init: { status: 500 } },
    ]);
    const view = renderWithQueryClient(FiltersPopup);
    await waitFor(() => expect(calls).toHaveLength(1));
    await fireEvent.click(view.getByRole("button", { name: "Delete from Overture 3" }));
    await answerConfirmation(true);

    await waitFor(() => expect(view.getByRole("alert")).toHaveTextContent("Delete failed"));
    expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(1);
    expect(view.getByRole("button", { name: "Delete from Overture 3" })).toBeEnabled();
  });
  it.each([
    ["set_group", { collection_group: "Weekend" }],
    ["set_order", { order_type: "title.asc" }],
    ["apply_sort_title_format", { sort_title_format: "+{title}" }],
    ["set_visibility", { collection_mode: "hide", visible_home: true }],
    ["orphan", {}],
    ["delete", { delete_target: "server" }],
  ])("applies %s only to filtered collections in the open group", async (operation, expected) => {
    await navigate("/collections");
    openSidebarGroup("Weekend");
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    queryClient.setQueryData(listCollectionsOptions().queryKey, [
      collection({
        id: 1,
        title: "Empty",
        collection_group: "Weekend",
        child_count: 0,
        below_minimum: true,
      }),
      collection({
        id: 2,
        title: "Other group",
        collection_group: "Other",
        child_count: 0,
        below_minimum: true,
      }),
      collection({
        id: 3,
        title: "Populated",
        collection_group: "Weekend",
        child_count: 2,
        below_minimum: false,
      }),
    ]);
    const { calls } = mockFetchRoutes({
      "/api/library/libraries": [],
      "/api/collections/capabilities": collectionCapabilities(),
      "/api/collections/bulk-operation": { collection_ids: [1], errors: {} },
      "/api/collections/groups": ["Ungrouped", "Weekend"],
    });
    const view = renderWithQueryClient(FiltersPopup);
    // Plex offers smart collections, so the server's options have loaded.
    await view.findByRole("radiogroup", { name: "Kind" });
    await fireEvent.click(
      within(view.getByRole("radiogroup", { name: "Size" })).getByLabelText("Empty"),
    );
    await fireEvent.change(view.getByLabelText("Operation"), { target: { value: operation } });
    if (operation === "set_group")
      await fireEvent.change(view.getByLabelText("Target group"), { target: { value: "Weekend" } });
    if (operation === "set_order")
      await fireEvent.change(await view.findByLabelText(/^Sort/), {
        target: { value: "title.asc" },
      });
    if (operation === "apply_sort_title_format")
      await fireEvent.input(view.getByRole("textbox", { name: /^Sort title template/ }), {
        target: { value: "+{title}" },
      });
    if (operation === "set_visibility") {
      await fireEvent.change(view.getByLabelText("Visibility"), { target: { value: "hide" } });
      await fireEvent.click(view.getByLabelText("Visible on home"));
    }
    await fireEvent.click(view.getByRole("button", { name: "Apply to 1 collections" }));
    await answerConfirmation(
      true,
      operation === "delete" ? "From the media server only" : undefined,
    );
    await waitFor(() => expect(calls.some((call) => call.init.method === "POST")).toBe(true));
    expect(
      JSON.parse(String(calls.find((call) => call.init.method === "POST")?.init.body)),
    ).toEqual({ collection_ids: [1], operation, ...expected });
  });

  it("lists collection operations and target groups alphabetically, without group actions", async () => {
    await navigate("/collections");
    openSidebarGroup("Weekend");
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    queryClient.setQueryData(listCollectionsOptions().queryKey, [
      collection({ id: 1, title: "Saga", collection_group: "Weekend" }),
    ]);
    mockFetchRoutes({
      "/api/library/libraries": [],
      "/api/collections/capabilities": collectionCapabilities(),
      "/api/collections/groups": ["Weekend", "Anime", "Ungrouped"],
    });
    const view = renderWithQueryClient(FiltersPopup);
    await view.findByRole("radiogroup", { name: "Kind" });
    const operations = within(view.getByLabelText("Operation"))
      .getAllByRole("option")
      .map((option) => option.textContent?.trim());
    expect(operations).toEqual([
      "Adopt unmanaged",
      "Assign group",
      "Delete collections",
      "Format sort titles",
      "Orphan managed",
      "Set sort",
      "Set visibility",
    ]);
    await fireEvent.change(view.getByLabelText("Operation"), { target: { value: "set_group" } });
    await waitFor(() =>
      expect(
        within(view.getByLabelText("Target group"))
          .getAllByRole("option")
          .map((option) => option.textContent),
      ).toEqual(["Anime", "Ungrouped", "Weekend"]),
    );
    // Groups are renamed and deleted in Collection groups, not among the filters.
    expect(view.queryByRole("button", { name: /rename/i })).toBeNull();
    expect(view.queryByRole("button", { name: /delete group/i })).toBeNull();
  });

  it("groups collection filters: status first, then art, theme, metadata, bulk and collection operations", async () => {
    await navigate("/collections");
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    queryClient.setQueryData(listCollectionsOptions().queryKey, []);
    mockFetchRoutes({
      "/api/library/libraries": [],
      "/api/collections/capabilities": collectionCapabilities(),
    });
    const view = renderWithQueryClient(FiltersPopup);
    await view.findByRole("radiogroup", { name: "Kind" });

    for (const name of [
      "Status",
      "Art",
      "Theme music",
      "Metadata issues",
      "Bulk operations",
      "Collection operations",
    ])
      expect(view.getByRole("button", { name, expanded: true })).toBeInTheDocument();
    const status = within(view.getByRole("region", { name: "Status" }));
    // The most used first, and filters with the same choices side by side.
    expect(
      status.getAllByRole("radiogroup").map((group) => group.getAttribute("aria-label")),
    ).toEqual([
      "Monitor status",
      "Art complete",
      "Theme complete",
      "Aspect ratio",
      "Media server",
      "Last sync",
      "Size",
      "Management",
      "Kind",
      "Made as",
      "Holds",
    ]);
    expect(
      within(view.getByRole("region", { name: "Art" })).getByRole("group", {
        name: "Art resolution",
      }),
    ).toBeInTheDocument();
    expect(view.queryByRole("region", { name: "Collections" })).toBeNull();
    expect(view.queryByRole("region", { name: "Theme source" })).toBeNull();
  });

  it("narrows items to one collection holding the tab's media type", async () => {
    await navigate("/movies");
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    queryClient.setQueryData(listCollectionsOptions().queryKey, [
      collection({ id: 6, title: "Lost", media_types: ["show"] }),
      collection({ id: 5, title: "Alien", media_types: ["movie"] }),
    ]);
    mockFetchRoutes({ "/api/library/libraries": [] });
    const view = renderWithQueryClient(FiltersPopup);

    const select = await view.findByRole("combobox", { name: "Collection" });
    expect(within(select).queryByRole("option", { name: "Lost" })).toBeNull();
    await fireEvent.change(select, { target: { value: "5" } });
    await fireEvent.click(view.getByRole("button", { name: "Apply filters" }));

    expect(uiState.movieFilters.collectionId).toBe(5);
  });

  it("discards the drafts of the catalog entries the filters match", async () => {
    await navigate("/overturedb/movies");
    storePublicDatasetStatus(publicDatasetStatus({ enabled: true }));
    queryClient.setQueryData(
      listCatalogEntriesOptions({ query: { media_type: "movie" } }).queryKey,
      [
        catalogRow({ entry_key: "tmdb-1", title: "Drafted", has_draft: true }),
        catalogRow({ entry_key: "tmdb-2", title: "Clean" }),
      ],
    );
    const { calls } = mockFetchRoutes({
      "/api/public-dataset/catalog/movie/drafts": { discarded: 1 },
    });
    const view = renderWithQueryClient(FiltersPopup);

    await fireEvent.click(view.getByRole("button", { name: "Discard drafts (1)" }));
    await answerConfirmation(true);

    await waitFor(() =>
      expect(calls.find((call) => call.init.method === "DELETE")?.init.body).toBe(
        JSON.stringify({ entry_keys: ["tmdb-1"] }),
      ),
    );
  });

  it("removes the themes of the matching collections as chosen", async () => {
    await navigate("/collections");
    settingsState.load(appSettings({ media_server: "plex", collections_supported: true }));
    queryClient.setQueryData(listCollectionsOptions().queryKey, [
      collection({ id: 1, youtube_id: "abcdefghijk" }),
      collection({ id: 2 }),
    ]);
    const { calls } = mockFetchRoutes({
      "/api/library/libraries": [],
      "/api/collections/capabilities": collectionCapabilities(),
      "/api/collections/bulk-operation": { collection_ids: [1], errors: {}, skipped: {} },
      "/api/art/removal-options": {
        forget: { count: 1 },
        delete_file: { count: 0, unavailable: "Plex keeps collection themes itself" },
        delete_from_server: { count: 1 },
      },
    });
    const view = renderWithQueryClient(FiltersPopup);
    await fireEvent.click(await view.findByRole("button", { name: /Remove themes 2/ }));
    await answerConfirmation(true, undefined, ["Delete from the media server"]);
    await waitFor(() =>
      expect(
        JSON.parse(String(calls.find((call) => call.url.endsWith("/bulk-operation"))?.init.body)),
      ).toEqual({
        collection_ids: [1, 2],
        operation: "remove_themes",
        removal: { forget: true, delete_file: false, delete_from_server: true },
      }),
    );
    expect(
      JSON.parse(String(calls.find((call) => call.url.endsWith("/removal-options"))?.init.body)),
    ).toEqual({ asset: "theme", collection_ids: [1, 2] });
  });
});
