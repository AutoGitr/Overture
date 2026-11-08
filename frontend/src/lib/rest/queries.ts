import { createQuery } from "@tanstack/svelte-query";
import {
  getSeasonsOptions,
  getServerWebLinksOptions,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type { MediaItemRead } from "../../generated/rest/types.gen";

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
  const fill = (template: string | undefined, serverId: string | null | undefined) =>
    template && serverId ? template.replaceAll("{id}", encodeURIComponent(serverId)) : null;
  return {
    item: (serverId: string | null | undefined) => fill(links.data?.item, serverId),
    collection: (serverId: string | null | undefined) => fill(links.data?.collection, serverId),
  };
}
