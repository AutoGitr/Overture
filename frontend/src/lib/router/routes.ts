import { createRouter } from "sv-router";
import type { ArtType, CatalogMediaType } from "../../generated/rest/types.gen";
import { settingsState } from "../stores/settingsState.svelte";
import type { SidebarMode, SidebarSource, SidebarTab } from "../utils/sidebarDomain";
import { buildIdSlug, parseCatalogSlug, parseItemSlug, type ItemSlug } from "../utils/slug";

/**
 * Path-based routing for the whole app.
 *
 * URL shape:
 *   /movies                                   items mode, nothing selected
 *   /movies/collections                       collections list
 *   /movies/collections/:collectionSlug        a selected collection ("{id}-{title}")
 *   /movies/:itemSlug                          a selected item ("{id}-{title}", or
 *                                              "tmdb-{tmdbId}-{title}" for a TMDB title
 *                                              not yet stored), default detail tab
 *   /movies/:itemSlug/art                      art tab, poster sub-tab
 *   /movies/:itemSlug/art/:subtab              art tab, explicit sub-tab (poster|background|seasons)
 *   /movies/:itemSlug/art/seasons/:seasonNum   art tab, drilled into a season (by season number)
 *   /movies/:itemSlug/themes                   themes tab
 * `/shows/...` mirrors the same shape for the shows tab.
 *
 * Item and collection ids are carried inside an `{id}-{title}` slug (e.g.
 * `42-the-matrix`) rather than a bare id, so links double as a readable,
 * shareable summary of what they point to. The numeric id is always the
 * leading segment and is what actually drives lookups - the title suffix is
 * cosmetic and never parsed for anything but display. Seasons are addressed
 * by their season number (stable and meaningful to a person reading the
 * URL) rather than their internal database id. Collections use their own database
 * ID, independent of the media server's ID.
 *
 * The route tree below is intentionally shared between `/movies` and `/shows` -
 * both tabs support exactly the same set of views, just scoped to a different
 * media type.
 *
 * Route components are dynamically imported so that this module (and anything
 * that only needs the `goTo*` navigation helpers below) stays cheap to load -
 * the detail-view components are only fetched once a matching route is hit.
 */

export type ArtSubTab = "poster" | "background" | "seasons";

/** A stored item, or a TMDB title that its first selection stores. */
type SelectableItem = { title: string; media_type: SidebarTab } & (
  { id: number } | { id?: never; tmdb_id: number }
);
type SelectableCollection = { id: number; title: string; media_type: SidebarTab };
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
  "/": loadCollectionPage,
  "/:collectionSlug": loadCollectionPage,
};

const mediaTypeRoutes = {
  "/": loadLibraryPage,
  "/collections": collectionSubroutes,
  "/:itemSlug": itemSubroutes,
};

const catalogEntrySubroutes = {
  "/": () => import("./pages/CatalogEntryPage.svelte"),
  "/art": () => import("./pages/CatalogEntryPage.svelte"),
  "/art/:subtab": () => import("./pages/CatalogEntryPage.svelte"),
  "/art/seasons/:seasonNum": () => import("./pages/CatalogEntryPage.svelte"),
  "/themes": () => import("./pages/CatalogEntryPage.svelte"),
};
const catalogCollectionSubroutes = {
  "/": () => import("./pages/CatalogCollectionPage.svelte"),
  "/art": () => import("./pages/CatalogCollectionPage.svelte"),
  "/art/:subtab": () => import("./pages/CatalogCollectionPage.svelte"),
  "/themes": () => import("./pages/CatalogCollectionPage.svelte"),
};

export const { navigate, route } = createRouter({
  "/movies": mediaTypeRoutes,
  "/shows": mediaTypeRoutes,
  "/overturedb/movies": {
    "/": () => import("./pages/CatalogPage.svelte"),
    "/collections": {
      "/": () => import("./pages/CatalogPage.svelte"),
      "/:entrySlug": catalogCollectionSubroutes,
    },
    "/:entrySlug": catalogEntrySubroutes,
  },
  "/overturedb/shows": {
    "/": () => import("./pages/CatalogPage.svelte"),
    "/:entrySlug": catalogEntrySubroutes,
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

/** The URL owns the sidebar's source, tab and mode together. */
export function routeScope(): { source: SidebarSource; tab: SidebarTab; mode: SidebarMode } {
  const parts = route.pathname.split("/").filter(Boolean);
  const source = parts[0] === "overturedb" ? "overturedb" : "library";
  const offset = source === "overturedb" ? 1 : 0;
  return {
    source,
    tab: parts[offset] === "shows" ? "show" : "movie",
    mode: parts[offset + 1] === "collections" ? "collections" : "items",
  };
}

export type CatalogTarget = { media_type: CatalogMediaType; entry_key: string };

export function routedCatalogEntry(): CatalogTarget | null {
  const scope = routeScope();
  const entryKey = parseCatalogSlug(route.params.entrySlug);
  return scope.source === "overturedb" && entryKey
    ? { media_type: scope.mode === "collections" ? "collection" : scope.tab, entry_key: entryKey }
    : null;
}

export function goToCatalog(tab: SidebarTab, mode: SidebarMode = "items"): void {
  if (tab === "show") void navigate("/overturedb/shows");
  else if (mode === "collections") void navigate("/overturedb/movies/collections");
  else void navigate("/overturedb/movies");
}

/** Open a catalog identity, whose key remains resolvable when another ID is added. */
export function goToCatalogEntry(entry: CatalogTarget, view?: ItemView): void {
  const params = {
    entrySlug: entry.entry_key,
    subtab: view?.artSubTab ?? "poster",
    seasonNum: String(view?.drillSeasonNum ?? 0),
  };
  if (entry.media_type === "collection") {
    if (view?.mode === "themes")
      void navigate("/overturedb/movies/collections/:entrySlug/themes", { params });
    else if (view)
      void navigate("/overturedb/movies/collections/:entrySlug/art/:subtab", { params });
    else void navigate("/overturedb/movies/collections/:entrySlug", { params });
  } else if (entry.media_type === "show") {
    if (view?.mode === "themes") void navigate("/overturedb/shows/:entrySlug/themes", { params });
    else if (view?.drillSeasonNum !== null && view?.drillSeasonNum !== undefined)
      void navigate("/overturedb/shows/:entrySlug/art/seasons/:seasonNum", { params });
    else if (view) void navigate("/overturedb/shows/:entrySlug/art/:subtab", { params });
    else void navigate("/overturedb/shows/:entrySlug", { params });
  } else {
    if (view?.mode === "themes") void navigate("/overturedb/movies/:entrySlug/themes", { params });
    else if (view) void navigate("/overturedb/movies/:entrySlug/art/:subtab", { params });
    else void navigate("/overturedb/movies/:entrySlug", { params });
  }
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

/** Navigate to the collections list for a tab. */
export function goToCollectionsList(tab: SidebarTab): void {
  if (tab === "show") void navigate("/shows/collections");
  else void navigate("/movies/collections");
}

/** Navigate to a specific collection. */
export function goToCollection(collection: SelectableCollection): void {
  const collectionSlug = buildIdSlug(collection.id, collection.title);
  if (collection.media_type === "show") {
    void navigate("/shows/collections/:collectionSlug", { params: { collectionSlug } });
  } else {
    void navigate("/movies/collections/:collectionSlug", { params: { collectionSlug } });
  }
}

/** Navigate to an item using whichever detail tab is configured as the default. */
/** Open *item*'s detail view; resolves once its route, loaded lazily, is shown. */
export function goToItem(
  item: SelectableItem,
  { replace }: NavigateOptions = {},
): Promise<unknown> {
  const params = { itemSlug: itemSlug(item) };
  return item.media_type === "show"
    ? navigate("/shows/:itemSlug", { params, replace })
    : navigate("/movies/:itemSlug", { params, replace });
}

/** Navigate to an item's Art tab, optionally on a specific sub-tab. */
export function goToItemArt(
  item: SelectableItem,
  subtab: ArtSubTab = "poster",
  { replace }: NavigateOptions = {},
): void {
  const params = { itemSlug: itemSlug(item), subtab };
  if (item.media_type === "show") {
    void navigate("/shows/:itemSlug/art/:subtab", { params, replace });
  } else {
    void navigate("/movies/:itemSlug/art/:subtab", { params, replace });
  }
}

/** Navigate to an item's Themes tab. */
export function goToItemThemes(item: SelectableItem, { replace }: NavigateOptions = {}): void {
  const params = { itemSlug: itemSlug(item) };
  if (item.media_type === "show") void navigate("/shows/:itemSlug/themes", { params, replace });
  else void navigate("/movies/:itemSlug/themes", { params, replace });
}

/** Drill into a specific season's art for a show. */
export function goToSeason(
  item: SelectableItem,
  season: SelectableSeason,
  { replace }: NavigateOptions = {},
): void {
  const params = { itemSlug: itemSlug(item), seasonNum: String(season.season_num) };
  if (item.media_type === "show") {
    void navigate("/shows/:itemSlug/art/seasons/:seasonNum", { params, replace });
  } else {
    void navigate("/movies/:itemSlug/art/seasons/:seasonNum", { params, replace });
  }
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
