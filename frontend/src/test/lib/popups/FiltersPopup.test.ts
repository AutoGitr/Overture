import { fireEvent, waitFor, within } from "@testing-library/svelte";
import { storePublicDatasetStatus } from "../../../lib/realtime/cache";
import { beforeEach, describe, expect, it } from "vitest";
import { listItemsOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import type { MediaItemListResponse } from "../../../generated/rest/types.gen";
import FiltersPopup from "../../../lib/popups/FiltersPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { navigate } from "../../../lib/router/routes";
import { defaultFilters, uiState } from "../../../lib/stores/uiState.svelte";
import { mockFetch, mockFetchSequence } from "../../helpers/fetch";
import { publicDatasetStatus, mediaItem } from "../../helpers/fixtures";
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
      within(view.getByRole("radiogroup", { name: "Resolution Art Type" })).getByRole("radio", {
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
      within(view.getByRole("radiogroup", { name: "Art Source Art Type" })).getByRole("radio", {
        name: "Poster",
      }),
    );
    await fireEvent.click(view.getByRole("checkbox", { name: "ThePosterDB" }));
    await fireEvent.click(view.getByRole("checkbox", { name: "OvertureDB" }));
    await fireEvent.click(view.getByRole("button", { name: "Apply filters" }));

    expect(uiState.movieFilters.artSource).toEqual({
      artType: "poster",
      sources: ["overturedb", "tpdb"],
    });
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
      within(view.getByRole("radiogroup", { name: "ThemerrDB Status" })).getByRole("radio", {
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
        mediaItem({ id: 1, director: "Alice", youtube_id: "theme" }),
        mediaItem({ id: 2, director: "Alice", monitored: false }),
        mediaItem({ id: 3, title: "Alice", director: "Bob", youtube_id: "other" }),
      ],
      total: 3,
    });
    uiState.searchQuery = "Alice";
    uiState.searchField = "director";
    const view = renderWithQueryClient(FiltersPopup);

    expect(view.getByRole("region", { name: "Bulk operations" })).toBeInTheDocument();
    expect(view.getByRole("button", { name: "Monitor 1" })).toBeEnabled();
    expect(view.getByRole("button", { name: "Unmonitor 1" })).toBeEnabled();
    expect(view.getByRole("button", { name: "Clear theme selections 1" })).toBeEnabled();
    expect(view.getByRole("button", { name: "Clear artwork selections 2" })).toBeEnabled();
    expect(view.getByRole("button", { name: "Delete from Overture 2" })).toBeEnabled();

    await fireEvent.click(view.getByRole("radio", { name: "Unmonitored" }));
    expect(view.getByRole("button", { name: "Clear theme selections 0" })).toBeDisabled();
    expect(view.getByRole("button", { name: "Delete from Overture 1" })).toBeEnabled();
    expect(uiState.movieFilters.monitored).toBe("all");
  });

  it.each([
    ["artwork", "Clear artwork selections 2"],
    ["themes", "Clear theme selections 2"],
  ])("clears %s in one request for a fixed filtered target set", async (operation, label) => {
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
      { body: { item_ids: [1, 2], operation } },
    ]);
    const view = renderWithQueryClient(FiltersPopup);
    await waitFor(() => expect(calls).toHaveLength(1));
    await fireEvent.click(view.getByRole("button", { name: label }));
    expect((await answerConfirmation(true)).message).toContain("Local");

    await waitFor(() =>
      expect(view.getByRole("status")).toHaveTextContent("selections for 2 movies"),
    );
    expect(calls[1]?.url).toBe("/api/library/items/bulk-operation");
    expect(calls[1]?.init.method).toBe("POST");
    expect(JSON.parse(calls[1]?.init.body as string)).toEqual({ item_ids: [1, 2], operation });
    // Clearing changes completeness, so the list is fetched again from the server.
    await waitFor(() =>
      expect(
        calls.slice(2).some((call) => call.url === "/api/library/items?media_type=movie"),
      ).toBe(true),
    );
  });

  it("deletes only draft-filtered items and removes them from the cache", async () => {
    queryClient.setQueryData(listItemsOptions({ query: { media_type: "movie" } }).queryKey, {
      items: [mediaItem({ id: 1 }), mediaItem({ id: 2, monitored: false })],
      total: 2,
    });
    const { calls } = mockFetchSequence([
      { body: [] },
      { body: { item_ids: [2], operation: "delete" } },
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

  it.each(["Clear artwork selections 1", "Clear theme selections 1", "Delete from Overture 1"])(
    "does not run %s when confirmation is cancelled",
    async (label) => {
      queryClient.setQueryData(listItemsOptions({ query: { media_type: "movie" } }).queryKey, {
        items: [mediaItem({ youtube_id: "theme" })],
        total: 1,
      });
      const { calls } = mockFetch([]);
      const view = renderWithQueryClient(FiltersPopup);
      await fireEvent.click(view.getByRole("button", { name: label }));
      await answerConfirmation(false);
      expect(calls.some((call) => call.init.method === "POST")).toBe(false);
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
});
