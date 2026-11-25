import { goToCatalog, goToCollectionsList, goToLibrary, routeScope } from "../router/routes";
import { tmdbSearchBy, type SidebarSearchField } from "../utils/sidebarSearches";
import type {
  CollectionView,
  SidebarMode,
  SidebarSource,
  SidebarTab,
} from "../utils/sidebarShared";
import { readJson, stringOption, writeJson } from "../utils/storage";
import type { CollectionPosterStyle } from "../../generated/rest/types.gen";
import { COLLECTION_POSTER_STYLES } from "../utils/collectionPosters";
import { settingsState } from "./settingsState.svelte";

export type OperationsTab = "assets" | "sync" | "renamer" | "audit";

export type PopupType =
  | null
  | "api-keys"
  | "filters"
  | "notifications"
  | "operations"
  | "settings"
  | "database"
  | "overturedb"
  | "backup"
  | "stats";

class UiState {
  searchQuery = $state("");
  searchField = $state<SidebarSearchField>("title");
  /** The sidebar section the search belongs to. */
  #searchSection = "";
  collectionView = $state<CollectionView>(
    readJson<unknown>("overture_collection_view", "groups") === "collections"
      ? "collections"
      : "groups",
  );
  mobileShowDetail = $state(false);

  /** Which OvertureDB poster the catalog's collections show and edit. */
  catalogPosters = $state<CollectionPosterStyle>(
    stringOption(
      readJson<unknown>("overture_catalog_posters", null),
      COLLECTION_POSTER_STYLES,
      "individual",
    ),
  );

  setCatalogPosters(posters: CollectionPosterStyle) {
    this.catalogPosters = posters;
    writeJson("overture_catalog_posters", posters);
  }

  operationsTab = $state<OperationsTab>("assets");
  /**
   * Which popup overlay is open.
   *
   * Purely in-memory UI state - popups are never reflected in the URL, so
   * they're never linkable/bookmarkable, never recreated by browser
   * back/forward navigation or a page refresh, and never interact with the
   * router in any way.
   */
  #openPopup = $state<PopupType>(null);

  get openPopup(): PopupType {
    return this.#openPopup;
  }

  openPopupByName(name: PopupType) {
    this.#openPopup = name;
  }

  openOperations(tab: OperationsTab = "assets") {
    this.operationsTab = tab;
    this.#openPopup = "operations";
  }

  closePopup() {
    this.#openPopup = null;
  }

  /** What the search looks up on TMDB, or null while it filters the list. */
  get tmdbSearchBy() {
    return tmdbSearchBy(this.searchField);
  }

  /** The search looks up TMDB rather than filtering the list. */
  get searchingTmdb(): boolean {
    return this.tmdbSearchBy !== null;
  }

  /** Which top-level tab (movies/shows) is active, derived from the URL. */
  get sidebarTab(): SidebarTab {
    return routeScope().tab;
  }

  /** Whether the sidebar is showing individual items or server collections, derived from the URL. */
  get sidebarMode(): SidebarMode {
    return routeScope().mode;
  }

  get sidebarSource() {
    return routeScope().source;
  }

  /** The sidebar's source, tab and mode together: what the search box searches. */
  get sidebarSection(): string {
    const { source, tab, mode } = routeScope();
    return `${source}:${tab}:${mode}`;
  }

  setCollectionView(view: CollectionView) {
    this.collectionView = view;
    writeJson("overture_collection_view", view);
  }

  #startSearch(section: string) {
    if (section === this.#searchSection) return;
    this.#searchSection = section;
    this.searchQuery = "";
    this.searchField = "title";
  }

  /**
   * Show a sidebar section with an empty search. The search starts over as the
   * control is used, not once the route settles, so what is typed meanwhile
   * stays; `followSection` covers navigation no control started.
   */
  goToSection(source: SidebarSource, tab: SidebarTab, mode: SidebarMode) {
    this.mobileShowDetail = false;
    const collections =
      mode === "collections" &&
      (source === "overturedb" || settingsState.current.collections_supported);
    this.#startSearch(`${source}:${tab}:${collections ? "collections" : "items"}`);
    if (source === "overturedb") goToCatalog(tab, collections ? "collections" : "items");
    else if (collections) goToCollectionsList();
    else goToLibrary(tab);
  }

  /** Start the search over after back, forward or a link changed the section. */
  followSection() {
    if (this.sidebarSection !== this.#searchSection) this.#startSearch(this.sidebarSection);
  }
}

export const uiState = new UiState();
