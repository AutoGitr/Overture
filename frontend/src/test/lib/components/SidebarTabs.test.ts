import { fireEvent, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SidebarTabs from "../../../lib/components/SidebarTabs.svelte";
import { goToCatalog, navigate, route } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { appSettings } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

describe("sidebar source and tabs", () => {
  beforeEach(async () => {
    settingsState.load(appSettings());
    await navigate("/movies");
  });
  it("offers OvertureDB only while enabled", () => {
    renderWithQueryClient(SidebarTabs, { totalMovies: 1, totalShows: 2 });
    expect(screen.queryByRole("radiogroup", { name: "Sidebar source" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Collections" })).toBeNull();
  });
  it("browses catalog movies, collections, and shows while keeping the mobile sidebar visible", async () => {
    renderWithQueryClient(SidebarTabs, { totalMovies: 1, totalShows: 2, datasetEnabled: true });
    await fireEvent.click(screen.getByRole("radio", { name: "OvertureDB" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/overturedb/movies"));
    await fireEvent.click(screen.getByRole("button", { name: "Collections" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/overturedb/movies/collections"));
    await fireEvent.click(screen.getByRole("button", { name: "Items" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/overturedb/movies"));
    uiState.mobileShowDetail = true;
    await fireEvent.click(screen.getByRole("button", { name: "Shows 2" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/overturedb/shows"));
    expect(uiState.mobileShowDetail).toBe(false);
    expect(screen.queryByRole("button", { name: "Collections" })).toBeNull();
    await fireEvent.click(screen.getByRole("radio", { name: "Library" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/shows"));
  });
  it("uses the server capability for Jellyfin collections and preserves collections on a source switch", async () => {
    settingsState.load(appSettings({ media_server: "jellyfin", collections_supported: true }));
    renderWithQueryClient(SidebarTabs, { totalMovies: 1, totalShows: 1, datasetEnabled: true });
    await fireEvent.click(screen.getByRole("button", { name: "Collections" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/movies/collections"));
    await fireEvent.click(screen.getByRole("radio", { name: "OvertureDB" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/overturedb/movies/collections"));
    await fireEvent.click(screen.getByRole("radio", { name: "Library" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/movies/collections"));
    goToCatalog("movie", "collections");
    await vi.waitFor(() => expect(route.pathname).toBe("/overturedb/movies/collections"));
    await fireEvent.click(screen.getByRole("button", { name: "Shows 1" }));
    await vi.waitFor(() => expect(route.pathname).toBe("/overturedb/shows"));
  });
});
