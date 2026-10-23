import { hashKey, QueryClient, type Query, type QueryKey } from "@tanstack/svelte-query";
import { isApiError } from "./transport";

const STATUS_STALE_TIME = 5_000;
const ENTITY_STALE_TIME = 15_000;
const LIST_STALE_TIME = 60_000;
const EXPENSIVE_STALE_TIME = 5 * 60_000;

/**
 * How long each operation's data stays fresh.
 *
 * Generated query options carry no cache policy, so it is declared once here
 * and applied by operation id. Anything absent uses `ENTITY_STALE_TIME`.
 */
const STALE_TIME_BY_OPERATION: Readonly<Record<string, number>> = {
  getArtSources: EXPENSIVE_STALE_TIME,
  getPublicDatasetStatus: STATUS_STALE_TIME,
  getPublicDatasetRecord: LIST_STALE_TIME,
  listBackups: LIST_STALE_TIME,
  listBulkAssetsSchedules: LIST_STALE_TIME,
  listCollections: LIST_STALE_TIME,
  listCatalogEntries: LIST_STALE_TIME,
  getCatalogEntry: LIST_STALE_TIME,
  listItems: LIST_STALE_TIME,
  listSyncSchedules: LIST_STALE_TIME,
  searchYoutube: EXPENSIVE_STALE_TIME,
};

/** Read the operation id out of a generated tagged query key. */
export function queryOperationId(queryKey: readonly unknown[]): string | null {
  const first = queryKey[0];
  if (!first || typeof first !== "object" || !("_id" in first)) return null;
  const id = (first as { _id?: unknown })._id;
  return typeof id === "string" ? id : null;
}

function staleTimeFor(query: Query): number {
  const id = queryOperationId(query.queryKey);
  return (id ? STALE_TIME_BY_OPERATION[id] : undefined) ?? ENTITY_STALE_TIME;
}

export const queryClient = new QueryClient({
  defaultOptions: {
    mutations: {
      retry: false,
      networkMode: "always",
    },
    queries: {
      refetchOnReconnect: true,
      refetchOnWindowFocus: false,
      networkMode: "always",
      retry: (failures, error) => failures < 2 && isApiError(error) && error.retryable,
      staleTime: staleTimeFor,
      // By default a result reports a change only to properties read so far,
      // so data that settles while a view reads only part of it (its error,
      // say, until another state shows the data) would stay stale. Svelte's
      // signals already update only what reads a changed value.
      notifyOnChangeProps: "all",
    },
  },
});

/**
 * Follow what the cache holds for *queryKey*: *onData* receives the current
 * value and every later one, from a fetch or a realtime write alike, and
 * *onError* every failed fetch. Stores that mirror server data read it here,
 * so the cache stays the one place it is written.
 */
export function followQuery<T>(
  queryKey: QueryKey,
  onData: (data: T) => void,
  onError: (error: unknown) => void = () => {},
): () => void {
  const hash = hashKey(queryKey);
  const current = queryClient.getQueryData<T>(queryKey);
  if (current !== undefined) onData(current);
  return queryClient.getQueryCache().subscribe((event) => {
    if (event.query.queryHash !== hash || event.type !== "updated") return;
    if (event.action.type === "success") onData(event.query.state.data as T);
    else if (event.action.type === "error") onError(event.action.error);
  });
}

export function clearRestCache(): void {
  queryClient.clear();
}
