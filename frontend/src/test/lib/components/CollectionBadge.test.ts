import { fireEvent, screen, waitFor } from "@testing-library/svelte";
import { beforeEach, describe, expect, it } from "vitest";
import { getCatalogEntryOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import CollectionBadge from "../../../lib/components/CollectionBadge.svelte";
import { queryClient } from "../../../lib/rest/queryClient";
import { navigate, route } from "../../../lib/router/routes";
import { catalogDetail, catalogEntry } from "../../helpers/fixtures";
import { renderWithQueryClient } from "../../helpers/render";

describe("item collection badge", () => {
  beforeEach(async () => {
    queryClient.clear();
    await navigate("/movies");
  });
  it("prefers the collection linked by the item response", async () => {
    renderWithQueryClient(CollectionBadge, {
      tmdbId: 10,
      libraryCollectionId: 12,
      datasetEnabled: true,
    });
    await fireEvent.click(screen.getByRole("button", { name: "Collection" }));
    await waitFor(() => expect(route.pathname).toBe("/movies/collections/12-collection"));
  });
  it("opens a catalog collection when there is no library match", async () => {
    queryClient.setQueryData(
      getCatalogEntryOptions({ path: { media_type: "collection", entry_key: "tmdb-10" } }).queryKey,
      catalogDetail({
        entry_key: "tmdb-10",
        entry: catalogEntry({ media_type: "collection", tmdb_id: 10, title: "Star Wars" }),
      }),
    );
    renderWithQueryClient(CollectionBadge, { tmdbId: 10, datasetEnabled: true });
    await fireEvent.click(screen.getByRole("button", { name: "Collection: Star Wars" }));
    await waitFor(() => expect(route.pathname).toBe("/overturedb/movies/collections/tmdb-10"));
  });
  it("links nowhere outside Overture when the catalog is disabled", () => {
    renderWithQueryClient(CollectionBadge, { tmdbId: 10, datasetEnabled: false });
    expect(screen.queryByRole("link")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
