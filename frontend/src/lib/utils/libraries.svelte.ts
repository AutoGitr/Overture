import { createQuery } from "@tanstack/svelte-query";
import {
  getCollectionCapabilitiesOptions,
  getLibrariesOptions,
} from "../../generated/rest/@tanstack/svelte-query.gen";
import type {
  CollectionCapabilities,
  LibrarySectionRead,
  MediaType,
} from "../../generated/rest/types.gen";
import { settingsState } from "../stores/settingsState.svelte";

/** Every library of the server, of either media type. Create during initialisation. */
export function allLibraries(enabled: () => boolean = () => true) {
  return createQuery(() => ({ ...getLibrariesOptions(), enabled: enabled() }));
}

/**
 * *entries* in the order the server lists its libraries, movies first, whatever
 * order they were chosen in; a library the server no longer lists goes last.
 */
export function inLibraryOrder<T>(
  libraries: readonly LibrarySectionRead[],
  entries: readonly T[],
  libraryId: (entry: T) => string,
): T[] {
  const position = (entry: T) => {
    const index = libraries.findIndex((library) => library.id === libraryId(entry));
    return index === -1 ? libraries.length : index;
  };
  return entries.toSorted((a, b) => position(a) - position(b));
}

/** What collections can do, by media type: their fields and sources differ. */
export class CollectionOptions {
  private readonly movie = this.query("movie");
  private readonly show = this.query("show");

  private query(media_type: MediaType) {
    return createQuery(() => ({
      ...getCollectionCapabilitiesOptions({ query: { media_type } }),
      enabled: settingsState.current.collections_supported,
    }));
  }

  for(mediaType: MediaType) {
    return mediaType === "show" ? this.show : this.movie;
  }

  /** What collections holding all of *mediaTypes* can do; movies when there are none. */
  shared(mediaTypes: readonly MediaType[]): CollectionCapabilities | undefined {
    const [first = "movie", ...rest] = mediaTypes;
    const base = this.for(first).data;
    return rest.reduce((shared, mediaType) => {
      const other = this.for(mediaType).data;
      return shared && other ? commonCapabilities(shared, other) : undefined;
    }, base);
  }
}

/** What two media types' collections both offer. */
export function commonCapabilities(
  a: CollectionCapabilities,
  b: CollectionCapabilities,
): CollectionCapabilities {
  const within = <T>(mine: T[], theirs: T[], same: (x: T, y: T) => boolean) =>
    mine.filter((entry) => theirs.some((other) => same(entry, other)));
  return {
    ...a,
    arr: a.arr || b.arr,
    orders: a.orders.filter((order) => b.orders.includes(order)),
    smart_orders: a.smart_orders.filter((order) => b.smart_orders.includes(order)),
    fields: within(a.fields, b.fields, (x, y) => x.field === y.field),
    sources: within(a.sources, b.sources, (x, y) => x.type === y.type),
    dimensions: within(a.dimensions, b.dimensions, (x, y) => x.dimension === y.dimension),
    charts: a.charts.filter((chart) => b.charts.includes(chart)),
  };
}
