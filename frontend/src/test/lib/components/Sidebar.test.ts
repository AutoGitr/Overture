import { appSettings } from "../../helpers/fixtures";
import { QueryClient } from "@tanstack/svelte-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getTmdbCollectionOptions,
  listCollectionsOptions,
  searchTmdbOptions,
} from "../../../generated/rest/@tanstack/svelte-query.gen";
import { navigate, route } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { sidebarState } from "../../../lib/stores/sidebarState.svelte";
import { uiState } from "../../../lib/stores/uiState.svelte";
import { collection, mediaItem } from "../../helpers/fixtures";
import SidebarHarness from "../../helpers/SidebarHarness.svelte";

const movie = mediaItem({
  id: 1,
  title: "Alien",
  media_type: "movie",
});

const show = mediaItem({
  id: 2,
  title: "Twin Peaks",
  media_type: "show",
});

describe("Sidebar", () => {
  let client: QueryClient;

  beforeEach(async () => {
    client = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: Infinity,
        },
      },
    });
    client.setQueryData(listCollectionsOptions({ query: { media_type: "movie" } }).queryKey, [
      collection({
        id: 1,
        title: "Action",
        media_type: "movie",
        server_type: "plex",
      }),
    ]);
    uiState.closePopup();
    uiState.mobileShowDetail = false;
    await navigate("/movies", { replace: true });
    uiState.searchQuery = "";
    uiState.clearFilters();
    settingsState.load(
      appSettings({
        workflow: "art",
        media_server: null,
        collections_supported: false,
      }),
    );
  });

  it("hides grouped collections until the group is opened and keeps that group while opening art", async () => {
    client.setQueryData(listCollectionsOptions({ query: { media_type: "movie" } }).queryKey, [
      collection({ id: 1, title: "Saga", collection_group: "Weekend", art_status: "complete" }),
      collection({ id: 2, title: "Loose" }),
    ]);
    await navigate("/movies/collections");
    render(SidebarHarness, { props: { client, movies: [movie] } });
    expect(await screen.findByRole("button", { name: "Open group Weekend" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Select collection Saga" })).toBeNull();
    expect(screen.getByRole("button", { name: "Select collection Loose" })).toBeVisible();
    await fireEvent.click(screen.getByRole("button", { name: "Open group Weekend" }));
    expect(await screen.findByRole("button", { name: "Select collection Saga" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Select collection Loose" })).toBeNull();
    const art = screen.getByRole("button", { name: "Open art for Saga" });
    expect(art).toHaveAttribute("data-status", "success");
    await fireEvent.click(art);
    await waitFor(() => expect(route.pathname).toBe("/movies/collections/1-saga/art/poster"));
    expect(screen.getByRole("button", { name: "Select collection Saga" })).toBeVisible();
    await fireEvent.click(screen.getByRole("button", { name: "Back to results" }));
    expect(await screen.findByRole("button", { name: "Open group Weekend" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Select collection Saga" })).toBeNull();
  });

  it("shows collection art and theme badges except themes on Emby", async () => {
    client.setQueryData(listCollectionsOptions({ query: { media_type: "movie" } }).queryKey, [
      collection({ id: 1, title: "Plex", server_type: "plex" }),
      collection({ id: 2, title: "Emby", server_type: "emby" }),
    ]);
    await navigate("/movies/collections");
    render(SidebarHarness, { props: { client } });
    expect(await screen.findByRole("button", { name: "Open art for Emby" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Open themes for Emby" })).toBeNull();
    await fireEvent.click(screen.getByRole("button", { name: "Open themes for Plex" }));
    await waitFor(() => expect(route.pathname).toBe("/movies/collections/1-plex/themes"));
  });

  it("remembers the scroll position of each tab separately", async () => {
    vi.useFakeTimers();
    try {
      const movies = Array.from({ length: 40 }, (_, index) =>
        mediaItem({ id: index + 10, title: `Movie ${index}` }),
      );
      const { container } = render(SidebarHarness, {
        props: { client, movies, totalMovies: movies.length, shows: [show], totalShows: 1 },
      });
      const list = container.querySelector(".sidebar-list")!;
      const viewport = list.querySelector<HTMLElement>("[data-virtual-viewport]") ?? list;
      viewport.scrollTop = 400;
      await fireEvent.scroll(viewport);
      vi.advanceTimersByTime(250);

      expect(sessionStorage.getItem("overture_sidebar_scroll:library:movie:items")).toBe("400");
      expect(sessionStorage.getItem("overture_sidebar_scroll:library:show:items")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });

  it("shares every filtered result with assets, including virtualized rows and search fields", async () => {
    const movies = Array.from({ length: 80 }, (_, index) =>
      mediaItem({
        id: index + 10,
        title: `Movie ${index}`,
        director: index % 2 === 0 ? "Ridley Scott" : "Other",
        monitored: index % 3 === 0,
      }),
    );
    const { unmount } = render(SidebarHarness, {
      props: { client, movies, totalMovies: movies.length, shows: [show], totalShows: 1 },
    });
    await waitFor(() => expect(sidebarState.current?.itemIds).toHaveLength(80));
    uiState.currentFilters.monitored = "unmonitored";
    await fireEvent.click(screen.getByRole("button", { name: "Choose search field" }));
    await fireEvent.click(screen.getByRole("menuitemradio", { name: "Director" }));
    expect(screen.getByLabelText("Search sidebar")).toHaveFocus();
    await fireEvent.input(screen.getByLabelText("Search sidebar"), { target: { value: "Ridley" } });
    const expected = movies.filter((item) => !item.monitored && item.director === "Ridley Scott");
    await waitFor(() =>
      expect(sidebarState.current?.itemIds.toSorted()).toEqual(
        expected.map((item) => item.id).toSorted(),
      ),
    );
    await fireEvent.click(screen.getByRole("button", { name: /Shows/ }));
    await waitFor(() => expect(sidebarState.current).toEqual({ type: "show", itemIds: [show.id] }));
    unmount();
    expect(sidebarState.current).toBeNull();
  });

  it("keeps the rendered search input in uiState and clears it on tab switch", async () => {
    render(SidebarHarness, {
      props: { client, movies: [movie], totalMovies: 1, totalShows: 1, shows: [show] },
    });

    const search = screen.getByLabelText("Search sidebar");
    await fireEvent.input(search, { target: { value: "Alien" } });
    uiState.mobileShowDetail = true;

    expect(uiState.searchQuery).toBe("Alien");
    expect(search).toHaveValue("Alien");

    await fireEvent.click(screen.getByRole("button", { name: /Shows/ }));

    await waitFor(() => expect(uiState.sidebarTab).toBe("show"));
    expect(uiState.sidebarMode).toBe("items");
    expect(uiState.searchQuery).toBe("");
    expect(screen.getByLabelText("Search sidebar")).toHaveValue("");
    expect(route.pathname).toBe("/shows");
    expect(uiState.mobileShowDetail).toBe(false);
  });

  it("defers poster requests until a virtual row remains visible", async () => {
    const { container } = render(SidebarHarness, {
      props: {
        client,
        movies: [mediaItem({ ...movie, server_item_id: "plex-1" })],
        totalMovies: 1,
      },
    });

    expect(container.querySelector(".item-poster img")).not.toBeInTheDocument();
    await waitFor(() => {
      const poster = container.querySelector(".item-poster img");
      expect(poster).toHaveAttribute("loading", "eager");
      expect(poster).toHaveAttribute(
        "src",
        "/api/library/items/1/provider-art?type=poster&t=0&size=display",
      );
    });
  });

  it("keeps the library search field when clearing its text", async () => {
    render(SidebarHarness, { props: { client, movies: [movie], totalMovies: 1 } });
    await fireEvent.click(screen.getByRole("button", { name: "Choose search field" }));
    await fireEvent.click(screen.getByRole("menuitemradio", { name: "Director" }));
    await fireEvent.input(screen.getByLabelText("Search sidebar"), {
      target: { value: "Ridley" },
    });

    await fireEvent.click(screen.getByRole("button", { name: "Clear search" }));

    expect(uiState.searchQuery).toBe("");
    expect(uiState.searchField).toBe("director");
    expect(screen.getByLabelText("Search sidebar")).toHaveValue("");
    expect(screen.getByLabelText("Search sidebar")).toHaveFocus();
    expect(screen.queryByRole("button", { name: "Clear search" })).toBeNull();
  });

  it("clears search when switching into collections mode", async () => {
    settingsState.load(
      appSettings({
        workflow: "art",
        media_server: "plex",
        collections_supported: true,
      }),
    );
    render(SidebarHarness, {
      props: { client, movies: [movie], totalMovies: 1, totalShows: 1, shows: [show] },
    });

    await fireEvent.input(screen.getByLabelText("Search sidebar"), {
      target: { value: "Action" },
    });
    await fireEvent.click(screen.getByRole("button", { name: "Collections" }));

    await waitFor(() => expect(uiState.sidebarMode).toBe("collections"));
    expect(sidebarState.current).toBeNull();
    expect(uiState.searchQuery).toBe("");
    expect(screen.getByLabelText("Search sidebar")).toHaveValue("");
    await waitFor(() => {
      expect(screen.getByText("Action")).toBeInTheDocument();
    });
  });

  it("marks the row of the item the URL opens", async () => {
    const { container } = render(SidebarHarness, {
      props: { client, movies: [movie], totalMovies: 1, totalShows: 1, shows: [show] },
    });
    expect(container.querySelector(".sidebar-item.active")).toBeNull();

    await navigate("/movies/:itemSlug", { params: { itemSlug: "1-alien" } });

    await waitFor(() =>
      expect(container.querySelector(".sidebar-item.active")).toHaveTextContent("Alien"),
    );
  });

  it("reveals an item that is already open behind the mobile sidebar", async () => {
    await navigate("/movies/:itemSlug", {
      params: { itemSlug: "1-alien" },
      replace: true,
    });
    uiState.mobileShowDetail = false;

    render(SidebarHarness, {
      props: { client, movies: [movie], totalMovies: 1, totalShows: 1, shows: [show] },
    });

    await fireEvent.click(screen.getByRole("button", { name: "Select Alien" }));

    expect(uiState.mobileShowDetail).toBe(true);
  });

  it("opens filters from the labelled icon button", async () => {
    render(SidebarHarness, {
      props: { client, movies: [movie], totalMovies: 1, totalShows: 1, shows: [show] },
    });

    await fireEvent.click(screen.getByLabelText("Open filters"));

    expect(uiState.openPopup).toBe("filters");
  });

  it("opens an item when clicking the item button", async () => {
    render(SidebarHarness, {
      props: { client, movies: [movie], totalMovies: 1, totalShows: 1, shows: [show] },
    });

    uiState.mobileShowDetail = false;
    await fireEvent.click(screen.getByRole("button", { name: "Select Alien" }));

    expect(uiState.mobileShowDetail).toBe(true);
  });

  it("opens art when clicking the art badge", async () => {
    render(SidebarHarness, {
      props: { client, movies: [movie], totalMovies: 1, totalShows: 1, shows: [show] },
    });

    uiState.mobileShowDetail = false;
    const artButton = screen.getByRole("button", { name: "Open art for Alien" });
    await fireEvent.click(artButton);

    expect(uiState.mobileShowDetail).toBe(true);
  });

  it("renders poster link for local and media server art, but shows placeholder when only remote poster_url exists", async () => {
    // 1. Local image has highest priority
    const { unmount: unmount1 } = render(SidebarHarness, {
      props: {
        client,
        movies: [
          mediaItem({
            ...movie,
            poster_hash: "hash123",
            server_item_id: "plex-1",
            poster_url: "https://remote.test/poster.jpg",
          }),
        ],
        totalMovies: 1,
      },
    });

    let posterLink = screen.getByRole("link", { name: "Open poster for Alien in new tab" });
    expect(posterLink).toHaveAttribute("target", "_blank");
    expect(posterLink).toHaveAttribute("rel", "noreferrer");
    expect(posterLink.getAttribute("href")).toContain("/api/library/items/1/local-image/poster");
    unmount1();

    // 2. Media server has second priority when no local poster
    const { unmount: unmount2 } = render(SidebarHarness, {
      props: {
        client,
        movies: [
          mediaItem({
            ...movie,
            poster_hash: null,
            server_item_id: "plex-1",
            poster_url: "https://remote.test/poster.jpg",
          }),
        ],
        totalMovies: 1,
      },
    });

    posterLink = screen.getByRole("link", { name: "Open poster for Alien in new tab" });
    expect(posterLink.getAttribute("href")).toContain(
      "/api/library/items/1/provider-art?type=poster",
    );
    unmount2();

    // 3. When neither local nor media server exists, only remote URL is present:
    // Sidebar should NOT link to remote poster and should render a placeholder instead
    render(SidebarHarness, {
      props: {
        client,
        movies: [
          mediaItem({
            ...movie,
            folder_path: "/movies/Alien",
            poster_hash: null,
            server_item_id: null,
            poster_url: "https://remote.test/poster.jpg",
          }),
        ],
        totalMovies: 1,
      },
    });

    expect(
      screen.queryByRole("link", { name: "Open poster for Alien in new tab" }),
    ).not.toBeInTheDocument();
  });

  it("preserves rendered poster image elements without flashing when an item leaves the filtered list", async () => {
    const movie1 = mediaItem({
      id: 10,
      title: "Movie 1",
      media_type: "movie",
      server_item_id: "p1",
    });
    const movie2 = mediaItem({
      id: 20,
      title: "Movie 2",
      media_type: "movie",
      server_item_id: "p2",
    });
    const movie3 = mediaItem({
      id: 30,
      title: "Movie 3",
      media_type: "movie",
      server_item_id: "p3",
    });

    uiState.currentFilters.art = "incomplete";
    const movies = [movie1, movie2, movie3];

    const { container, rerender } = render(SidebarHarness, {
      props: {
        client,
        movies,
        totalMovies: 3,
      },
    });

    await waitFor(() => {
      const imgs = container.querySelectorAll(".item-poster img");
      expect(imgs.length).toBe(3);
    });

    const initialImgs = Array.from(container.querySelectorAll(".item-poster img"));

    // Complete movie 1 so it leaves the filtered list (simulating artwork auto-advance completion)
    const completedMovie1 = mediaItem({
      ...movie1,
      art_status: "complete",
      poster_url: "https://example.com/poster.jpg",
      poster_hash: "hash1",
      background_url: "https://example.com/bg.jpg",
      background_hash: "bghash1",
    });

    await rerender({ movies: [completedMovie1, movie2, movie3], totalMovies: 3 });

    // Movie 2 and Movie 3 should immediately retain their rendered img elements without flashing to placeholders
    const posterEls = Array.from(container.querySelectorAll(".item-poster"));
    expect(posterEls.length).toBe(2);

    const movie2Img = posterEls[0]?.querySelector("img");
    const movie3Img = posterEls[1]?.querySelector("img");

    expect(movie2Img).toBe(initialImgs[1]);
    expect(movie3Img).toBe(initialImgs[2]);
  });
});

describe("Sidebar TMDB search", () => {
  let client: QueryClient;
  const stored = mediaItem({ id: 1, title: "The Matrix", media_type: "movie", tmdb_id: 603 });
  const tmdbItem = (tmdbId: number, title: string, existing: number | null = null) => ({
    kind: "item" as const,
    media_type: "movie" as const,
    tmdb_id: tmdbId,
    title,
    year: 2003,
    poster_url: null,
    poster_preview_url: null,
    existing_item_id: existing,
    catalog_entry_key: null,
  });

  beforeEach(async () => {
    client = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity } } });
    client.setQueryData(
      searchTmdbOptions({ query: { media_type: "movie", query: "matrix" } }).queryKey,
      {
        results: [
          tmdbItem(603, "The Matrix", 1),
          tmdbItem(604, "The Matrix Reloaded"),
          {
            kind: "collection",
            tmdb_id: 2344,
            title: "The Matrix Collection",
            poster_url: null,
            poster_preview_url: null,
          },
        ],
      },
    );
    client.setQueryData(getTmdbCollectionOptions({ path: { collection_id: 2344 } }).queryKey, {
      tmdb_id: 2344,
      title: "The Matrix Collection",
      items: [tmdbItem(605, "The Matrix Revolutions")],
    });
    await navigate("/movies", { replace: true });
    settingsState.load(appSettings({ media_server: null, collections_supported: false }));
    settingsState.current.tmdb_configured = true;
    uiState.clearFilters();
    uiState.searchField = "tmdb";
    uiState.searchQuery = "matrix";
  });

  it("lists stored items as rows, new titles, and collections that expand", async () => {
    render(SidebarHarness, { props: { client, movies: [stored], totalMovies: 1 } });

    expect(await screen.findByRole("button", { name: "Open art for The Matrix" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Select The Matrix Reloaded" })).toBeVisible();
    expect(sidebarState.current).toBeNull();

    await fireEvent.click(
      screen.getByRole("button", { name: "Open Collection: The Matrix Collection" }),
    );
    expect(
      await screen.findByRole("button", { name: "Select The Matrix Revolutions" }),
    ).toBeVisible();
    expect(screen.getByText("The Matrix Collection")).toBeVisible();

    await fireEvent.click(screen.getByRole("button", { name: "Back to results" }));
    expect(await screen.findByRole("button", { name: "Select The Matrix Reloaded" })).toBeVisible();
  });

  it("keeps TMDB search active when clearing the query", async () => {
    render(SidebarHarness, { props: { client, movies: [stored], totalMovies: 1 } });
    await screen.findByRole("button", { name: "Select The Matrix Reloaded" });

    await fireEvent.click(screen.getByRole("button", { name: "Clear search" }));

    expect(uiState.searchQuery).toBe("");
    expect(uiState.searchField).toBe("tmdb");
    expect(screen.getByLabelText("Search sidebar")).toHaveAttribute(
      "placeholder",
      "Search TMDB by title or ID...",
    );
    expect(screen.queryByRole("button", { name: "Open filters" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Choose sort order" })).toBeNull();
    expect(sidebarState.current).toBeNull();
  });

  it("opens a new title by its TMDB ID", async () => {
    render(SidebarHarness, { props: { client, movies: [stored], totalMovies: 1 } });

    await fireEvent.click(
      await screen.findByRole("button", { name: "Select The Matrix Reloaded" }),
    );

    await waitFor(() => expect(route.pathname).toBe("/movies/tmdb-604-the-matrix-reloaded"));
    expect(uiState.mobileShowDetail).toBe(true);
  });

  it("shows a title stored after the search as its library row at once", async () => {
    const view = render(SidebarHarness, { props: { client, movies: [stored], totalMovies: 1 } });
    await screen.findByRole("button", { name: "Select The Matrix Reloaded" });
    expect(
      screen.getByRole("button", { name: "Open art for The Matrix Reloaded" }),
    ).toHaveAttribute("data-status", "danger");

    // The first selection stores it; the cached search result still says it is new.
    const reloaded = mediaItem({
      id: 2,
      title: "The Matrix Reloaded",
      media_type: "movie",
      tmdb_id: 604,
      art_status: "complete",
      poster_url: "https://image.tmdb.org/t/p/original/chosen.jpg",
      poster_preview_url: "https://image.tmdb.org/t/p/w342/chosen.jpg",
    });
    await view.rerender({ client, movies: [stored, reloaded], totalMovies: 2 });

    const art = await screen.findByRole("button", { name: "Open art for The Matrix Reloaded" });
    expect(art).toHaveAttribute("data-status", "success");
    expect(
      screen.getByRole("link", { name: "Open poster for The Matrix Reloaded in new tab" }),
    ).toHaveAttribute("href", "https://image.tmdb.org/t/p/original/chosen.jpg");
  });
});
