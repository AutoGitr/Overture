import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import EmptyCollectionsCard from "../../../../lib/components/operations/EmptyCollectionsCard.svelte";
import { queryClient } from "../../../../lib/rest/queryClient";
import { settingsState } from "../../../../lib/stores/settingsState.svelte";
import { listCollectionsOptions } from "../../../../generated/rest/@tanstack/svelte-query.gen";
import { appSettings, collection } from "../../../helpers/fixtures";
import { mockFetchRoutes } from "../../../helpers/fetch";
import { answerConfirmation } from "../../../helpers/notifications";
import { renderWithQueryClient } from "../../../helpers/render";

describe("empty collection maintenance", () => {
  beforeEach(() => {
    queryClient.clear();
    settingsState.load(appSettings({ collections_supported: true }));
    queryClient.setQueryData(listCollectionsOptions({ query: { media_type: "movie" } }).queryKey, [
      collection({ id: 1, title: "Empty movies", child_count: 0, below_minimum: true }),
      collection({ id: 2, title: "Small movies", child_count: 1, below_minimum: true }),
      collection({ id: 3, title: "Enough movies", child_count: 5, below_minimum: false }),
    ]);
    queryClient.setQueryData(listCollectionsOptions({ query: { media_type: "show" } }).queryKey, [
      collection({
        id: 4,
        title: "Empty shows",
        media_type: "show",
        child_count: 0,
        below_minimum: true,
      }),
    ]);
  });

  it("reviews empty and optional undersized collections, then deletes each media type", async () => {
    const { calls } = mockFetchRoutes({
      "/api/collections/bulk-operation": ({ init }: { init: RequestInit }) =>
        Response.json({ collection_ids: JSON.parse(String(init.body)).collection_ids, errors: {} }),
    });
    renderWithQueryClient(EmptyCollectionsCard, { isActive: true });
    expect(screen.getByText("Empty movies (0 members)")).toBeInTheDocument();
    expect(screen.queryByText("Small movies (1 members)")).not.toBeInTheDocument();
    await fireEvent.click(
      screen.getByLabelText("Include collections below their effective minimum"),
    );
    expect(screen.getByText("Small movies (1 members)")).toBeInTheDocument();
    expect(screen.queryByText("Enough movies (5 members)")).not.toBeInTheDocument();
    await fireEvent.click(screen.getByRole("button", { name: "Delete 3 collections" }));
    expect((await answerConfirmation(true)).message).toContain("media files are kept");
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls.map((call) => JSON.parse(String(call.init.body)))).toEqual([
      { collection_ids: [1, 2], media_type: "movie", operation: "delete" },
      { collection_ids: [4], media_type: "show", operation: "delete" },
    ]);
  });

  it("keeps all records when cleanup is cancelled", async () => {
    const { calls } = mockFetchRoutes({});
    renderWithQueryClient(EmptyCollectionsCard, { isActive: true });
    await fireEvent.click(screen.getByRole("button", { name: "Delete 2 collections" }));
    await answerConfirmation(false);
    expect(calls).toEqual([]);
    expect(screen.getByText("Empty movies (0 members)")).toBeInTheDocument();
  });
});
