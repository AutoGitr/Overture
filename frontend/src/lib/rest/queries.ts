import { createQuery } from "@tanstack/svelte-query";
import { getSeasonsOptions } from "../../generated/rest/@tanstack/svelte-query.gen";
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
