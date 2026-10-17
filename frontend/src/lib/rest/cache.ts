import {
  getItemOptions,
  getSeasonsOptions,
  listBulkAssetsSchedulesQueryKey,
  listSyncSchedulesQueryKey,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  BulkItemOperation,
  CollectionRead,
  MediaItemListResponse,
  MediaItemRead,
} from "../../generated/rest/types.gen";
import type { ApiTag, SchedulesChangedEvent } from "../../generated/ws";
import { artPreviewState } from "../stores/artPreviewState.svelte";
import { collectionState } from "../stores/collectionState.svelte";
import { selectedState } from "../stores/selectedState.svelte";
import { queryClient, queryOperationId } from "./queryClient";

type TaggedQueryKey = readonly [
  {
    _id?: string;
    tags?: readonly string[];
    path?: { item_id?: number };
    query?: {
      media_type?: string | null;
    };
  },
];

function isTaggedQuery(queryKey: readonly unknown[], id: string): queryKey is TaggedQueryKey {
  return queryOperationId(queryKey) === id;
}

function patchLibraryQueries(
  update: (response: MediaItemListResponse, queryKey: TaggedQueryKey) => MediaItemListResponse,
): void {
  for (const [queryKey, response] of queryClient.getQueriesData<MediaItemListResponse>({
    predicate: ({ queryKey }) => isTaggedQuery(queryKey, "listItems"),
  })) {
    if (response && isTaggedQuery(queryKey, "listItems")) {
      queryClient.setQueryData(queryKey, update(response, queryKey));
    }
  }
}

/** TMDB answers that name the stored item of each title. */
const TMDB_MATCH_OPERATIONS = ["searchTmdb", "getTmdbCollection", "getTmdbItem"];

/**
 * TMDB answers name the stored item of each title, so they go out of date
 * whenever an item is stored or removed. Mark them stale, so the next look at
 * a title re-checks it, and refresh the results on show. An open title is not
 * refetched: its own first selection switches the view to the stored item.
 */
function outdateTmdbMatches(): void {
  void queryClient.invalidateQueries({
    predicate: ({ queryKey }) => TMDB_MATCH_OPERATIONS.some((id) => isTaggedQuery(queryKey, id)),
    refetchType: "none",
  });
  void queryClient.refetchQueries({
    predicate: ({ queryKey }) =>
      isTaggedQuery(queryKey, "searchTmdb") || isTaggedQuery(queryKey, "getTmdbCollection"),
    type: "active",
  });
}

export function upsertLibraryItem(item: MediaItemRead): void {
  if (item.server_removed_at) {
    removeLibraryItem(item.id);
    return;
  }

  let added = false;
  patchLibraryQueries((response, queryKey) => {
    const existing = response.items.some((current) => current.id === item.id);
    const listType = queryKey[0].query?.media_type;
    const belongs = !listType || listType === item.media_type;
    if (existing) {
      if (!belongs) {
        return {
          items: response.items.filter((current) => current.id !== item.id),
          total: Math.max(0, response.total - 1),
        };
      }
      return {
        ...response,
        items: response.items.map((current) => (current.id === item.id ? item : current)),
      };
    }
    if (belongs) {
      added = true;
      return {
        items: [...response.items, item],
        total: response.total + 1,
      };
    }
    return response;
  });

  // The open item follows this query, so its detail view updates from here too.
  queryClient.setQueryData(getItemOptions({ path: { item_id: item.id } }).queryKey, item);
  artPreviewState.itemUpdated(item);
  if (added) outdateTmdbMatches();
}

export function removeLibraryItem(itemId: number): void {
  const removeSelection = selectedState.item?.id === itemId;
  let removed = false;
  patchLibraryQueries((response) => {
    const items = response.items.filter((item) => item.id !== itemId);
    if (items.length === response.items.length) return response;
    removed = true;
    return { items, total: Math.max(0, response.total - 1) };
  });
  if (removed) outdateTmdbMatches();
  queryClient.removeQueries({ queryKey: getItemOptions({ path: { item_id: itemId } }).queryKey });
  if (removeSelection) selectedState.selectItem(null);
}

export function findCachedLibraryItem(itemId: number): MediaItemRead | undefined {
  for (const [, response] of queryClient.getQueriesData<MediaItemListResponse>({
    predicate: ({ queryKey }) => isTaggedQuery(queryKey, "listItems"),
  })) {
    const item = response?.items.find((current) => current.id === itemId);
    if (item) return item;
  }
}

export async function refreshItem(itemId: number | string): Promise<MediaItemRead> {
  const options = getItemOptions({ path: { item_id: Number(itemId) } });
  await queryClient.invalidateQueries({ queryKey: options.queryKey, exact: true });
  const item = await queryClient.fetchQuery(options);
  upsertLibraryItem(item);
  return item;
}

/** Mark an item's seasons stale; mounted views refetch themselves. */
export function invalidateSeasons(itemId: number | string): Promise<void> {
  return queryClient.invalidateQueries({
    queryKey: getSeasonsOptions({ path: { item_id: Number(itemId) } }).queryKey,
    exact: true,
  });
}

export function patchCollection(serverId: string, update: Partial<CollectionRead>): void {
  queryClient.setQueriesData<CollectionRead[]>(
    {
      predicate: ({ queryKey }) => isTaggedQuery(queryKey, "listCollections"),
    },
    (collections) =>
      collections?.map((collection) =>
        collection.id === serverId ? { ...collection, ...update } : collection,
      ),
  );
  collectionState.patchSelectedCollection(serverId, update);
}

/** Apply a whole committed batch without per-item requests or list scans. */
export function applyBulkItemOperation({ item_ids, operation }: BulkItemOperation): void {
  if (operation === "artwork" || operation === "themes") {
    // Clearing selections changes completeness, which only the backend computes.
    void invalidateTags(["library"]);
    return;
  }
  const ids = new Set(item_ids);
  patchLibraryQueries((response) => {
    if (operation === "delete") {
      const items = response.items.filter((item) => !ids.has(item.id));
      return { items, total: Math.max(0, response.total - (response.items.length - items.length)) };
    }
    return {
      ...response,
      items: response.items.map((item) =>
        ids.has(item.id) ? { ...item, monitored: operation === "monitor" } : item,
      ),
    };
  });

  const targets = (queryKey: readonly unknown[], id: string) =>
    isTaggedQuery(queryKey, id) && ids.has(queryKey[0].path?.item_id ?? -1);
  if (operation === "delete") {
    outdateTmdbMatches();
    queryClient.removeQueries({
      predicate: ({ queryKey }) => targets(queryKey, "getItem") || targets(queryKey, "getSeasons"),
    });
  } else {
    queryClient.setQueriesData<MediaItemRead>(
      { predicate: ({ queryKey }) => targets(queryKey, "getItem") },
      (item) => (item ? { ...item, monitored: operation === "monitor" } : item),
    );
  }
  // A removed query still answers its open view, so a deleted selection closes here.
  if (operation === "delete" && selectedState.item && ids.has(selectedState.item.id)) {
    selectedState.selectItem(null);
  }
}

export function bulkSetCollectionMonitoredInCache(
  collectionIds: string[],
  monitored: boolean,
): void {
  const ids = new Set(collectionIds);
  queryClient.setQueriesData<CollectionRead[]>(
    {
      predicate: ({ queryKey }) => isTaggedQuery(queryKey, "listCollections"),
    },
    (collections) =>
      collections?.map((collection) =>
        ids.has(collection.id) ? { ...collection, monitored } : collection,
      ),
  );
}

export function invalidateTags(tags: readonly ApiTag[], throwOnError = false): Promise<void> {
  return queryClient.invalidateQueries(
    {
      predicate: ({ queryKey }) => {
        const first = queryKey[0];
        if (!first || typeof first !== "object" || !("tags" in first)) return false;
        const queryTags = first.tags;
        return Array.isArray(queryTags) && tags.some((tag) => queryTags.includes(tag));
      },
    },
    { throwOnError },
  );
}

export function invalidateReconnectData(): Promise<void> {
  return invalidateTags(
    ["library", "collections", "settings", "public-dataset", "sync", "backups", "bulk"],
    true,
  );
}

const SCHEDULE_LISTS = {
  sync: listSyncSchedulesQueryKey(),
  assets: listBulkAssetsSchedulesQueryKey(),
} satisfies Record<SchedulesChangedEvent["kind"], readonly unknown[]>;

/** Reload one kind's saved schedules, which the server said changed. */
export function invalidateSchedules(kind: SchedulesChangedEvent["kind"]): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: SCHEDULE_LISTS[kind] });
}
