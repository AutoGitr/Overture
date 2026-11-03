import { listCatalogEntriesOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
import { discardCatalogDrafts } from "../../generated/rest/sdk.gen";
import type { CatalogEntryRow, CatalogMediaType } from "../../generated/rest/types.gen";
import { invalidateTags } from "../rest/cache";
import { queryClient } from "../rest/queryClient";

const CATALOG_MEDIA_TYPES: readonly CatalogMediaType[] = ["movie", "show", "collection"];

/** Discard the drafts of *entries*, by media type; return how many were discarded. */
export async function discardDrafts(entries: readonly CatalogEntryRow[]): Promise<number> {
  let discarded = 0;
  for (const mediaType of CATALOG_MEDIA_TYPES) {
    const keys = entries
      .filter((entry) => entry.media_type === mediaType && entry.has_draft)
      .map((entry) => entry.entry_key);
    if (!keys.length) continue;
    const { data } = await discardCatalogDrafts({
      path: { media_type: mediaType },
      body: { entry_keys: keys },
      throwOnError: true,
    });
    discarded += data.discarded;
  }
  await invalidateTags(["public-dataset"]);
  return discarded;
}

/** Every catalog entry that holds a draft, across movies, shows and collections. */
export async function draftedEntries(): Promise<CatalogEntryRow[]> {
  const lists = await Promise.all(
    CATALOG_MEDIA_TYPES.map((mediaType) =>
      queryClient.fetchQuery(listCatalogEntriesOptions({ query: { media_type: mediaType } })),
    ),
  );
  return lists.flat().filter((entry) => entry.has_draft);
}
