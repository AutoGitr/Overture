---
name: svelte-query
description: TanStack Svelte Query v6 with Svelte 5 runes, as Overture uses it with its generated REST client and live WebSocket updates. Use whenever a Svelte component or frontend module reads server data, runs a mutation, or reads or updates the query cache.
---

# Svelte Query in Overture

Overture uses `@tanstack/svelte-query` 6: Svelte 5 runes on top of
`@tanstack/query-core` 5. Most Query material online is written for React or for
the store-based v5 adapter; neither applies here. There are no hooks and no
stores: `create*` functions take option thunks and return reactive objects.

## The client

- The app has one `QueryClient`: `queryClient` in `src/lib/rest/queryClient.ts`.
  It owns the cache policy: stale time per operation id
  (`STALE_TIME_BY_OPERATION`), retry rules and network mode. Never create another
  client, and never set `staleTime` or `retry` in a component.
- `src/Root.svelte` provides it with `<QueryClientProvider>`. Components call
  `createQuery` and `createMutation` without a client argument, and call
  `useQueryClient()` during initialisation when they need the client itself.
- Code outside components (`src/lib/rest/`, `src/lib/realtime/`, stores and
  utilities) imports `queryClient` directly.

## Who owns server data

- The cache is the only copy of server data. Never mirror a query result into a
  store, into `$state` or into a module variable.
- Route pages own the queries for what they show and pass the results to their
  views as props. Other components that need the same data call the same
  generated options; the cache answers them all from one entry with one request.
- `settingsState` is the one read-only adapter, for settings that code outside
  components needs; it follows the cache with `followQuery`. Do not add others.

## Queries

```svelte
<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { getSeasonsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
  import type { MediaItemRead } from "../../generated/rest/types.gen";
  import DataStatus from "./DataStatus.svelte";

  let { item }: { item: MediaItemRead | null } = $props();

  const seasonsQuery = createQuery(() => ({
    ...getSeasonsOptions({ path: { item_id: item?.id ?? 0 } }),
    enabled: item?.media_type === "show",
  }));
  let seasons = $derived(seasonsQuery.data ?? []);
</script>

<DataStatus
  label="seasons"
  error={seasonsQuery.error}
  loading={seasonsQuery.isFetching}
  hasData={seasonsQuery.data !== undefined}
  onretry={() => seasonsQuery.refetch()}
/>
```

- Pass options as a function. Everything reactive it reads (props, `$state`,
  `$derived`) re-configures the query when it changes; a plain object would
  freeze the first values.
- Build options from the generated `*Options()` helpers in
  `src/generated/rest/@tanstack/svelte-query.gen.ts`. They carry the query key,
  its tags and the fetcher; spread them and add only `enabled`, `select`,
  `initialData` or `placeholderData`. Never hand-write a key or a `queryFn`.
- Call `create*` once, during component initialisation. Skip a request with
  `enabled: false`; never create a query conditionally, in an event handler or
  in an effect. A `.svelte.ts` class may create queries and mutations in its
  constructor when it is constructed during component initialisation, as
  `ItemRecordActions` does.
- A panel that stays mounted while hidden passes `enabled: isActive`. A disabled
  query keeps its cached data, so never latch "was shown once" in state.
- Read the result as an object (`query.data`, `query.isPending`,
  `query.error`) and derive from it with `$derived`. Never destructure it, which
  loses reactivity, and never prefix it with `$`; it is not a store.
- Show a query's loading, failure and retry with `DataStatus`
  (`src/lib/components/DataStatus.svelte`) rather than hand-rolled states.
- When a key changes, compare the result with what the route asked for before
  showing it (`itemQuery.data?.id === itemId`), so a previous entity never
  flashes in. Seed an entity the list already holds with
  `initialData: () => findCachedLibraryItem(id)` instead of waiting for it.

## Mutations

```ts
const saveArtRequest = createMutation(() => saveArtMutation());

const result = await saveArtRequest.mutateAsync({ path: { item_id, art_type }, body });
```

- Build mutations from the generated `*Mutation()` helpers. Use `mutateAsync`
  when the caller awaits the result and handles the error, `mutate` for
  fire-and-forget calls, and `request.isPending` for busy state.
- Afterwards, update only what nothing else updates:
  - Library items, collections, downloads and jobs change over the WebSocket.
    Never refetch an entity the server announces.
  - A response that holds the new value is written with
    `setQueryData(generatedOptions(args).queryKey, value)`, or with the matching
    helper in `src/lib/rest/cache.ts` (`upsertLibraryItem`, `patchCollection`).
  - Anything else is marked stale with `invalidateTags([...])`.

## Live updates

- `src/lib/realtime/cache.ts` (`applyRestCachePolicy`) applies every WebSocket
  event that changes cached data. A new event of that kind is registered in the
  backend's `ws/events.py` and handled there; components never subscribe to
  events to patch the cache themselves.
- Events that carry the entity write it into the cache. Those that cannot (an
  item event says nothing about its seasons) invalidate what they leave out, such
  as `invalidateSeasons(itemId)`.
- On reconnect, `invalidateReconnectData()` and `refreshRemovedDownloadTargets()`
  catch up on what was missed, once per target.

## Cache reads and writes

- Address cached data through generated keys (`someOptions(args).queryKey`) or
  through the operation id `queryOperationId` reads, never through hand-built
  arrays.
- A write that touches more than one query belongs in `src/lib/rest/cache.ts`,
  which keeps library lists, detail queries and TMDB answers consistent with each
  other. Add a helper there rather than writing to several queries from a
  component; a mutation's response for its own query is written in place.
- Outside a component, read a value with
  `queryClient.fetchQuery(someOptions(args))`; it answers from the cache while
  the value is fresh. Prefetch a popup's data on hover or focus with
  `queryClient.prefetchQuery`, so it opens complete.

## Testing

- Render components through `renderWithQueryClient` from
  `src/test/helpers/render.ts`, which provides the app's client, and call
  `queryClient.clear()` in `beforeEach`.
- Seed data with `queryClient.setQueryData(someOptions(args).queryKey, value)`.
  Answer requests with `mockFetchRoutes`, `mockFetchSequence` or `mockFetch` from
  `src/test/helpers/fetch.ts`, or mock the functions of `generated/rest/sdk.gen`
  with `vi.mock` when a test is about one call.
- Assert what the user sees, and that no redundant request is made, rather than
  how the cache is written.

## Reference

- Svelte Query overview: https://tanstack.com/query/latest/docs/framework/svelte/overview
- Migrating from v5 (stores) to v6 (runes): https://tanstack.com/query/latest/docs/framework/svelte/migrate-from-v5-to-v6
- Svelte API reference: https://tanstack.com/query/latest/docs/framework/svelte/reference/index
