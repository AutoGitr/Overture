import { createQuery, onlineManager } from "@tanstack/svelte-query";
import { flushSync } from "svelte";
import { afterEach, describe, expect, it, vi } from "vitest";
import { queryClient } from "../../../lib/rest/queryClient";
import { ApiError } from "../../../lib/rest/transport";

afterEach(() => {
  onlineManager.setOnline(true);
  queryClient.clear();
});

describe("queryClient", () => {
  it("shows data that settled while a view read only the query's error", async () => {
    let query: { data: number | undefined; error: unknown } | undefined;
    const cleanup = $effect.root(() => {
      query = createQuery(
        () => ({ queryKey: ["settles-unread"], queryFn: () => Promise.resolve(42) }),
        () => queryClient,
      );
      // A view that shows only a failure until another state reveals the data.
      $effect(() => {
        void query?.error;
      });
    });

    await vi.waitFor(() => expect(queryClient.getQueryData(["settles-unread"])).toBe(42));
    flushSync();

    expect(query?.data).toBe(42);
    cleanup();
  });
});

describe("query retry policy", () => {
  it.each([401, 403, 404, 422, 429])(
    "does not repeat a rejected HTTP %i request",
    async (status) => {
      const queryFn = vi.fn().mockRejectedValue(new ApiError("Rejected", status));
      await expect(
        queryClient.fetchQuery({ queryKey: ["rejected", status], queryFn, retryDelay: 0 }),
      ).rejects.toMatchObject({ status });
      expect(queryFn).toHaveBeenCalledOnce();
    },
  );

  it.each([0, 502, 503])(
    "retries a transient HTTP %i failure within a fixed bound",
    async (status) => {
      const queryFn = vi.fn().mockRejectedValue(new ApiError("Unavailable", status));
      await expect(
        queryClient.fetchQuery({ queryKey: ["transient", status], queryFn, retryDelay: 0 }),
      ).rejects.toMatchObject({ status });
      expect(queryFn).toHaveBeenCalledTimes(3);
    },
  );

  it("reports offline writes immediately instead of queuing them for replay", async () => {
    onlineManager.setOnline(false);
    const mutationFn = vi.fn().mockRejectedValue(new ApiError("Offline", 0));
    const mutation = queryClient.getMutationCache().build(queryClient, { mutationFn });
    await expect(mutation.execute(undefined)).rejects.toMatchObject({ status: 0 });
    expect(mutationFn).toHaveBeenCalledOnce();
    onlineManager.setOnline(true);
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mutationFn).toHaveBeenCalledOnce();
  });
});
