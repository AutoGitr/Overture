import { fireEvent, screen, waitFor, within } from "@testing-library/svelte";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getItemOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import type { DatabaseRecord, MediaItemRead } from "../../../generated/rest/types.gen";
import DbRecordPopup from "../../../lib/popups/DbRecordPopup.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { goToCatalogEntry, goToItem, navigate, route } from "../../../lib/router/routes";
import { mockFetchRoutes } from "../../helpers/fetch";
import {
  catalogDetail,
  catalogEntry,
  mediaItem,
  publicDatasetRecord,
  publicDatasetRecordItem,
  publicDatasetRecordSeason,
} from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

const alien = mediaItem({ id: 7, title: "Alien", tmdb_id: 348 });
const notFound = { found: false, item: null, seasons: [] };
const alienRecord: DatabaseRecord = {
  stored: [
    { table: "media_items", values: { id: 7, title: "Alien", tmdb_id: 348 } },
    { table: "seasons", values: { id: 3, media_item_id: 7, season_num: 1 } },
  ],
  derived: { art_status: "missing" },
};

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
  await screen.findByRole("dialog", { name: /^Database Record/ });
  return view;
}

describe("DbRecordPopup", () => {
  beforeEach(async () => {
    queryClient.clear();
    await openItem(alien);
  });

  it("groups what the database stores apart from what the API derives", async () => {
    const { calls } = mockFetchRoutes({
      "/api/library/items/7/record": alienRecord,
      "/api/public-dataset/items/7/record": notFound,
    });

    await renderPopup();

    expect(
      await screen.findByRole("heading", { name: "Stored in media_items" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Database Record - Alien" })).toBeVisible();
    expect(field("title")).toHaveTextContent("Alien");
    expect(screen.getByText("seasons 3", { selector: "summary" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Derived by the API" })).toBeInTheDocument();
    expect(field("art_status")).toHaveTextContent("missing");
    expect(calls.map((call) => call.url)).toContain("/api/library/items/7/record");
    expect(screen.queryByRole("heading", { name: "OvertureDB Item" })).not.toBeInTheDocument();
  });

  it("copies a value and marks only the field copied last", async () => {
    mockFetchRoutes({
      "/api/library/items/7/record": alienRecord,
      "/api/public-dataset/items/7/record": notFound,
    });
    const writeText = vi.fn().mockResolvedValue(undefined);
    stubClipboard(writeText);
    await renderPopup();

    await fireEvent.click(await screen.findByRole("button", { name: /^title / }));
    await waitFor(() => expect(field("title").querySelector(".text-success")).not.toBeNull());
    await fireEvent.click(field("tmdb_id"));

    expect(writeText.mock.calls).toEqual([["Alien"], ["348"]]);
    await waitFor(() => expect(field("tmdb_id").querySelector(".text-success")).not.toBeNull());
    expect(field("title").querySelector(".text-success")).toBeNull();
  });

  it("asks for a manual copy when the clipboard is unavailable", async () => {
    mockFetchRoutes({
      "/api/library/items/7/record": alienRecord,
      "/api/public-dataset/items/7/record": notFound,
    });
    stubClipboard();
    await renderPopup();

    await fireEvent.click(await screen.findByRole("button", { name: /^title / }));

    expect(
      await screen.findByText(
        "Clipboard access is unavailable. Select and copy the value manually.",
      ),
    ).toBeInTheDocument();
  });

  it("reports a record that cannot be read, and retries it", async () => {
    let available = false;
    mockFetchRoutes({
      "/api/library/items/7/record": () =>
        available ? Response.json(alienRecord) : Response.json({ detail: "Down" }, { status: 404 }),
      "/api/public-dataset/items/7/record": notFound,
    });
    await renderPopup();

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("database record: Down");

    available = true;
    await fireEvent.click(within(alert).getByRole("button", { name: "Retry database record" }));

    expect(await screen.findByRole("button", { name: /^title / })).toHaveTextContent("Alien");
  });

  it("shows the matching OvertureDB record and its seasons", async () => {
    mockFetchRoutes({
      "/api/library/items/7/record": alienRecord,
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

  it("shows the selected collection and its OvertureDB record, never an item's", async () => {
    await navigate("/collections/:collectionSlug", {
      params: { collectionSlug: "12-action" },
    });
    const { calls } = mockFetchRoutes({
      "/api/collections/12/record": {
        stored: [{ table: "media_collections", values: { id: 12, title: "Action" } }],
        derived: {},
      },
      "/api/public-dataset/collections/12/record": {
        found: true,
        item: null,
        seasons: [],
        collection: { id: 1, tmdb_id: 10, title: "Action Collection" },
      },
    });

    await renderPopup();

    expect(
      await screen.findByRole("heading", { name: "Stored in media_collections" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("dialog", { name: "Database Record - Action" })).toBeVisible();
    expect(
      await screen.findByRole("heading", { name: "OvertureDB Collection" }),
    ).toBeInTheDocument();
    expect(calls.map((call) => call.url).toSorted()).toEqual([
      "/api/collections/12/record",
      "/api/public-dataset/collections/12/record",
    ]);
  });

  it("shows a catalog entry's OvertureDB record", async () => {
    goToCatalogEntry({ media_type: "movie", entry_key: "tmdb-348" });
    await waitFor(() => expect(route.params.entrySlug).toBe("tmdb-348"));
    mockFetchRoutes({
      "/api/public-dataset/catalog/movie/tmdb-348/record": publicDatasetRecord(),
      "/api/public-dataset/catalog/movie/tmdb-348": catalogDetail({
        draft: catalogEntry({ poster_url: "https://image.test/draft.jpg" }),
      }),
    });

    await renderPopup();

    expect(await screen.findByRole("heading", { name: "OvertureDB Item" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /^Stored in/ })).not.toBeInTheDocument();
    // A local draft is inspectable beside the synced catalog row.
    const draft = await screen.findByRole("heading", { name: "Local draft" });
    expect(draft.closest("section")).toHaveTextContent("https://image.test/draft.jpg");
  });
});
