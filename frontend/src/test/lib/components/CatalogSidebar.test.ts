import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import {
  getPublicDatasetStatusOptions,
  listCatalogEntriesOptions,
} from "../../../generated/rest/@tanstack/svelte-query.gen";
import Sidebar from "../../../lib/components/Sidebar.svelte";
import FiltersPopup from "../../../lib/popups/FiltersPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { navigate, route } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { sidebarState } from "../../../lib/stores/sidebarState.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { defaultCatalogFilters } from "../../../lib/utils/sidebarDomain";
import { appSettings, catalogRow, mediaItem, publicDatasetStatus } from "../../helpers/fixtures";
import { mockFetchRoutes } from "../../helpers/fetch";
import { renderWithQueryClient } from "../../helpers/render";

const alien = catalogRow({
  poster_url: "https://image.tmdb.org/t/p/original/poster.jpg",
  poster_preview_url: "https://image.tmdb.org/t/p/w500/poster.jpg",
  has_draft: true,
  library_item_id: 1,
});
const arrival = catalogRow({
  entry_key: "imdb-tt2543164",
  title: "Arrival",
  tmdb_id: null,
  imdb_id: "tt2543164",
  year: 2016,
});

describe("catalog sidebar", () => {
  beforeEach(async () => {
    queryClient.clear();
    settingsState.load(appSettings());
    uiState.catalogFilters = defaultCatalogFilters();
    uiState.searchQuery = "";
    uiState.searchField = "title";
    await navigate("/overturedb/movies");
    queryClient.setQueryData(getPublicDatasetStatusOptions().queryKey, publicDatasetStatus());
    queryClient.setQueryData(
      listCatalogEntriesOptions({ query: { media_type: "movie" } }).queryKey,
      [alien, arrival],
    );
    queryClient.setQueryData(
      listCatalogEntriesOptions({ query: { media_type: "show" } }).queryKey,
      [],
    );
    mockFetchRoutes({ "/api/library/libraries": [] });
  });
  it("shows full catalog rows and their previews, and opens entries and art or themes", async () => {
    const { container } = renderWithQueryClient(Sidebar, { movies: [mediaItem()] });
    expect(await screen.findByRole("button", { name: "Select Arrival" })).toBeInTheDocument();
    await waitFor(() =>
      expect(container.querySelector(`img[src="${alien.poster_preview_url}"]`)).not.toBeNull(),
    );
    expect(screen.getByText("Draft")).toBeInTheDocument();
    expect(sidebarState.current).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Select Arrival" }));
    await waitFor(() => expect(route.pathname).toBe("/overturedb/movies/imdb-tt2543164"));
    await fireEvent.click(screen.getByRole("button", { name: "Open art for Alien" }));
    await waitFor(() => expect(route.pathname).toBe("/overturedb/movies/tmdb-348/art/poster"));
    await fireEvent.click(screen.getByRole("button", { name: "Open themes for Alien" }));
    await waitFor(() => expect(route.pathname).toBe("/overturedb/movies/tmdb-348/themes"));
  });
  it("offers catalog fields, filters drafts and library membership, and leaves library filters separate", async () => {
    renderWithQueryClient(Sidebar);
    await fireEvent.click(screen.getByRole("button", { name: "Choose search field" }));
    expect(screen.queryByRole("menuitemradio", { name: "Director" })).toBeNull();
    await fireEvent.click(screen.getByRole("menuitemradio", { name: "TMDB, TVDB or IMDb ID" }));
    await fireEvent.input(screen.getByLabelText("Search sidebar"), {
      target: { value: "tt2543164" },
    });
    expect(screen.getByRole("button", { name: "Select Arrival" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select Alien" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    const libraryFilters = JSON.parse(JSON.stringify(uiState.currentFilters));
    renderWithQueryClient(FiltersPopup);
    expect(screen.queryByText("Monitor status")).toBeNull();
    expect(screen.queryByRole("button", { name: "Run" })).toBeNull();
    await fireEvent.click(
      within(screen.getByRole("radiogroup", { name: "Has draft" })).getByRole("radio", {
        name: "Present",
      }),
    );
    await fireEvent.click(screen.getByRole("button", { name: "Apply filters" }));
    expect(screen.getByRole("button", { name: "Select Alien" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Select Arrival" })).toBeNull();
    expect(uiState.currentFilters).toEqual(libraryFilters);
  });
  it("lists catalog collections without a media server and handles disabled datasets", async () => {
    queryClient.setQueryData(
      listCatalogEntriesOptions({ query: { media_type: "collection" } }).queryKey,
      [
        catalogRow({
          media_type: "collection",
          entry_key: "tmdb-10",
          tmdb_id: 10,
          title: "Star Wars",
          library_collection_id: 12,
        }),
      ],
    );
    renderWithQueryClient(Sidebar);
    await fireEvent.click(screen.getByRole("button", { name: "Collections" }));
    expect(await screen.findByRole("button", { name: "Select Star Wars" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Select Star Wars" }));
    await waitFor(() => expect(route.pathname).toBe("/overturedb/movies/collections/tmdb-10"));
    queryClient.setQueryData(
      getPublicDatasetStatusOptions().queryKey,
      publicDatasetStatus({ enabled: false }),
    );
    expect(await screen.findByText("Enable OvertureDB to browse the catalog.")).toBeInTheDocument();
    expect(screen.queryByRole("radiogroup", { name: "Sidebar source" })).toBeNull();
  });
});
