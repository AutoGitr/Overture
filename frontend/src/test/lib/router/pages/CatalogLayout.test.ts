import { screen, waitFor } from "@testing-library/svelte";
import { createRawSnippet } from "svelte";
import { beforeEach, describe, expect, it } from "vitest";
import { getPublicDatasetStatusOptions } from "../../../../generated/rest/@tanstack/svelte-query.gen";
import CatalogLayout from "../../../../lib/router/pages/CatalogLayout.svelte";
import { queryClient } from "../../../../lib/rest/queryClient";
import { navigate, route } from "../../../../lib/router/routes";
import { settingsState } from "../../../../lib/stores/settingsState.svelte";
import { appSettings, publicDatasetStatus } from "../../../helpers/fixtures";
import { renderWithQueryClient } from "../../../helpers/render";

const children = createRawSnippet(() => ({ render: () => "<p>Catalog page</p>" }));

describe("catalog layout", () => {
  beforeEach(async () => {
    queryClient.clear();
    await navigate("/overturedb/shows/:entrySlug", { params: { entrySlug: "tmdb-1399" } });
  });

  it("shows the catalog while it can be browsed", () => {
    settingsState.load(appSettings());
    queryClient.setQueryData(getPublicDatasetStatusOptions().queryKey, publicDatasetStatus());
    renderWithQueryClient(CatalogLayout, { children });
    expect(screen.getByText("Catalog page")).toBeInTheDocument();
    expect(route.pathname).toBe("/overturedb/shows/tmdb-1399");
  });

  it.each([
    ["OvertureDB is off", { enabled: false }, true],
    ["sidebar browsing is off", {}, false],
  ] as const)("returns to the library tab while %s", async (_case, status, browse) => {
    settingsState.load(appSettings({ overturedb_browse: browse }));
    queryClient.setQueryData(getPublicDatasetStatusOptions().queryKey, publicDatasetStatus(status));
    renderWithQueryClient(CatalogLayout, { children });
    expect(screen.queryByText("Catalog page")).toBeNull();
    await waitFor(() => expect(route.pathname).toBe("/shows"));
  });
});
