import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  getItemOptions,
  listCollectionsOptions,
} from "../../../generated/rest/@tanstack/svelte-query.gen";
import type { MediaItemRead } from "../../../generated/rest/types.gen";
import DbRecordPopup from "../../../lib/popups/DbRecordPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { goToItem, navigate, route } from "../../../lib/router/routes";
import { mockFetchRoutes } from "../../helpers/fetch";
import {
  collection,
  mediaItem,
  publicDatasetRecord,
  publicDatasetRecordItem,
  publicDatasetRecordSeason,
  season,
} from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const alien = mediaItem({ id: 7, title: "Alien", tmdb_id: 348 });
const notFound = { found: false, item: null, seasons: [] };

function stubClipboard(writeText?: (value: string) => Promise<void>) {
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: writeText ? { writeText } : undefined,
  });
}

/** The copy button of a field, named by its key and value. */
function field(name: string) {
  return screen.getByRole("button", { name: new RegExp(`^${name} `) });
}

/** Open *item*'s detail route, with its record cached as the detail view left it. */
async function openItem(item: MediaItemRead) {
  queryClient.setQueryData(getItemOptions({ path: { item_id: item.id } }).queryKey, item);
  await goToItem(item);
  expect(route.params.itemSlug).toMatch(new RegExp(`^${item.id}-`));
}

async function renderPopup() {
  const view = renderWithQueryClient(DbRecordPopup);
  await screen.findByRole("dialog", { name: /^Database Record - / });
  return view;
}

describe("DbRecordPopup", () => {
  beforeEach(async () => {
    queryClient.clear();
    await openItem(alien);
  });

  it("lists the item's stored fields and re-reads it on open", async () => {
    mockFetchRoutes({
      "/api/library/items/7": { ...alien, year: 1979 },
      "/api/public-dataset/items/7/record": notFound,
    });

    await renderPopup();

    expect(screen.getByRole("dialog", { name: "Database Record - Alien" })).toBeVisible();
    expect(field("title")).toHaveTextContent("Alien");
    expect(field("tmdb_id")).toHaveTextContent("348");
    // The open item follows its query, which the refresh replaces.
    await waitFor(() =>
      expect(
        queryClient.getQueryData(getItemOptions({ path: { item_id: 7 } }).queryKey),
      ).toMatchObject({ year: 1979 }),
    );
    expect(screen.queryByRole("heading", { name: "OvertureDB Item" })).not.toBeInTheDocument();
  });

  it("copies a value and marks only the field copied last", async () => {
    mockFetchRoutes({
      "/api/library/items/7": alien,
      "/api/public-dataset/items/7/record": notFound,
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    await renderPopup();

    await fireEvent.click(field("title"));
    await waitFor(() => expect(field("title").querySelector(".text-success")).not.toBeNull());
    await fireEvent.click(field("tmdb_id"));

    expect(writeText.mock.calls).toEqual([["Alien"], ["348"]]);
    await waitFor(() => expect(field("tmdb_id").querySelector(".text-success")).not.toBeNull());
    expect(field("title").querySelector(".text-success")).toBeNull();
  });

  it("asks for a manual copy when the clipboard is unavailable", async () => {
    mockFetchRoutes({
      "/api/library/items/7": alien,
      "/api/public-dataset/items/7/record": notFound,
    });
    stubClipboard();
    await renderPopup();

    await fireEvent.click(field("title"));

    expect(
      await screen.findByText(
        "Clipboard access is unavailable. Select and copy the value manually.",
      ),
    ).toBeInTheDocument();
  });

  it("keeps the last loaded record when the refresh fails, and retries it", async () => {
    let available = false;
    mockFetchRoutes({
      "/api/library/items/7": () =>
        available ? Response.json(alien) : Response.json({ detail: "Down" }, { status: 404 }),
      "/api/public-dataset/items/7/record": notFound,
    });
    await renderPopup();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("database record: Down Showing last loaded data.");
    expect(field("title")).toHaveTextContent("Alien");

    available = true;
    await fireEvent.click(within(alert).getByRole("button", { name: "Retry database record" }));

    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });

  it("lists a show's seasons", async () => {
    const show = mediaItem({ id: 9, media_type: "show", title: "Firefly" });
    await openItem(show);
    mockFetchRoutes({
      "/api/library/items/9": show,
      "/api/library/items/9/seasons": [season({ id: 3, media_item_id: 9, season_num: 1 })],
      "/api/public-dataset/items/9/record": notFound,
    });

    await renderPopup();

    expect(await screen.findByRole("heading", { name: "Seasons" })).toBeInTheDocument();
    expect(screen.getByText("Season 1", { selector: "summary" })).toBeInTheDocument();
  });

  it("shows the matching OvertureDB record and its seasons", async () => {
    mockFetchRoutes({
      "/api/library/items/7": alien,
      "/api/public-dataset/items/7/record": publicDatasetRecord({
        item: publicDatasetRecordItem({ title: "Alien", tmdb_id: 348 }),
        seasons: [publicDatasetRecordSeason({ season_num: 2 })],
      }),
    });

    await renderPopup();

    expect(await screen.findByRole("heading", { name: "OvertureDB Item" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "OvertureDB Seasons" })).toBeInTheDocument();
    expect(screen.getByText("Season 2", { selector: "summary" })).toBeInTheDocument();
  });

  it("shows the selected collection in collections mode without reading item records", async () => {
    queryClient.setQueryData(listCollectionsOptions({ query: { media_type: "movie" } }).queryKey, [
      collection({ id: 12, title: "Action", media_type: "movie" }),
    ]);
    await navigate("/movies/collections/:collectionSlug", {
      params: { collectionSlug: "12-action" },
    });
    const { calls } = mockFetchRoutes({});

    await renderPopup();

    expect(screen.getByRole("dialog", { name: "Database Record - Action" })).toBeVisible();
    expect(screen.getByRole("heading", { name: "Collection" })).toBeInTheDocument();
    expect(field("title")).toHaveTextContent("Action");
    expect(calls).toEqual([]);
  });
});
