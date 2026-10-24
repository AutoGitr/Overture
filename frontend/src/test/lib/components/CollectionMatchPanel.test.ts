import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import { getCollectionOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import { queryClient } from "../../../lib/rest/queryClient";
import CollectionPage from "../../../lib/router/pages/CollectionPage.svelte";
import { navigate, route } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { notificationState } from "../../../lib/stores/notificationState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import { appSettings, collectionDetail, mediaItem } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

describe("collection matching and members", () => {
  beforeEach(async () => {
    queryClient.clear();
    settingsState.load(appSettings({ media_server: "jellyfin", collections_supported: true }));
    await navigate("/movies/collections/:collectionSlug", {
      params: { collectionSlug: "12-star-wars" },
    });
  });
  function setup() {
    let detail = collectionDetail({
      id: 12,
      title: "Star Wars",
      server_type: "jellyfin",
      tmdb_collection_id: 10,
      theme_unavailable: "Set JELLYFIN_COLLECTIONS_PATH",
      members: [
        mediaItem({
          id: 1,
          title: "A New Hope",
          media_type: "movie",
          tmdb_id: 11,
          year: 1977,
          poster_hash: "member-poster",
        }),
      ],
      catalog_title: "Star Wars",
      catalog_entry_key: "tmdb-10",
      server_link: "https://server.test/collection",
    });
    const { calls } = mockFetchRoutes({
      "/api/collections/12": () => Response.json(detail),
      "/api/collections/12/match": ({ init }: { init: RequestInit }) => {
        detail =
          init.method === "DELETE"
            ? { ...detail, tmdb_match: "auto", tmdb_collection_id: 10 }
            : {
                ...detail,
                tmdb_collection_id: JSON.parse(String(init.body)).tmdb_collection_id,
                tmdb_match:
                  JSON.parse(String(init.body)).tmdb_collection_id === null
                    ? "unmatched"
                    : "manual",
              };
        return Response.json(detail);
      },
      "/api/tmdb/search": {
        results: [
          { kind: "item", tmdb_id: 1, title: "Movie", media_type: "movie" },
          { kind: "collection", tmdb_id: 2344, title: "The Matrix" },
        ],
      },
    });
    renderWithQueryClient(CollectionPage);
    return { calls };
  }
  it("shows the folder requirement, links the server and catalog, and opens members", async () => {
    setup();
    expect(await screen.findByText("Set JELLYFIN_COLLECTIONS_PATH")).toBeInTheDocument();
    expect(screen.queryByLabelText("Search collection themes")).toBeNull();
    expect(screen.getAllByRole("link", { name: "Open in Jellyfin" })[0]).toHaveAttribute(
      "href",
      "https://server.test/collection",
    );
    await fireEvent.click(screen.getByRole("button", { name: "Open in OvertureDB" }));
    await waitFor(() => expect(route.pathname).toBe("/overturedb/movies/collections/tmdb-10"));
    await navigate("/movies/collections/:collectionSlug", {
      params: { collectionSlug: "12-star-wars" },
    });
    const member = await screen.findByRole("button", { name: "A New Hope (1977) In library" });
    expect(within(member).getByRole("presentation")).toHaveAttribute(
      "src",
      "/api/library/items/1/local-image/poster?t=member-poster&size=display",
    );
    await fireEvent.click(member);
    await waitFor(() => expect(route.pathname).toBe("/movies/1-a-new-hope"));
  });
  it("manually matches by ID without TMDB configured, unmatches, and resets to auto", async () => {
    const { calls } = setup();
    const input = await screen.findByLabelText("TMDB collection ID");
    await fireEvent.input(input, { target: { value: "2344" } });
    await fireEvent.click(screen.getByRole("button", { name: "Match collection" }));
    expect(await screen.findByText("Match: Manual")).toBeInTheDocument();
    expect(calls.find((call) => call.init.method === "PUT")?.init.body).toBe(
      JSON.stringify({ media_type: "movie", tmdb_collection_id: 2344 }),
    );
    await fireEvent.click(screen.getByRole("button", { name: "Unmatch" }));
    expect(await screen.findByText("Match: Manually unmatched")).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Reset to auto" }));
    expect(await screen.findByText("Match: Automatic")).toBeInTheDocument();
    expect(
      queryClient.getQueryData(
        getCollectionOptions({ path: { collection_id: 12 }, query: { media_type: "movie" } })
          .queryKey,
      ),
    ).toMatchObject({ tmdb_collection_id: 10, tmdb_match: "auto" });
  });

  it("does not offer TMDB matching for show collections", async () => {
    await navigate("/shows/collections/:collectionSlug", {
      params: { collectionSlug: "12-shows" },
    });
    mockFetchRoutes({
      "/api/collections/12": collectionDetail({
        id: 12,
        title: "Shows",
        media_type: "show",
        theme_unavailable: "Read only",
      }),
    });
    renderWithQueryClient(CollectionPage);
    await screen.findByRole("heading", { name: "Shows" });
    expect(screen.queryByRole("region", { name: "TMDB collection match" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Unmatch" })).toBeNull();
  });
  it("searches TMDB collections and ignores item search results", async () => {
    settingsState.load(appSettings({ tmdb_configured: true }));
    setup();
    const input = await screen.findByLabelText("Search TMDB collections");
    await fireEvent.input(input, { target: { value: "Matrix" } });
    await fireEvent.click(screen.getByRole("button", { name: "Search TMDB" }));
    await fireEvent.click(
      await screen.findByRole("button", { name: "Match The Matrix (TMDB 2344)" }),
    );
    expect(await screen.findByText("Match: Manual")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Match Movie/ })).toBeNull();
  });
  it("keeps the match on refused changes and reports both mutation failures", async () => {
    const detail = collectionDetail({
      id: 12,
      tmdb_match: "manual",
      theme_unavailable: "Read only",
    });
    const { calls } = mockFetchRoutes({
      "/api/collections/12": detail,
      "/api/collections/12/match": () =>
        Response.json({ detail: "Match refused" }, { status: 422 }),
    });
    renderWithQueryClient(CollectionPage);
    await fireEvent.click(await screen.findByRole("button", { name: "Unmatch" }));
    await waitFor(() =>
      expect(notificationState.toasts.some((toast) => toast.message === "Match refused")).toBe(
        true,
      ),
    );
    await fireEvent.click(screen.getByRole("button", { name: "Reset to auto" }));
    await waitFor(() => expect(calls.some((call) => call.init.method === "DELETE")).toBe(true));
    expect(notificationState.toasts.some((toast) => toast.message === "Match refused")).toBe(true);
    expect(screen.getByText("Match: Manual")).toBeInTheDocument();
  });
});
