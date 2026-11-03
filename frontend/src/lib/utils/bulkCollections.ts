import type {
  BulkCollectionOperation,
  BulkCollectionOperationResult,
} from "../../generated/rest/types.gen";

/** Keep large filtered selections within the API's request limit. */
export async function runBulkCollections(
  body: BulkCollectionOperation,
  execute: (body: BulkCollectionOperation) => Promise<BulkCollectionOperationResult>,
): Promise<BulkCollectionOperationResult> {
  const result: BulkCollectionOperationResult = { collection_ids: [], errors: {}, skipped: {} };
  for (let offset = 0; offset < body.collection_ids.length; offset += 1000) {
    const batch = await execute({
      ...body,
      collection_ids: body.collection_ids.slice(offset, offset + 1000),
    });
    result.collection_ids.push(...batch.collection_ids);
    Object.assign(result.errors, batch.errors);
    Object.assign(result.skipped, batch.skipped);
  }
  return result;
}
