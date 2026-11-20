import { createRouter, searchParams } from "sv-router";
import type { ArtType } from "../../generated/rest/types.gen";
import type { CatalogTarget } from "../rest/cache";
import { notify } from "../stores/notificationState.svelte";
import { settingsState } from "../stores/settingsState.svelte";
import type { SidebarMode, SidebarSource, SidebarTab } from "../utils/sidebarDomain";
import { buildIdSlug, parseCatalogSlug, parseItemSlug, type ItemSlug } from "../utils/slug";

/**
 * Path-based routing for the whole app.
 *
 * URL shape:
 *   /movies                                    items, nothing selected
 *   /movies/:itemSlug                          an item ("{id}-{title}", or
 *                                              "tmdb-{tmdbId}-{title}" for a TMDB title
 *                                              not yet stored), default detail tab
 *   /movies/:itemSlug/art/:subtab              art tab (poster|background|seasons)
 *   /movies/:itemSlug/art/seasons/:seasonNum   a season's art, by season number
 *   /movies/:itemSlug/themes                   themes tab
 *   /collections                               collections, of movies and shows
 *   /collections/:collectionSlug/...           a collection ("{id}-{title}"), with art,
 *                                              themes, rule and settings views
 *   /overturedb/movies|shows|collections/...   the OvertureDB catalog, in the same shape
 * `/shows/...` mirrors `/movies/...`.
 *
 * Library slugs lead with the stored ID, which drives lookups; the title is only
 * there to make links readable. Catalog entries have no stored ID, so their slug
 * is the entry's file name (`tmdb-603`), which identifies it in OvertureDB too.
 * Seasons are addressed by number, which stays meaningful to a person reading
 * the URL.
 *
 * Route components are imported lazily, so the `goTo*` helpers stay cheap to load.
 */

export type ArtSubTab = "poster" | "background" | "seasons";

/** A stored item, or a TMDB title that its first selection stores. */
type SelectableItem = { title: string; media_type: SidebarTab } & (
  { id: number } | { id?: never; tmdb_id: number }
);
type SelectableCollection = { id: number; title: string };
type SelectableSeason = { season_num: number };

const loadLibraryPage = () => import("./pages/LibraryPage.svelte");
const loadCollectionPage = () => import("./pages/CollectionPage.svelte");
const loadItemPage = () => import("./pages/ItemPage.svelte");
const loadRedirectToLibrary = () => import("./pages/RedirectToLibrary.svelte");

const itemSubroutes = {
  "/": loadItemPage,
  "/art": loadItemPage,
  "/art/:subtab": loadItemPage,
  "/art/seasons/:seasonNum": loadItemPage,
  "/themes": loadItemPage,
};

const collectionSubroutes = {
  "/new": loadCollectionPage,
  "/": loadCollectionPage,
  "/:collectionSlug": {
    "/": loadCollectionPage,
    "/art": loadCollectionPage,
    "/art/:subtab": loadCollectionPage,
    "/themes": loadCollectionPage,
    "/rule": loadCollectionPage,
    "/settings": loadCollectionPage,
  },
};

const mediaTypeRoutes = {
  "/": loadLibraryPage,
  "/:itemSlug": itemSubroutes,
};

const loadCatalogPage = () => import("./pages/CatalogPage.svelte");
const loadCatalogEntryPage = () => import("./pages/CatalogEntryPage.svelte");

// A catalog collection has no seasons; library collections also have a rule and
// settings, which OvertureDB has no part in.
const catalogCollectionSubroutes = {
  "/": loadCatalogEntryPage,
  "/art": loadCatalogEntryPage,
  "/art/:subtab": loadCatalogEntryPage,
  "/themes": loadCatalogEntryPage,
};
const catalogEntrySubroutes = {
  ...catalogCollectionSubroutes,
  "/art/seasons/:seasonNum": loadCatalogEntryPage,
};

function catalogTypeRoutes<T>(entryRoutes: T) {
  return { "/": loadCatalogPage, "/:entrySlug": entryRoutes };
}

export const { navigate, route } = createRouter({
  hooks: {
    // A page whose code cannot be loaded leaves the one shown in place, so say
    // so rather than leaving a click without an answer.
    onError() {
      notify.error("The page could not be loaded. Check the connection to Overture.", {
        title: "Could not open this page",
        action: { label: "Reload", run: () => location.reload() },
      });
    },
  },
  "/movies": mediaTypeRoutes,
  "/shows": mediaTypeRoutes,
  "/collections": collectionSubroutes,
  "/overturedb": {
    layout: () => import("./pages/CatalogLayout.svelte"),
    "/movies": catalogTypeRoutes(catalogEntrySubroutes),
    "/shows": catalogTypeRoutes(catalogEntrySubroutes),
    "/collections": catalogTypeRoutes(catalogCollectionSubroutes),
  },
  // Anything unmatched (including a bare "/") opens an available library.
  "*": loadRedirectToLibrary,
});

/** Whether a navigation replaces the current history entry. */
type NavigateOptions = { replace?: boolean };

/** The detail view an item route shows. */
export type ItemView = {
  mode: "art" | "themes";
  artSubTab: ArtSubTab;
  drillSeasonNum: number | null;
};

/** The stored item or TMDB title the URL opens. */
export function routedItem(): ItemSlug | null {
  return parseItemSlug(route.params.itemSlug);
}

/** The ID of the stored item the URL opens. */
export function routedItemId(): number | null {
  const slug = routedItem();
  return slug?.kind === "item" ? slug.id : null;
}

/** The ID of the collection the URL opens. */
export function routedCollectionId(): number | null {
  const slug = parseItemSlug(route.params.collectionSlug);
  return slug?.kind === "item" ? slug.id : null;
}

export type CollectionView = "configure" | "art" | "themes";

export function routedCollectionView(): CollectionView {
  if (route.pathname.includes("/art")) return "art";
  if (route.pathname.endsWith("/themes")) return "themes";
  return "configure";
}

export function routedCollectionArtType(): "poster" | "background" {
  return route.params.subtab === "background" ? "background" : "poster";
}

/** Open a collection's view; `hash` names a configure section to show. */
export function goToCollectionView(
  collection: SelectableCollection,
  view: CollectionView,
  subtab: "poster" | "background" = "poster",
  hash?: string,
): void {
  const params = { collectionSlug: buildIdSlug(collection.id, collection.title), subtab };
  const options = { params, search: sidebarSearch(), hash };
  if (view === "configure") void navigate("/collections/:collectionSlug", options);
  else if (view === "art") void navigate("/collections/:collectionSlug/art/:subtab", options);
  else void navigate("/collections/:collectionSlug/themes", options);
}

/** The URL owns the sidebar's source, tab and mode together. */
export function routeScope(): { source: SidebarSource; tab: SidebarTab; mode: SidebarMode } {
  const parts = route.pathname.split("/").filter(Boolean);
  if (parts[0] === "collections") return { source: "library", tab: "movie", mode: "collections" };
  if (parts[0] !== "overturedb") {
    return { source: "library", tab: parts[0] === "shows" ? "show" : "movie", mode: "items" };
  }
  return {
    source: "overturedb",
    tab: parts[1] === "shows" ? "show" : "movie",
    mode: parts[1] === "collections" ? "collections" : "items",
  };
}

export function routedCatalogEntry(): CatalogTarget | null {
  const scope = routeScope();
  const entryKey = parseCatalogSlug(route.params.entrySlug);
  return scope.source === "overturedb" && entryKey
    ? { media_type: scope.mode === "collections" ? "collection" : scope.tab, entry_key: entryKey }
    : null;
}

function catalogBase(type: CatalogTarget["media_type"]) {
  return type === "collection"
    ? "/overturedb/collections"
    : type === "show"
      ? "/overturedb/shows"
      : "/overturedb/movies";
}

export function goToCatalog(tab: SidebarTab, mode: SidebarMode = "items"): void {
  void navigate(catalogBase(mode === "collections" ? "collection" : tab));
}

/** Open a catalog identity, whose key remains resolvable when another ID is added. */
export function goToCatalogEntry(entry: CatalogTarget, view?: ItemView): void {
  const base = catalogBase(entry.media_type);
  const options = {
    params: {
      entrySlug: entry.entry_key,
      subtab: view?.artSubTab ?? "poster",
      seasonNum: String(view?.drillSeasonNum ?? 0),
    },
    search: sidebarSearch(),
  };
  if (!view) void navigate(`${base}/:entrySlug`, options);
  else if (view.mode === "themes") void navigate(`${base}/:entrySlug/themes`, options);
  else if (view.drillSeasonNum !== null && entry.media_type === "show")
    void navigate("/overturedb/shows/:entrySlug/art/seasons/:seasonNum", options);
  else void navigate(`${base}/:entrySlug/art/:subtab`, options);
}

/** The detail view the URL names; a bare item route opens the configured tab. */
export function routedItemView(): ItemView {
  const { pathname } = route;
  if (pathname.endsWith("/themes")) {
    return { mode: "themes", artSubTab: "poster", drillSeasonNum: null };
  }
  if (!pathname.includes("/art")) {
    return { mode: settingsState.initial_tab, artSubTab: "poster", drillSeasonNum: null };
  }
  const { seasonNum, subtab } = route.params;
  if (seasonNum) return { mode: "art", artSubTab: "seasons", drillSeasonNum: Number(seasonNum) };
  return {
    mode: "art",
    artSubTab: subtab === "background" || subtab === "seasons" ? subtab : "poster",
    drillSeasonNum: null,
  };
}

/** The artwork slot type an art view shows. */
export function viewArtType(view: ItemView): ArtType {
  return view.artSubTab === "seasons" ? "season_poster" : view.artSubTab;
}

function tabBase(tab: SidebarTab): "/movies" | "/shows" {
  return tab === "show" ? "/shows" : "/movies";
}

function itemSlug(item: SelectableItem): string {
  return buildIdSlug(item.id ?? `tmdb-${item.tmdb_id}`, item.title);
}

/** Navigate to the root library view (items mode, nothing selected) for a tab. */
export function goToLibrary(tab: SidebarTab): void {
  void navigate(tabBase(tab));
}

/** Navigate to the collections list, optionally inside a group. */
export function goToCollectionsList(group?: string): void {
  const search: Record<string, string> = group ? { collection_group: `group:${group}` } : {};
  void navigate("/collections", { search });
}

/** Close the open collection, leaving the sidebar where it is, such as in a group. */
export function closeCollection(): void {
  void navigate("/collections", { search: sidebarSearch() });
}

export function goToNewCollection(tmdbId?: number): void {
  const search = {
    draft: crypto.randomUUID(),
    ...(tmdbId === undefined ? {} : { tmdb_id: tmdbId }),
  };
  void navigate("/collections/new", { search });
}

export function sidebarGroup(): string | null {
  const value = searchParams.get("collection_group");
  return typeof value === "string" && value.startsWith("group:") ? value.slice(6) : null;
}

export function openSidebarGroup(group: string | null): void {
  if (group === null) searchParams.delete("collection_group");
  else searchParams.set("collection_group", `group:${group}`);
}

function sidebarSearch(): Record<string, string | number | boolean> {
  const search: Record<string, string | number | boolean> = {};
  for (const key of ["collection_group", "tmdb_collection", "tmdb_query"]) {
    const value = searchParams.get(key);
    if (value !== null) search[key] = value;
  }
  return search;
}

export { searchParams };

/** Navigate to a specific collection. */
export function goToCollection(collection: SelectableCollection): void {
  void navigate("/collections/:collectionSlug", {
    params: { collectionSlug: buildIdSlug(collection.id, collection.title) },
    search: sidebarSearch(),
  });
}

/** Open *item*'s detail view; resolves once its route, loaded lazily, is shown. */
export function goToItem(
  item: SelectableItem,
  { replace }: NavigateOptions = {},
): Promise<unknown> {
  return navigate(`${tabBase(item.media_type)}/:itemSlug`, {
    params: { itemSlug: itemSlug(item) },
    replace,
    search: sidebarSearch(),
  });
}

/** Navigate to an item's Art tab, optionally on a specific sub-tab. */
export function goToItemArt(
  item: SelectableItem,
  subtab: ArtSubTab = "poster",
  { replace }: NavigateOptions = {},
): void {
  void navigate(`${tabBase(item.media_type)}/:itemSlug/art/:subtab`, {
    params: { itemSlug: itemSlug(item), subtab },
    replace,
    search: sidebarSearch(),
  });
}

/** Navigate to an item's Themes tab. */
export function goToItemThemes(item: SelectableItem, { replace }: NavigateOptions = {}): void {
  void navigate(`${tabBase(item.media_type)}/:itemSlug/themes`, {
    params: { itemSlug: itemSlug(item) },
    replace,
    search: sidebarSearch(),
  });
}

/** Drill into a specific season's art for a show. */
export function goToSeason(
  item: SelectableItem,
  season: SelectableSeason,
  { replace }: NavigateOptions = {},
): void {
  void navigate(`${tabBase(item.media_type)}/:itemSlug/art/seasons/:seasonNum`, {
    params: { itemSlug: itemSlug(item), seasonNum: String(season.season_num) },
    replace,
    search: sidebarSearch(),
  });
}

/** Show *item* in *view*, as when a TMDB title opens as the item it became. */
export function goToItemView(
  item: SelectableItem,
  view: ItemView,
  options?: NavigateOptions,
): void {
  if (view.mode === "themes") goToItemThemes(item, options);
  else if (view.drillSeasonNum !== null) {
    goToSeason(item, { season_num: view.drillSeasonNum }, options);
  } else goToItemArt(item, view.artSubTab, options);
}

/** Back out of a season drill-in to the season grid. */
export function goToSeasonsList(item: SelectableItem): void {
  goToItemArt(item, "seasons");
}
