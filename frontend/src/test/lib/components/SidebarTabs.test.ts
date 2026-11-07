import { fireEvent, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SidebarTabs from "../../../lib/components/SidebarTabs.svelte";
import { goToCollection, navigate, route } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { appSettings } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

describe("sidebar tabs", () => {
  beforeEach(async () => {
    settingsState.load(appSettings());
    uiState.setCollectionView("groups");
    localStorage.clear();
    await navigate("/movies");
  });

  it("offers collections only where the media server supports them", () => {
    settingsState.load(appSettings({ collections_supported: false }));
    renderWithQueryClient(SidebarTabs, { totalMovies: 1, totalShows: 2, totalCollections: 0 });

    expect(screen.queryByRole("button", { name: "Collections" })).toBeNull();
  });

  it("opens the last view of the collections, then switches between groups and collections", async () => {
    settingsState.load(appSettings({ media_server: "jellyfin", collections_supported: true }));
    renderWithQueryClient(SidebarTabs, { totalMovies: 1, totalShows: 1, totalCollections: 1 });

    await fireEvent.click(screen.getByRole("button", { name: "Collections" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/collections"));
    expect(uiState.collectionView).toBe("groups");
    const toggle = screen.getByRole("button", { name: "Show collections" });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: /^Movies/ })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    goToCollection({ id: 12, title: "Star Wars" });
    await vi.waitFor(() => expect(route.pathname).toBe("/collections/12-star-wars"));
    await fireEvent.click(toggle);

    expect(route.pathname).toBe("/collections/12-star-wars");
    expect(uiState.collectionView).toBe("collections");
    expect(localStorage.getItem("overture_collection_view")).toBe('"collections"');
    await fireEvent.click(screen.getByRole("button", { name: "Show groups" }));
    expect(uiState.collectionView).toBe("groups");

    await fireEvent.click(screen.getByRole("button", { name: /^Movies/ }));
    await vi.waitFor(() => expect(route.pathname).toBe("/movies"));
    await fireEvent.click(screen.getByRole("button", { name: "Collections" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/collections"));
    expect(uiState.collectionView).toBe("groups");
  });

  it("opens the catalog's collections from its movies, keeping the mobile sidebar visible", async () => {
    await navigate("/overturedb/movies");
    renderWithQueryClient(SidebarTabs, { totalMovies: 1, totalShows: 2, totalCollections: 0 });

    await fireEvent.click(screen.getByRole("button", { name: "Collections" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/overturedb/movies/collections"));
    // The catalog's collections have no groups to switch to.
    await fireEvent.click(screen.getByRole("button", { name: "Collections" }));
    expect(route.pathname).toBe("/overturedb/movies/collections");
    await fireEvent.click(screen.getByRole("button", { name: /^Movies/ }));
    await vi.waitFor(() => expect(route.pathname).toBe("/overturedb/movies"));

    uiState.mobileShowDetail = true;
    await fireEvent.click(screen.getByRole("button", { name: "Shows 2" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/overturedb/shows"));
    expect(uiState.mobileShowDetail).toBe(false);
    expect(screen.queryByRole("button", { name: "Collections" })).toBeNull();
  });

  it("keeps what is typed while the collections page loads", async () => {
    settingsState.load(appSettings({ collections_supported: true }));
    renderWithQueryClient(SidebarTabs, { totalMovies: 1, totalShows: 1, totalCollections: 1 });

    await fireEvent.click(screen.getByRole("button", { name: "Collections" }));
    uiState.searchQuery = "Star Wars";
    await vi.waitFor(() => expect(route.pathname).toBe("/collections"));
    uiState.followSection();

    expect(uiState.searchQuery).toBe("Star Wars");
  });
});
