import { beforeEach, describe, expect, it } from "vitest";
import { getPublicDatasetStatusOptions } from "../../../generated/rest/@tanstack/svelte-query.gen";
import { queryClient } from "../../../lib/rest/queryClient";
import { publicDatasetState } from "../../../lib/stores/publicDatasetState.svelte";
import { mockFetchRoutes } from "../../helpers/fetch";
import { publicDatasetStatus } from "../../helpers/fixtures";

describe("publicDatasetState", () => {
  beforeEach(() => {
    queryClient.clear();
    publicDatasetState.reset();
  });

  it("follows the status the query cache holds", () => {
    expect([publicDatasetState.loaded, publicDatasetState.enabled]).toEqual([false, false]);

    queryClient.setQueryData(
      getPublicDatasetStatusOptions().queryKey,
      publicDatasetStatus({ enabled: true }),
    );

    expect([publicDatasetState.loaded, publicDatasetState.enabled]).toEqual([true, true]);
  });

  it("reads the status again on refresh and reports a failure", async () => {
    let available = false;
    const { fetchMock } = mockFetchRoutes({
      "/api/public-dataset/status": () =>
        available
          ? Response.json(publicDatasetStatus({ last_status: "success" }))
          : Response.json({ detail: "Catalog offline" }, { status: 404 }),
    });

    await publicDatasetState.refresh();
    expect(publicDatasetState.error).toBe("Catalog offline");
    expect(publicDatasetState.loading).toBe(false);

    available = true;
    await publicDatasetState.refresh();
    expect(publicDatasetState.error).toBe("");
    expect(publicDatasetState.status?.last_status).toBe("success");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("joins a refresh already under way instead of starting another", async () => {
    const { fetchMock } = mockFetchRoutes({ "/api/public-dataset/status": publicDatasetStatus() });

    await Promise.all([publicDatasetState.refresh(), publicDatasetState.refresh()]);

    expect(fetchMock).toHaveBeenCalledOnce();
  });
});
