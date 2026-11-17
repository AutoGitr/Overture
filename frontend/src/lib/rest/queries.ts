import { createQuery, queryOptions } from "@tanstack/svelte-query";
import {
  getSeasonsOptions,
  getServerWebLinksOptions,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import { matchLibraryFilter } from "../../generated/rest/sdk.gen";
import type { LibraryFilterMatchRequest, MediaItemRead } from "../../generated/rest/types.gen";
import { sdkData } from "./sdk";

/**
 * Observe an item's seasons.
 */
export function createSeasonsQuery(item: () => MediaItemRead | null) {
  return createQuery(() => {
    const current = item();
    return {
      ...getSeasonsOptions({ path: { item_id: current?.id ?? 0 } }),
      enabled: current?.media_type === "show",
    };
  });
}

/**
 * Observe where the media server's web app opens a title or collection.
 *
 * Each link is the server's template filled in with the server ID; there is
 * none without a server copy, or until the server answers.
 */
export function createServerLinks() {
  const links = createQuery(() => getServerWebLinksOptions());
  const fill = (
    kind: "item" | "collection",
    serverId: number | null | undefined,
    serverItemId: string | null | undefined,
  ) => {
    const template = links.data?.find((server) => server.server_id === serverId)?.[kind];
    return template && serverItemId
      ? template.replaceAll("{id}", encodeURIComponent(serverItemId))
      : null;
  };
  return {
    item: (serverId: number | null | undefined, serverItemId: string | null | undefined) =>
      fill("item", serverId, serverItemId),
    collection: (serverId: number | null | undefined, serverItemId: string | null | undefined) =>
      fill("collection", serverId, serverItemId),
  };
}

/**
 * The titles each of a custom filter's metadata and source conditions selects.
 *
 * Tagged with the library, so a sync or a collection change, which can change
 * what they select, asks again; nothing else does.
 */
export function libraryFilterMatchOptions(body: LibraryFilterMatchRequest) {
  return queryOptions({
    queryKey: [{ _id: "matchLibraryFilter", tags: ["library"], body }] as const,
    queryFn: ({ signal }) => sdkData(matchLibraryFilter({ body, signal, throwOnError: true })),
    staleTime: Infinity,
  });
}
