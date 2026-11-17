import { createQueries, createQuery, keepPreviousData } from "@tanstack/svelte-query";
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

/** Every library of every server, of either media type. Create during initialisation. */
export function allLibraries(enabled: () => boolean = () => true) {
  return createQuery(() => ({ ...getLibrariesOptions(), enabled: enabled() }));
}

/**
 * *entries* in the order the servers list their libraries, movies first, whatever
 * order they were chosen in; a library no server lists any more goes last.
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

/** A library a collection spans, by Overture's ID, and what it holds. */
export interface ChosenLibrary {
  id: string;
  media_type: MediaType;
}

/**
 * What collections can do, by media type, on the servers of the libraries
 * they span (every configured server without any): their fields and sources
 * differ. Each library's own server decides what its criteria can test.
 */
export class CollectionOptions {
  private readonly libraries: () => readonly ChosenLibrary[];
  private readonly movie;
  private readonly show;
  private readonly byLibrary;

  constructor(libraries: () => readonly ChosenLibrary[] = () => []) {
    this.libraries = libraries;
    this.movie = this.query("movie");
    this.show = this.query("show");
    this.byLibrary = createQueries(() => ({
      queries: this.libraries().map((library) => ({
        ...getCollectionCapabilitiesOptions({
          query: { media_type: library.media_type, library_ids: [library.id] },
        }),
        enabled: settingsState.current.collections_supported,
      })),
    }));
  }

  private query(media_type: MediaType) {
    return createQuery(() => {
      const ids = this.libraries()
        .filter((library) => library.media_type === media_type)
        .map((library) => library.id);
      return {
        ...getCollectionCapabilitiesOptions({
          query: { media_type, library_ids: ids.length ? ids : undefined },
        }),
        // Choosing a library asks again; the form keeps its fields meanwhile.
        placeholderData: keepPreviousData,
        enabled: settingsState.current.collections_supported,
      };
    });
  }

  for(mediaType: MediaType) {
    return mediaType === "show" ? this.show : this.movie;
  }

  /** What one of the libraries' server lets its collections test. */
  forLibrary(libraryId: string, mediaType: MediaType): CollectionCapabilities | undefined {
    const index = this.libraries().findIndex((library) => library.id === libraryId);
    return (index === -1 ? undefined : this.byLibrary[index]?.data) ?? this.for(mediaType).data;
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
