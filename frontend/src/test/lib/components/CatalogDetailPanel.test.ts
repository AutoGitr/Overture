import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import {
  getCatalogEntryOptions,
  getPublicDatasetStatusOptions,
} from "../../../generated/rest/@tanstack/svelte-query.gen";
import type { CatalogDraftUpdate } from "../../../generated/rest/types.gen";
import CatalogEntryPage from "../../../lib/router/pages/CatalogEntryPage.svelte";
import CatalogCollectionPage from "../../../lib/router/pages/CatalogCollectionPage.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { navigate, route } from "../../../lib/router/routes";
import { settingsState } from "../../../lib/stores/settingsState.svelte";
import { notificationState } from "../../../lib/stores/notificationState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import {
  appSettings,
  artCandidate,
  catalogDetail,
  catalogEntry,
  publicDatasetStatus,
} from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const poster = "https://image.tmdb.org/t/p/original/chosen.jpg";

describe("catalog detail drafts", () => {
  beforeEach(async () => {
    queryClient.clear();
    settingsState.load(appSettings());
    queryClient.setQueryData(getPublicDatasetStatusOptions().queryKey, publicDatasetStatus());
    await navigate("/overturedb/movies/:entrySlug/art/:subtab", {
      params: { entrySlug: "tmdb-348", subtab: "poster" },
    });
  });

  function server(initial = catalogDetail()) {
    let detail = initial;
    const result = mockFetchRoutes({
      "/api/public-dataset/catalog/movie/tmdb-348": () => Response.json(detail),
      "/api/public-dataset/catalog/movie/tmdb-348/draft": ({ init }: { init: RequestInit }) => {
        detail = {
          ...detail,
          draft:
            init.method === "DELETE"
              ? null
              : { ...(detail.draft ?? detail.entry), ...JSON.parse(String(init.body)) },
        };
        return Response.json(detail);
      },
      "/api/tmdb/movie/348/art/poster/sources": {
        sources: { tmdb: [artCandidate({ url: poster })] },
      },
      "/api/themes/search": { results: [] },
    });
    return result;
  }

  it("saves a poster draft, contributes it, and discards it without changing the library", async () => {
    settingsState.load(appSettings({ tmdb_configured: true }));
    const { calls } = server(catalogDetail({ library_item_id: 9 }));
    renderWithQueryClient(CatalogEntryPage);
    await fireEvent.click(
      await screen.findByRole("button", { name: "Use artwork 1000x1500 from tmdb" }),
    );
    expect(await screen.findByText("Draft", { selector: ".badge" })).toBeInTheDocument();
    const issue = new URL(
      screen.getByRole("link", { name: "Contribute to OvertureDB" }).getAttribute("href") ?? "",
    );
    expect(issue.searchParams.get("poster_url")).toBe(poster);
    expect(
      calls
        .filter((call) => call.init.method === "PUT")
        .map((call) => JSON.parse(String(call.init.body))),
    ).toEqual([{ poster_url: poster }]);
    await fireEvent.click(screen.getByRole("button", { name: "Discard draft" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Discard draft" })).toBeNull());
    expect(calls.some((call) => call.url.includes("/api/library"))).toBe(false);
    await fireEvent.click(screen.getByRole("button", { name: "Open in library" }));
    await waitFor(() => expect(route.pathname).toBe("/movies/9-alien"));
  });

  it("records a pasted theme and can clear it in the draft", async () => {
    await navigate("/overturedb/movies/:entrySlug/themes", { params: { entrySlug: "tmdb-348" } });
    const { calls } = server(
      catalogDetail({ entry: catalogEntry({ youtube_id_themerrdb: "themerr12345" }) }),
    );
    renderWithQueryClient(CatalogEntryPage);
    const input = await screen.findByLabelText("Search themes");
    await fireEvent.input(input, { target: { value: "https://youtu.be/abcDEF123_4" } });
    await fireEvent.keyDown(input, { key: "Enter" });
    expect(await screen.findByRole("button", { name: "Discard draft" })).toBeInTheDocument();
    expect(calls.find((call) => call.init.method === "PUT")?.init.body).toBe(
      JSON.stringify({ youtube_id_overturedb: "abcDEF123_4" }),
    );
    expect(screen.getByText("ThemerrDB", { selector: ".badge" })).toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Clear catalog theme" }));
    await waitFor(() =>
      expect(calls.filter((call) => call.init.method === "PUT").at(-1)?.init.body).toBe(
        JSON.stringify({ youtube_id_overturedb: null }),
      ),
    );
  });

  it("edits backgrounds through the paste fallback and reports refused drafts", async () => {
    await navigate("/overturedb/movies/:entrySlug/art/:subtab", {
      params: { entrySlug: "tmdb-348", subtab: "background" },
    });
    const { calls } = mockFetchRoutes({
      "/api/public-dataset/catalog/movie/tmdb-348": catalogDetail(),
      "/api/public-dataset/catalog/movie/tmdb-348/draft": () =>
        Response.json({ detail: "Use catalog artwork" }, { status: 422 }),
    });
    renderWithQueryClient(CatalogEntryPage);
    await screen.findByRole("heading", { name: "Alien" });
    await fireEvent.click(screen.getByRole("button", { name: "Paste URL & save as background" }));
    await fireEvent.input(await screen.findByLabelText("Image URL"), { target: { value: poster } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(
        notificationState.toasts.some((toast) => toast.message === "Use catalog artwork"),
      ).toBe(true),
    );
    expect(calls.find((call) => call.init.method === "PUT")?.init.body).toBe(
      JSON.stringify({ background_url: poster }),
    );
    expect(screen.queryByRole("button", { name: "Discard draft" })).toBeNull();
  });

  it("preserves other season posters when editing or removing season zero", async () => {
    await navigate("/overturedb/shows/:entrySlug/art/seasons/:seasonNum", {
      params: { entrySlug: "tvdb-81189", seasonNum: "0" },
    });
    let detail = catalogDetail({
      entry_key: "tvdb-81189",
      entry: catalogEntry({
        media_type: "show",
        tmdb_id: null,
        tvdb_id: 81189,
        seasons: [{ season_num: 1, poster_url: poster }],
      }),
    });
    const { calls } = mockFetchRoutes({
      "/api/public-dataset/catalog/show/tvdb-81189": () => Response.json(detail),
      "/api/public-dataset/catalog/show/tvdb-81189/draft": ({ init }: { init: RequestInit }) => {
        const body: CatalogDraftUpdate = JSON.parse(String(init.body));
        detail = { ...detail, draft: { ...detail.entry, seasons: body.seasons ?? [] } };
        return Response.json(detail);
      },
    });
    renderWithQueryClient(CatalogEntryPage);
    await screen.findByRole("heading", { name: "Alien" });
    await fireEvent.click(
      screen.getByRole("button", { name: "Paste URL & save as season poster" }),
    );
    await fireEvent.input(await screen.findByLabelText("Image URL"), { target: { value: poster } });
    await fireEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(detail.draft?.seasons).toEqual([
        { season_num: 0, poster_url: poster },
        { season_num: 1, poster_url: poster },
      ]),
    );
    await fireEvent.click(await screen.findByRole("button", { name: "Clear artwork" }));
    await waitFor(() =>
      expect(detail.draft?.seasons).toEqual([{ season_num: 1, poster_url: poster }]),
    );
    expect(calls.some((call) => call.url.startsWith("/api/tmdb"))).toBe(false);
    await fireEvent.click(screen.getByRole("button", { name: "All seasons" }));
    expect(await screen.findByRole("button", { name: "Season 1" })).toBeInTheDocument();
  });

  it("lists collection members with their library links and opens its linked collection", async () => {
    settingsState.load(appSettings({ tmdb_configured: true }));
    await navigate("/overturedb/movies/collections/:entrySlug/themes", {
      params: { entrySlug: "tmdb-10" },
    });
    mockFetchRoutes({
      "/api/public-dataset/catalog/collection/tmdb-10": catalogDetail({
        entry_key: "tmdb-10",
        entry: catalogEntry({ media_type: "collection", tmdb_id: 10, title: "Star Wars" }),
        library_collection_id: 12,
      }),
      "/api/tmdb/collections/10": {
        tmdb_id: 10,
        title: "Star Wars",
        items: [
          {
            kind: "item",
            title: "A New Hope",
            media_type: "movie",
            tmdb_id: 11,
            existing_item_id: 8,
            year: 1977,
          },
        ],
      },
      "/api/themes/search": { results: [] },
    });
    renderWithQueryClient(CatalogCollectionPage);
    const members = await screen.findByRole("region", { name: "Collection members" });
    expect(within(members).getByText("In library")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "TMDB 10" })).toHaveAttribute(
      "href",
      "https://www.themoviedb.org/collection/10",
    );
    await fireEvent.click(screen.getByRole("button", { name: "Open in library" }));
    await waitFor(() => expect(route.pathname).toBe("/movies/collections/12-star-wars"));
  });

  it("keeps a draft visible if discarding it fails", async () => {
    mockFetchRoutes({
      "/api/public-dataset/catalog/movie/tmdb-348": catalogDetail({
        draft: catalogEntry({ poster_url: poster }),
      }),
      "/api/public-dataset/catalog/movie/tmdb-348/draft": () =>
        Response.json({ detail: "Try again" }, { status: 422 }),
    });
    renderWithQueryClient(CatalogEntryPage);
    await fireEvent.click(await screen.findByRole("button", { name: "Discard draft" }));
    await waitFor(() =>
      expect(notificationState.toasts.some((toast) => toast.message === "Try again")).toBe(true),
    );
    expect(screen.getByRole("button", { name: "Discard draft" })).toBeEnabled();
  });

  it("holds discard and clear actions while an artwork draft is saving", async () => {
    settingsState.load(appSettings({ tmdb_configured: true }));
    const initial = catalogDetail({ draft: catalogEntry({ poster_url: poster }) });
    let finish: ((response: Response) => void) | undefined;
    mockFetchRoutes({
      "/api/public-dataset/catalog/movie/tmdb-348": initial,
      "/api/tmdb/movie/348/art/poster/sources": {
        sources: { tmdb: [artCandidate({ url: poster })] },
      },
      "/api/public-dataset/catalog/movie/tmdb-348/draft": () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    });
    renderWithQueryClient(CatalogEntryPage);
    await fireEvent.click(
      await screen.findByRole("button", { name: "Use artwork 1000x1500 from tmdb" }),
    );
    await waitFor(() => expect(finish).toBeDefined());
    expect(screen.getByRole("button", { name: "Discard draft" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Clear artwork" })).toBeDisabled();
    finish?.(Response.json(initial));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Discard draft" })).toBeEnabled(),
    );
  });

  it("does not request a catalog entry while OvertureDB is disabled", async () => {
    queryClient.setQueryData(
      getPublicDatasetStatusOptions().queryKey,
      publicDatasetStatus({ enabled: false }),
    );
    const { calls } = mockFetchRoutes({});
    renderWithQueryClient(CatalogEntryPage);
    expect(screen.getByText("Enable OvertureDB to browse the catalog.")).toBeInTheDocument();
    expect(calls).toEqual([]);
    expect(
      queryClient.getQueryData(
        getCatalogEntryOptions({ path: { media_type: "movie", entry_key: "tmdb-348" } }).queryKey,
      ),
    ).toBeUndefined();
  });
});
