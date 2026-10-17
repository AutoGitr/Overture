---
name: svelte-query
description: TanStack Svelte Query v6 with Svelte 5 runes, as Overture uses it with its generated REST client. Use whenever a Svelte component or frontend module reads server data, runs a mutation, or reads or updates the query cache.
---

# Svelte Query in Overture

Overture uses `@tanstack/svelte-query` 6 (Svelte 5 runes on top of `@tanstack/query-core` 5). Most Query material online is written for React or for the store-based v5 adapter; neither applies here. There are no hooks and no stores: `create*` functions take option thunks and return reactive objects.

## The client

- The app has one `QueryClient`: `queryClient` in `src/lib/rest/queryClient.ts`. It owns the cache policy (stale time per operation id, retry rules, network mode). Never create another one in application code.
- `src/Root.svelte` provides it with `<QueryClientProvider client={queryClient}>`. Components rely on that context: call `createQuery` and `createMutation` without a client argument, and call `useQueryClient()` during component initialisation when a component needs the client itself.
- Code that runs outside a component (`src/lib/rest/`, `src/lib/realtime/`, stores and utilities) imports `queryClient` directly.
- Component tests render through `renderWithQueryClient` from `src/test/helpers/render.ts`, which provides the same client.

## Queries

```svelte
<script lang="ts">
  import { createQuery } from "@tanstack/svelte-query";
  import { getSeasonsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";

  let { item }: { item: MediaItemRead | null } = $props();

  const seasons = createQuery(() => ({
    ...getSeasonsOptions({ path: { item_id: item?.id ?? 0 } }),
    enabled: item?.media_type === "show",
  }));
  let rows = $derived(seasons.data ?? []);
</script>

{#if seasons.isPending}...{:else if seasons.isError}{seasons.error.message}{/if}
```

- Pass options as a function (`() => ({ ... })`). Everything reactive that the function reads (props, `$state`, `$derived`) re-configures the query when it changes; a plain object would freeze the first values.
- Build options from the generated `*Options()` helpers in `src/generated/rest/@tanstack/svelte-query.gen.ts`. They carry the query key and the fetcher; spread them and add only `enabled`, `select` or `placeholderData`. Never hand-write a key or a `queryFn` for an API call.
- Read the result as an object (`query.data`, `query.isPending`, `query.error`). Do not destructure it, which loses reactivity, and do not prefix it with `$`; it is not a store. Derive values with `$derived`.
- Call `create*` once, during component initialisation. To skip a request, set `enabled: false`; never create queries conditionally, in event handlers or in effects.
- Stale times belong in `STALE_TIME_BY_OPERATION` in `queryClient.ts`, not in components. A caller that needs a fresh value outside a component uses `queryClient.fetchQuery({ ...someOptions(), staleTime: 0 })`, as `src/lib/rest/queries.ts` does.

## Mutations

```ts
const saveArtRequest = createMutation(() => saveArtMutation());

const result = await saveArtRequest.mutateAsync({ path: { item_id, art_type }, body });
```

- Build mutations from the generated `*Mutation()` helpers. Use `mutateAsync` when the caller awaits the result and handles the error, `mutate` for fire-and-forget calls, and `request.isPending` for busy state.
- After a mutation, update only what nothing else updates. Library items, jobs and collections arrive over the WebSocket and are applied to the cache by `src/lib/realtime/` and `src/lib/rest/cache.ts`; use the helpers there instead of patching those queries again. Otherwise write the returned value with `setQueryData(generatedOptions().queryKey, value)`, or call `invalidateTags` from `src/lib/rest/cache.ts`.

## Cache reads and writes

- Address cached data through generated keys (`someOptions(args).queryKey`) or through the operation id read by `queryOperationId`, never through hand-built arrays.
- Prefer `setQueryData` with the server's response over invalidating and refetching when the response already holds the new value.

## Reference

- Svelte Query overview: https://tanstack.com/query/latest/docs/framework/svelte/overview
- Migrating from v5 (stores) to v6 (runes): https://tanstack.com/query/latest/docs/framework/svelte/migrate-from-v5-to-v6
- Svelte API reference: https://tanstack.com/query/latest/docs/framework/svelte/reference/index
