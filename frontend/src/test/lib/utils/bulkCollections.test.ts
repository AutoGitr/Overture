import { expect, it, vi } from "vitest";
import { runBulkCollections } from "../../../lib/utils/bulkCollections";

it("batches large selections and preserves successful IDs and per-record errors", async () => {
  const ids = Array.from({ length: 1001 }, (_, index) => index + 1);
  const execute = vi
    .fn()
    .mockResolvedValueOnce({ collection_ids: ids.slice(0, 999), errors: { 1000: "Failed" } })
    .mockResolvedValueOnce({ collection_ids: [1001], errors: {} });
  const result = await runBulkCollections(
    { collection_ids: ids, media_type: "movie", operation: "delete" },
    execute,
  );
  expect(execute.mock.calls.map(([body]) => body.collection_ids.length)).toEqual([1000, 1]);
  expect(result.collection_ids).toEqual([...ids.slice(0, 999), 1001]);
  expect(result.errors).toEqual({ 1000: "Failed" });
});
