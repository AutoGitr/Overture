import { fireEvent, screen } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import { queryClient } from "../../../../lib/rest/queryClient";
import CollectionPage from "../../../../lib/router/pages/CollectionPage.svelte";
import { navigate } from "../../../../lib/router/routes";
import { uiState } from "../../../../lib/stores/uiState.svelte";
import { mockFetchRoutes } from "../../../helpers/fetch";
import { collectionDetail as collection } from "../../../helpers/fixtures";
import { renderWithQueryClient } from "../../../helpers/render";

const action = collection({ id: 12, title: "Action", media_type: "movie" });

async function openCollection(collectionSlug: string) {
  await navigate("/movies/collections/:collectionSlug", { params: { collectionSlug } });
}

describe("CollectionPage", () => {
  beforeEach(() => {
    queryClient.clear();
    uiState.mobileShowDetail = false;
  });

  it("selects the collection its URL names once its detail has loaded", async () => {
    mockFetchRoutes({
      "/api/collections/groups": [],
      "/api/library/libraries": [],
      "/api/library/items": { items: [], total: 0 },
      "/api/collections/12": action,
    });
    await openCollection("12-action");

    renderWithQueryClient(CollectionPage);

    expect(await screen.findByRole("heading", { name: "Action" })).toBeInTheDocument();
    expect(uiState.mobileShowDetail).toBe(true);
  });

  it("selects nothing for a collection the server no longer lists", async () => {
    const { fetchMock } = mockFetchRoutes({
      "/api/collections/groups": [],
      "/api/library/libraries": [],
      "/api/library/items": { items: [], total: 0 },
      "/api/collections/12": () =>
        Response.json({ detail: "Collection not found" }, { status: 404 }),
    });
    await openCollection("12-action");

    renderWithQueryClient(CollectionPage);

    expect(await screen.findByText("Select a collection from the sidebar")).toBeInTheDocument();
    expect(await screen.findByRole("alert")).toHaveTextContent("Collection not found");
    expect(fetchMock).toHaveBeenCalled();
  });

  it("shows no collection on the collections list", async () => {
    mockFetchRoutes({ "/api/collections/groups": [] });
    uiState.mobileShowDetail = true;
    await navigate("/movies/collections");

    renderWithQueryClient(CollectionPage);

    expect(await screen.findByText("Select a collection from the sidebar")).toBeInTheDocument();
    expect(uiState.mobileShowDetail).toBe(false);
  });

  it("waits for a failed detail to be retried before deciding what is selected", async () => {
    let available = false;
    mockFetchRoutes({
      "/api/collections/groups": [],
      "/api/library/libraries": [],
      "/api/library/items": { items: [], total: 0 },
      "/api/collections/12": () =>
        available
          ? Response.json(action)
          : Response.json({ detail: "Collections unavailable" }, { status: 404 }),
    });
    await openCollection("12-action");
    renderWithQueryClient(CollectionPage);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "collection: Collections unavailable Data is unavailable.",
    );
    expect(screen.queryByRole("heading", { name: "Action" })).not.toBeInTheDocument();

    available = true;
    await fireEvent.click(screen.getByRole("button", { name: "Retry collection" }));

    expect(await screen.findByRole("heading", { name: "Action" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
