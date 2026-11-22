import { createQuery, queryOptions } from "@tanstack/svelte-query";
import {
  getSeasonsOptions,
  getServerWebLinksOptions,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import { matchLibraryFilter } from "../../generated/rest/sdk.gen";
import type {
  LibraryFilterMatchRequest,
  MediaItemRead,
  SeasonRead,
  TmdbItemPreview,
  TmdbSeasonPreview,
} from "../../generated/rest/types.gen";
import type { CatalogContext } from "../utils/catalogDraft";
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

/** What a title's seasons come from: a stored show, a TMDB title or a catalog entry. */
export interface SeasonSource {
  item: MediaItemRead | null;
  preview: TmdbItemPreview | null;
  catalog?: CatalogContext | null;
}

/**
 * Observe a title's seasons: a catalog entry's or a TMDB title's come with it,
 * and a stored show's are loaded.
 */
export function createTitleSeasons(source: () => SeasonSource) {
  const query = createSeasonsQuery(() => source().item);
  return {
    /** The stored show's seasons, for its load state and season IDs. */
    query,
    get seasons(): (SeasonRead | TmdbSeasonPreview)[] {
      const { item, preview, catalog } = source();
      if (catalog) return catalog.seasons;
      return item ? (query.data ?? []) : (preview?.seasons ?? []);
    },
    /** Whether every season is known, as a title that is not stored always is. */
    get loaded(): boolean {
      return !source().item || query.isSuccess;
    },
  };
}

/** A media server's copy of a title or collection. */
type ServerCopy = { server_id: number; server_item_id: string };

/**
 * Observe where each media server's web app opens a title or collection.
 *
 * A link is the copy's server's template filled in with its ID; there is
 * none without a copy, or until that server answers.
 */
export function createServerLinks() {
  const links = createQuery(() => getServerWebLinksOptions());
  const fill = (kind: "item" | "collection", copy: ServerCopy | undefined) => {
    if (!copy?.server_item_id) return null;
    const template = links.data?.find((server) => server.server_id === copy.server_id)?.[kind];
    return template ? template.replaceAll("{id}", encodeURIComponent(copy.server_item_id)) : null;
  };
  return {
    item: (copy: ServerCopy | undefined) => fill("item", copy),
    collection: (copy: ServerCopy | undefined) => fill("collection", copy),
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
