import {
  sidebarState,
  type SidebarListed,
  type SidebarSearched,
} from "../../lib/stores/sidebarState.svelte";

/** Make the sidebar list *shown*, keeping the rest of what it lists. */
export function showInSidebar(shown: Partial<SidebarListed>): void {
  sidebarState.listed = {
    view: "",
    current: null,
    listedCollections: null,
    records: null,
    ...sidebarState.listed,
    ...shown,
  };
}

/** Make the sidebar's TMDB search show *searched*, keeping the rest of what it shows. */
export function searchInSidebar(searched: Partial<SidebarSearched>): void {
  sidebarState.searched = { results: [], records: [], ...sidebarState.searched, ...searched };
}
