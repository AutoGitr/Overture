import type {
  CatalogEntryRow,
  CollectionRead,
  MediaItemRead,
  TmdbSearchBy,
} from "../../generated/rest/types.gen";
import { countOf } from "./plural";
import { keysOf } from "./records";
import { extractYouTubeId } from "./themeSearch";
import {
  hasKey,
  sortScope,
  type ListScope,
  type MenuEntry,
  type SidebarMode,
  type SidebarSource,
  type SidebarTab,
} from "./sidebarShared";

type Matcher<T> = (query: string) => (row: T) => boolean;

/** One search-by field, by the list it applies to; a list without a matcher lacks it. */
export interface SearchDef {
  label: string;
  /** What the field is called in the collection list, where it differs. */
  collectionsLabel?: string;
  placeholder?: string;
  movieOnly?: boolean;
  library?: Matcher<MediaItemRead>;
  collections?: Matcher<CollectionRead>;
  overturedb?: Matcher<CatalogEntryRow>;
  /** Searches TMDB on the server, for this, instead of filtering the library. */
  tmdb?: TmdbSearchBy;
}

function textMatcher<T>(text: (row: T) => string | null): Matcher<T> {
  return (query) => {
    const needle = query.toLowerCase();
    return (row) => text(row)?.toLowerCase().includes(needle) ?? false;
  };
}

function youtubeMatcher<T>(
  ids: (row: T) => (string | null)[],
  title: (row: T) => string | null,
): Matcher<T> {
  return (query) => {
    const linkedId = extractYouTubeId(query);
    const needle = query.toLowerCase();
    return (row) =>
      linkedId
        ? ids(row).includes(linkedId)
        : ids(row).some((id) => id?.toLowerCase() === needle) ||
          (title(row)?.toLowerCase().includes(needle) ?? false);
  };
}

function externalIdMatcher<
  T extends { tmdb_id: number | null; tvdb_id: number | null; imdb_id: string | null },
>(): Matcher<T> {
  return (query) => {
    // A pasted IMDb link carries its ID; every other ID must match exactly.
    const id = (/tt\d+/i.exec(query)?.[0] ?? query).toLowerCase();
    return (row) =>
      [row.tmdb_id, row.tvdb_id, row.imdb_id].some(
        (value) => value != null && String(value).toLowerCase() === id,
      );
  };
}

/** Every search-by field, in menu order. */
export const SEARCHES = {
  title: {
    label: "Title",
    collectionsLabel: "Title or TMDB collection ID",
    library: textMatcher((item) => item.title),
    collections: (query) => {
      const byTitle = textMatcher<CollectionRead>((collection) => collection.title)(query);
      return (collection) =>
        String(collection.tmdb_collection_id ?? "") === query || byTitle(collection);
    },
    overturedb: textMatcher((entry) => entry.title),
  },
  director: {
    label: "Director",
    placeholder: "Search directors...",
    movieOnly: true,
    library: textMatcher((item) =>
      item.media_type === "movie" ? item.directors.join("\n") : null,
    ),
  },
  studio: {
    label: "Studio",
    placeholder: "Search studios...",
    library: textMatcher((item) => item.studio),
  },
  group: {
    label: "Group",
    placeholder: "Search groups...",
    collections: textMatcher((collection) => collection.collection_group),
  },
  year: {
    label: "Year",
    placeholder: "Search years...",
    library: (query) => (item) => String(item.year ?? "").startsWith(query),
    overturedb: (query) => (entry) => String(entry.year ?? "").startsWith(query),
  },
  external_id: {
    label: "TMDB, TVDB or IMDb ID",
    placeholder: "Search IDs...",
    library: externalIdMatcher(),
    overturedb: externalIdMatcher(),
  },
  youtube: {
    label: "YouTube link, ID or title",
    placeholder: "Search YouTube...",
    library: youtubeMatcher(
      (item) => [item.assets.theme.youtube_id],
      (item) => item.assets.theme.youtube_title,
    ),
    collections: youtubeMatcher(
      (collection) => [collection.assets.theme.youtube_id],
      (collection) => collection.assets.theme.youtube_title,
    ),
    overturedb: youtubeMatcher(
      (entry) => [entry.youtube_id_overturedb, entry.youtube_id_themerrdb],
      () => null,
    ),
  },
  // Listed under a "TMDB" heading, apart from the library fields.
  tmdb: {
    label: "Title or ID",
    placeholder: "Search TMDB by title or ID...",
    tmdb: "title",
  },
  tmdbPerson: {
    label: "Person",
    placeholder: "A person's name, TMDB ID or link...",
    tmdb: "person",
  },
  tmdbCompany: {
    label: "Company",
    placeholder: "A company's name, TMDB ID or link...",
    tmdb: "company",
  },
  tmdbKeyword: {
    label: "Keyword",
    placeholder: "A keyword, TMDB ID or link...",
    tmdb: "keyword",
  },
  tmdbList: {
    label: "List",
    placeholder: "A TMDB list's ID or link...",
    tmdb: "list",
  },
} as const satisfies Record<string, SearchDef>;
export type SidebarSearchField = keyof typeof SEARCHES;

export function searchDef(field: string): SearchDef | undefined {
  return hasKey(SEARCHES, field) ? SEARCHES[field] : undefined;
}

export interface SearchFieldGroup {
  label: "Library" | "TMDB" | "OvertureDB" | "Collections";
  fields: MenuEntry<SidebarSearchField>[];
}

function searchEntries(
  fields: readonly SidebarSearchField[],
  scope: ListScope,
): MenuEntry<SidebarSearchField>[] {
  return fields.map((id) => {
    const field: SearchDef = SEARCHES[id];
    const label = (scope === "collections" && field.collectionsLabel) || field.label;
    return { id, label, shortLabel: label };
  });
}

/** What a search field looks for on TMDB, or null for a field of the list. */
export function tmdbSearchBy(field: SidebarSearchField): TmdbSearchBy | null {
  return searchDef(field)?.tmdb ?? null;
}

/** The search fields a list offers: its own first, then TMDB's in every list. */
export function searchFieldGroups(
  source: SidebarSource,
  mode: SidebarMode,
  tab: SidebarTab,
  tmdbConfigured: boolean,
): SearchFieldGroup[] {
  const scope = sortScope(source, mode);
  const fields = keysOf(SEARCHES).filter((id) => {
    const field: SearchDef = SEARCHES[id];
    return tab === "movie" || !field.movieOnly;
  });
  const groups: SearchFieldGroup[] = [
    {
      label:
        scope === "overturedb" ? "OvertureDB" : scope === "collections" ? "Collections" : "Library",
      fields: searchEntries(
        fields.filter((id) => searchDef(id)?.[scope]),
        scope,
      ),
    },
    {
      label: "TMDB",
      // A collection list searches TMDB for collections, which only a title finds.
      fields: searchEntries(
        fields.filter(
          (id) =>
            tmdbConfigured &&
            !!searchDef(id)?.tmdb &&
            (mode === "items" || searchDef(id)?.tmdb === "title"),
        ),
        scope,
      ),
    },
  ];
  return groups.filter((group) => group.fields.length > 0);
}

/** What the search box says, naming the field or what it searches. */
export function searchPlaceholder(
  mode: SidebarMode,
  tab: SidebarTab,
  field: SidebarSearchField,
  count: number,
): string {
  const placeholder = searchDef(field)?.placeholder;
  if (placeholder) return placeholder;
  if (mode === "collections") return `Search ${countOf(count, "collection")}...`;
  return `Search ${count} ${tab === "movie" ? "movies" : "shows"}...`;
}
